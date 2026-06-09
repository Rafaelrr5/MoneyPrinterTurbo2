"""WebUI input-visibility controls.

Lets an operator declutter the Streamlit WebUI without editing code:
- **Trim dropdowns**: choose which entries appear in a categorical dropdown.
- **Hide fields**: hide individual controls entirely (the hidden control falls
  back to its default value in ``Main.py``).

All state lives under the ``[ui]`` section of ``config.toml`` (one of the four
sections ``config.save_config()`` persists). Semantics are intentionally
fail-open so existing configs keep working unchanged:

- An ``enabled_*`` list that is missing/empty => **show every entry**.
- ``hidden_fields`` missing/empty => **hide nothing**.

The pure helpers here have no Streamlit dependency so they can be unit tested;
``render_visibility_panel`` imports Streamlit lazily.
"""

from app.config import config

# ---------------------------------------------------------------------------
# Dropdown catalogs (single source of truth for what *can* be shown).
# Each entry is (value_id, display_label). value_id MUST match the id used by
# the corresponding dropdown in Main.py.
# ---------------------------------------------------------------------------

LLM_PROVIDERS = [
    ("openai", "OpenAI"),
    ("aihubmix", "AIHubMix"),
    ("moonshot", "Moonshot"),
    ("azure", "Azure"),
    ("qwen", "Qwen"),
    ("deepseek", "DeepSeek"),
    ("modelscope", "ModelScope"),
    ("openrouter", "OpenRouter"),
    ("nvidia", "NVIDIA NIM"),
    ("gemini", "Gemini"),
    ("grok", "Grok"),
    ("groq", "Groq"),
    ("ollama", "Ollama"),
    ("g4f", "G4f"),
    ("oneapi", "OneAPI"),
    ("cloudflare", "Cloudflare"),
    ("ernie", "ERNIE"),
    ("minimax", "MiniMax"),
    ("mimo", "MiMo"),
    ("pollinations", "Pollinations"),
    ("litellm", "LiteLLM"),
]

VIDEO_SOURCES = [
    ("pexels", "Pexels"),
    ("pixabay", "Pixabay"),
    ("local", "Local file"),
    ("douyin", "TikTok"),
    ("bilibili", "Bilibili"),
    ("xiaohongshu", "Xiaohongshu"),
]

TTS_SERVERS = [
    ("no-voice", "No Voice"),
    ("azure-tts-v1", "Azure TTS V1"),
    ("azure-tts-v2", "Azure TTS V2"),
    ("siliconflow", "SiliconFlow TTS"),
    ("gemini-tts", "Google Gemini TTS"),
    ("mimo-tts", "Xiaomi MiMo TTS"),
]

VIDEO_ASPECTS = [
    ("9:16", "Portrait 9:16"),
    ("16:9", "Landscape 16:9"),
]

VIDEO_CONCAT_MODES = [
    ("sequential", "Sequential"),
    ("random", "Random"),
]

BGM_TYPES = [
    ("", "No Background Music"),
    ("random", "Random Background Music"),
    ("custom", "Custom Background Music"),
]

SUBTITLE_POSITIONS = [
    ("top", "Top"),
    ("center", "Center"),
    ("bottom", "Bottom"),
    ("custom", "Custom"),
]

# Registry the admin panel iterates over. ``main_id_index`` records where the id
# sits in Main.py's runtime tuple, so the same trim works for lists built as
# (label, value) and as (value, label) (TTS servers use the latter).
TRIMMABLE = [
    {
        "config_key": "enabled_llm_providers",
        "label_key": "Visibility LLM Providers",
        "catalog": LLM_PROVIDERS,
        "main_id_index": 1,
    },
    {
        "config_key": "enabled_video_sources",
        "label_key": "Visibility Video Sources",
        "catalog": VIDEO_SOURCES,
        "main_id_index": 1,
    },
    {
        "config_key": "enabled_tts_servers",
        "label_key": "Visibility TTS Servers",
        "catalog": TTS_SERVERS,
        "main_id_index": 0,
    },
    {
        "config_key": "enabled_video_aspects",
        "label_key": "Visibility Video Ratios",
        "catalog": VIDEO_ASPECTS,
        "main_id_index": 1,
    },
    {
        "config_key": "enabled_video_concat_modes",
        "label_key": "Visibility Concat Modes",
        "catalog": VIDEO_CONCAT_MODES,
        "main_id_index": 1,
    },
    {
        "config_key": "enabled_bgm_types",
        "label_key": "Visibility Background Music",
        "catalog": BGM_TYPES,
        "main_id_index": 1,
    },
    {
        "config_key": "enabled_subtitle_positions",
        "label_key": "Visibility Subtitle Positions",
        "catalog": SUBTITLE_POSITIONS,
        "main_id_index": 1,
    },
]

