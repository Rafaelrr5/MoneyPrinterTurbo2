# 10-Second Preview Approval Gate (WebUI)

**Date:** 2026-06-09
**Status:** Approved design — ready for implementation plan
**Scope:** Streamlit WebUI only (`webui/Main.py`). The FastAPI/async path is unchanged.

## Goal

Before rendering the full video, the WebUI renders a ~10-second preview that
represents the real final video (real footage + narration + subtitles + effects,
truncated). The user must **Approve** it before the full render runs. The user
can also **Regenerate** the preview (new footage ordering, same script/narration)
or **Cancel** the task.

## Non-goals

- No approval gate on the FastAPI path (`app/controllers/`, `TaskManager`). Async
  tasks keep current fire-and-forget behavior.
- No separate "preview-quality" / low-res render path. The preview reuses the
  exact final render code, capped to the preview duration.
- No pause/resume persisted in the state store. The gate lives entirely in
  Streamlit `session_state`, which survives reruns within a session.

## Key decisions

1. **Faithful preview via audio truncation.** `video.combine_videos` sizes the
   video to the **audio file's duration**. So the preview is produced by feeding
   a 10s-trimmed copy of `audio.mp3` to the same `combine_videos` + `generate_video`
   path. Subtitles beyond 10s simply don't render. Styling/effects are identical
   to the final video.
2. **Two-phase synchronous flow.** Split the single `tm.start()` WebUI call into:
   phase 1 = run up to `stop_at="materials"` then render preview; phase 2 (on
   Approve) = resume from materials and run render + cross-post. No new state
   machine — Streamlit reruns the script and `session_state` carries context.
3. **Single preview for `video_count > 1`.** The preview is one 10s clip
   representing style. Approving renders all N variants.
4. **Default-on toggle.** A WebUI checkbox "Preview before full render"
   (default ON) lets a run skip the gate and behave exactly as today.
5. **Reject offers both paths.** Per user: Regenerate (cheap loop, keeps
   script+audio) *and* Cancel (abort) are both available.

## Architecture

### `app/services/task.py`

- **Extract** stages 6–8 of `start()` (final render, cross-post, YouTube upload)
  into a reusable function:

  ```
  finalize_from_materials(task_id, params, downloaded_videos, audio_file,
                          subtitle_path, video_script, video_terms,
                          audio_duration) -> kwargs
  ```

  `start()` calls this in place of the inlined stages 6–8. Behavior of the full
  run / API path is unchanged (refactor is behavior-preserving).

- **Enrich** the `stop_at == "materials"` return dict. Today it returns
  `{"materials": downloaded_videos}`. Add (additively — existing callers ignore
  extra keys): `audio_file`, `subtitle_path`, `script`, `terms`, `audio_duration`.
  This lets the WebUI resume without re-reading disk.

- **New** preview renderer:

  ```
  generate_preview(task_id, params, downloaded_videos, audio_file,
                   subtitle_path, duration=PREVIEW_DURATION) -> preview_path
  ```

  Steps: trim `audio_file` → `audio-preview.mp3` (0..duration) via the video.py
  helper; `combine_videos(... combined-preview.mp4, audio=audio-preview.mp3,
  video_concat_mode=random ...)`; `generate_video(combined-preview.mp4,
  audio-preview.mp3, subtitle_path, output=preview.mp4, params)`; return
  `preview.mp4` path. A `random` concat mode lets Regenerate produce a different
  clip ordering on each call.

- `PREVIEW_DURATION = 10` constant (in `task.py` or `app/models/const.py`).

### `app/services/video.py`

- Small helper to trim an audio file to the first N seconds (moviepy
  `AudioFileClip` subclip → write `audio-preview.mp3`). Reuses existing
  `close_clip` cleanup convention. Honors the project's ffmpeg env-var setup.

### `webui/Main.py`

Replace the single `tm.start(...)` block (currently ~line 1660) with a
`session_state`-driven flow:

- `st.session_state["preview_stage"]` ∈ {`idle`, `awaiting_approval`}.
  Initialize to `idle`.
- Add checkbox **"Preview before full render"** (default ON) near the Generate
  button; persisted in `config.ui` like other UI prefs.

**Generate clicked:**
- If checkbox OFF → current behavior: `tm.start(task_id, params)` full run, render
  finals. (Unchanged path.)
