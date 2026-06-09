# Subsequent Themes — Design

**Date:** 2026-06-09
**Status:** Approved (pre-implementation)

## Summary

Add a new AI-generated capability, **Subsequent Themes**: given the current video
subject and (optionally) its script, the LLM proposes related topic ideas for the
*next* videos. Each suggestion is a `theme` plus a one-line `hook` (the angle/reason
to make it). Surfaces in both the WebUI (new section in the left panel) and the HTTP
API (`POST /subsequent-themes`), mirroring the existing `generate_terms` /
`generate_social_metadata` patterns.

This is a suggestion-only feature. It does not feed the render pipeline, is not
persisted to the task directory, and reuses the configured LLM provider only.

## Goals

- Help a creator plan a content series by surfacing 5 (configurable 1–10) related,
  *distinct* follow-up themes after generating a video.
- Reuse existing LLM dispatch (`_generate_response`) and the established prompt /
  parse / retry conventions.
- Full parity surface: WebUI section + API endpoint.

## Non-goals (YAGNI)

- No persistence of themes to `storage/tasks/{id}/` and no new pipeline stage.
- No heuristic fallback content. On repeated LLM failure, return an empty list —
  fabricated topic+hook suggestions would mislead the user.
- No auto-chaining (clicking a theme to start a new video). Display only.

## Output contract

`generate_subsequent_themes(...)` returns `List[dict]`, each item:

```json
{ "theme": "string", "hook": "string" }
```

- `theme`: a short follow-up video topic, distinct from the current subject.
- `hook`: a one-line angle/reason explaining why it's a good next video.
- On failure (all retries exhausted, or LLM returns `Error: ...`): returns `[]`.

## Components

### Service — `app/services/llm.py`

Constants:

- `DEFAULT_SUBSEQUENT_THEME_COUNT = 5`
- `MIN_SUBSEQUENT_THEME_COUNT = 1`, `MAX_SUBSEQUENT_THEME_COUNT = 10`
- `MAX_SUBSEQUENT_THEME_TEXT = 120` (clamp per-field length)
- Reuse `MAX_SOCIAL_SUBJECT_LENGTH` (500) and `MAX_SOCIAL_SCRIPT_LENGTH` (8000) for
  input limits, and `_social_language_instruction` for language handling.

Functions:

- `_normalize_theme_count(amount) -> int` — clamp to `[MIN, MAX]`, default on bad input.
- `build_subsequent_themes_prompt(video_subject, video_script, amount, language) -> str`
  — role = content strategist; instruct: return ONLY a minified JSON array of exactly
  `amount` objects, keys `theme` and `hook`; each theme must be related to but
  **distinct** from the current subject; obey the language instruction; no markdown,
  no code fences, no commentary. Includes subject + script context blocks.
- `_parse_subsequent_themes(response, amount) -> List[dict]` — `json.loads`; on failure
  fall back to regex `\[.*\]` (DOTALL) to extract the first JSON array (handles fenced /
  wrapped output, same tactic as `_parse_social_metadata`). Keep only items that are
  dicts with a non-empty `theme`; clamp `theme`/`hook` via `_clamp_text(..., MAX_SUBSEQUENT_THEME_TEXT)`;
  cap to `amount`.
- `generate_subsequent_themes(video_subject, video_script="", amount=DEFAULT, language="auto") -> List[dict]`
  — limit inputs, build prompt, retry loop (`_max_retries`) over `_generate_response`;
  break out and return `[]` if a response contains the `Error: ` sentinel; return parsed
  list on first success; return `[]` after exhausting retries. Log with `loguru` like
  the sibling generators.

### Schema — `app/models/schema.py`

```python
class VideoSubsequentThemesParams:
    video_subject: Optional[str] = Field(default="A day in Shanghai", max_length=500)
    video_script: Optional[str] = Field(default="", max_length=8000)
    amount: Optional[int] = Field(default=5, ge=1, le=10)
    language: Optional[str] = Field(default="auto", max_length=64)

class VideoSubsequentThemesRequest(VideoSubsequentThemesParams, BaseModel): pass

class VideoSubsequentThemesResponse(BaseResponse):
    # json_schema_extra example: data = {"themes": [{"theme": "...", "hook": "..."}]}
```

### API — `app/controllers/v1/llm.py`

`POST /subsequent-themes` (summary "Generate related themes for follow-up videos"):

```python
@router.post("/subsequent-themes", response_model=VideoSubsequentThemesResponse, ...)
def generate_video_subsequent_themes(request: Request, body: VideoSubsequentThemesRequest):
    themes = llm.generate_subsequent_themes(
        video_subject=body.video_subject,
        video_script=body.video_script,
        amount=body.amount,
        language=body.language,
    )
    return utils.get_response(200, {"themes": themes})
```

Import the new request/response models alongside the existing ones.

### WebUI — `webui/Main.py`

New section inside `left_panel`, after the Video Keywords text area (~`:791`):

- Init `st.session_state["subsequent_themes"] = []` near the other session defaults.
- Button `tr("Generate Subsequent Themes")` (key `auto_generate_subsequent_themes`):
  requires `params.video_subject` (else `st.error(tr("Please Enter the Video Subject"))`);
  calls `llm.generate_subsequent_themes(params.video_subject, params.video_script, language=params.video_language)`
  inside a spinner; on empty result show an info/error; else store in session state.
- Render: for each item, `st.markdown(f"**{theme}** — {hook}")` (read-only). Themes are
  suggestions, not edited or fed into `params`.

### i18n

Add keys to `webui/i18n/en.json` and `webui/i18n/zh.json`:
`"Subsequent Themes"`, `"Generate Subsequent Themes"`, `"Generating Subsequent Themes"`,
`"No Subsequent Themes Generated"`. Other locales fall back to the key via `tr()`.

## Testing — `test/services/test_llm.py`

Unit tests (stdlib `unittest`, monkeypatch `_generate_response`):

- `build_subsequent_themes_prompt` includes subject, script, and requested count.
- Parse valid minified JSON array → list of `{theme, hook}`.
- Parse fenced / prose-wrapped JSON array via regex fallback.
- Malformed / non-array response → `[]`.
- Count clamping: request > MAX clamps; parsed list capped to `amount`.
- `Error: ...` response and exhausted retries → `[]`.

## Error handling

- Bad/oversized inputs are clamped before the prompt (no exceptions to caller).
- Parse failures retried up to `_max_retries`; terminal failure → `[]`.
- API always returns 200 with `{"themes": [...]}` (possibly empty).
- WebUI surfaces an info message when the list is empty.