# Fields that can be hidden entirely. (field_id, i18n label key). field_id is
# referenced by ``is_hidden`` calls wrapping the matching control in Main.py.
HIDEABLE = [
    ("script_language", "Visibility Field Script Language"),
    ("advanced_script_settings", "Visibility Field Advanced Script Settings"),
    ("subsequent_themes", "Visibility Field Subsequent Themes"),
    ("video_concat_mode", "Visibility Field Video Concat Mode"),
    ("video_transition_mode", "Visibility Field Video Transition Mode"),
    ("video_aspect", "Visibility Field Video Ratio"),
    ("video_clip_duration", "Visibility Field Clip Duration"),
    ("video_count", "Visibility Field Video Count"),
    ("advanced_video_settings", "Visibility Field Advanced Video Settings"),
    ("play_voice", "Visibility Field Play Voice"),
    ("custom_audio_file", "Visibility Field Custom Audio File"),
    ("speech_volume", "Visibility Field Speech Volume"),
    ("speech_rate", "Visibility Field Speech Rate"),
    ("background_music", "Visibility Field Background Music"),
    ("subtitle_stroke", "Visibility Field Subtitle Stroke"),
    ("subtitle_background", "Visibility Field Subtitle Background"),
    ("rounded_subtitle_background", "Visibility Field Rounded Subtitle Background"),
    ("karaoke_highlight", "Visibility Field Karaoke Highlight"),
    ("youtube_upload", "Visibility Field YouTube Upload"),
    ("api_key_management", "Visibility Field API Key Management"),
]


# ---------------------------------------------------------------------------
# Pure helpers (no Streamlit). Read from config.ui.
# ---------------------------------------------------------------------------


def _ui_list(config_key):
    """Read a list-valued ui setting, tolerating a scalar or missing value."""
    val = config.ui.get(config_key, [])
    if isinstance(val, str):
        val = [val]
    return list(val) if val else []


def enabled_ids(config_key, all_ids):
    """Return the enabled subset of ``all_ids`` (order preserved).

    Missing/empty config, or a config that matches nothing in ``all_ids``,
    falls back to ``all_ids`` so a dropdown is never empty.
    """
    saved = set(_ui_list(config_key))
    if not saved:
        return list(all_ids)
    result = [i for i in all_ids if i in saved]
    return result or list(all_ids)


def filter_pairs(pairs, enabled, id_index=1):
    """Keep only ``pairs`` whose id is in ``enabled``; never returns empty."""
    enabled_set = set(enabled)
    result = [p for p in pairs if p[id_index] in enabled_set]
    return result if result else list(pairs)


def trim(config_key, pairs, id_index=1):
    """Convenience: filter ``pairs`` by the enabled set saved under ``config_key``."""
    all_ids = [p[id_index] for p in pairs]
    return filter_pairs(pairs, enabled_ids(config_key, all_ids), id_index)


def resolve_index(pairs, saved_value, default_value=None, id_index=1):
    """Index of ``saved_value`` in ``pairs``; falls back to ``default_value`` then 0.

    Guards the hardcoded ``index=`` / ``.index(...)`` lookups in Main.py against a
    saved value that was trimmed out of the dropdown.
    """
    ids = [p[id_index] for p in pairs]
    if saved_value in ids:
        return ids.index(saved_value)
    if default_value is not None and default_value in ids:
        return ids.index(default_value)
    return 0


def hidden_fields():
    return set(_ui_list("hidden_fields"))


def is_hidden(field_id):
    return field_id in hidden_fields()


# ---------------------------------------------------------------------------
# Admin panel (Streamlit).
# ---------------------------------------------------------------------------


def render_visibility_panel(tr):
    """Draw the 'Visibility Settings' expander. ``tr`` is Main.py's translator."""
    import streamlit as st

    with st.expander(tr("Visibility Settings"), expanded=False):
        st.caption(tr("Visibility Help"))

        st.write(tr("Visibility Trim Dropdowns"))
        for entry in TRIMMABLE:
            catalog = entry["catalog"]
            all_ids = [c[0] for c in catalog]
            label_map = {c[0]: c[1] for c in catalog}
            current = enabled_ids(entry["config_key"], all_ids)
            selected = st.multiselect(
                tr(entry["label_key"]),
                options=all_ids,
                default=current,
                # 用 default 参数绑定当前循环的 label_map，避免闭包捕获到最后一次迭代的值。
                format_func=lambda vid, _m=label_map: _m.get(vid, vid),
                key=f"vis_{entry['config_key']}",
            )
            config.ui[entry["config_key"]] = selected

        st.write(tr("Visibility Hide Fields"))
        field_ids = [f[0] for f in HIDEABLE]
        field_label_map = {f[0]: tr(f[1]) for f in HIDEABLE}
        hidden_default = [fid for fid in field_ids if fid in hidden_fields()]
        hidden_selected = st.multiselect(
            tr("Visibility Hidden Fields"),
            options=field_ids,
            default=hidden_default,
            format_func=lambda fid, _m=field_label_map: _m.get(fid, fid),
            key="vis_hidden_fields",
        )
        config.ui["hidden_fields"] = hidden_selected

        if st.button(tr("Visibility Save"), key="vis_save"):
            config.save_config()
            st.success(tr("Visibility Saved"))