- If checkbox ON and `preview_stage == idle`:
  1. Run all existing pre-flight validations (subject/script, source, API keys,
     uploaded audio/materials persistence) — unchanged.
  2. `result = tm.start(task_id, params, stop_at="materials")`. On falsy result →
     show `Video Generation Failed`, stay `idle`.
  3. `preview_path = task.generate_preview(...)` using the enriched result. Wrap
     in try/except → on error show the error, clear ctx, stay `idle`.
  4. Store `session_state["preview_ctx"]` = `{task_id, params (snapshot),
     materials, audio_file, subtitle_path, script, terms, audio_duration,
     preview_path}`.
  5. `preview_stage = awaiting_approval`; `st.rerun()`.

**`preview_stage == awaiting_approval`:**
- `st.video(preview_ctx["preview_path"])` + three buttons:
  - **Approve** → `task.finalize_from_materials(**preview_ctx fields)`; on success
    render final videos (existing player code) and `open_task_folder`; clear ctx;
    `preview_stage = idle`.
  - **Regenerate Preview** → `task.generate_preview(...)` again (reshuffled clips,
    no re-download / no re-TTS); update `preview_ctx["preview_path"]`; `st.rerun()`.
  - **Cancel** → `sm.state.update_task(task_id, state=TASK_STATE_FAILED)`; clear
    ctx; `preview_stage = idle`; `st.stop()`.

Params are snapshotted into `preview_ctx` at phase 1 so editing widgets while
`awaiting_approval` does not desync the resume.

### i18n (`webui/i18n/`)

Add keys to at least `en.json` and `zh.json` (mirror to other locale files with
English fallback): `Preview before full render`, `Approve`,
`Regenerate Preview`, `Cancel`, `Preview ready, please review`.

## Data flow

```
[Generate, preview ON, stage=idle]
  tm.start(task_id, params, stop_at="materials")
    -> script.json, audio.mp3, subtitle.srt, downloaded clips
    -> {materials, audio_file, subtitle_path, script, terms, audio_duration}
  generate_preview(...) -> audio-preview.mp3 -> combined-preview.mp4 -> preview.mp4
  session_state.preview_ctx = {...}; stage = awaiting_approval; rerun

[stage=awaiting_approval]  st.video(preview.mp4) + buttons
  Approve     -> finalize_from_materials(ctx) -> final-N.mp4 (+cross-post/YouTube) -> render; clear
  Regenerate  -> generate_preview(ctx, reshuffle) -> new preview.mp4 -> rerun
  Cancel      -> state=FAILED; clear; st.stop()
```

## Error handling

- Phase-1 failure (`start` returns falsy): existing `Video Generation Failed`
  message; remain `idle`.
- `generate_preview` raises: catch, surface error, clear ctx, return to `idle` —
  never strand the user in `awaiting_approval` with no preview.
- Approve-time finalize failure: existing failed-state path; ctx cleared.
- Rerun safety: Generate triggers phase 1 only when `preview_stage == idle`, so
  unrelated widget interactions during `awaiting_approval` don't restart the
  pipeline.

## Testing

Stdlib `unittest`, in `test/services/test_task.py`:

- `generate_preview`: mock the video.py audio-trim helper, `combine_videos`, and
  `generate_video`; assert the trimmed-audio path and `preview.mp4` output path
  flow through and the function returns the preview path.
- `finalize_from_materials`: mock `generate_final_videos`; upload/YouTube services
  unconfigured; assert stages 6–8 run and the returned dict contains `videos`.
- Regression: existing `start()` tests pass unchanged after the stage-6–8
  extraction (behavior-preserving refactor).

WebUI (Streamlit) is not unit-tested. **Manual verification:** run the WebUI,
generate with preview ON, confirm a ~10s `preview.mp4` plays, exercise
Approve / Regenerate / Cancel, and confirm preview OFF behaves exactly as today.

## Files touched

- `app/services/task.py` — refactor + `generate_preview` + enriched materials return.
- `app/services/video.py` — audio-trim helper.
- `webui/Main.py` — two-phase session_state flow + checkbox.
- `webui/i18n/en.json`, `webui/i18n/zh.json` (+ other locales) — new strings.
- `app/models/const.py` — `PREVIEW_DURATION` (if placed here).
- `test/services/test_task.py` — new tests.
- `config.example.toml` — document the `ui` preview-toggle key if persisted there.
