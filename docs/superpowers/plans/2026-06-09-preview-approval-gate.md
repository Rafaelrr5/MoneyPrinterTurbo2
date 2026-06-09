# 10-Second Preview Approval Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the Streamlit WebUI, render a ~10s preview of the real final video and require Approve / Regenerate / Cancel before the full render runs.

**Architecture:** Split the WebUI's single synchronous `tm.start()` call into two phases using the existing `stop_at="materials"` short-circuit. Phase 1 runs script→terms→audio→subtitle→download, then renders a 10s preview (real footage + narration + subtitles, capped by a 10s-trimmed audio clip). Streamlit `session_state` holds the resume context across reruns. Phase 2 (on Approve) calls a new `finalize_from_materials()` extracted from `start()` stages 6–8. The API/async path is untouched.

**Tech Stack:** Python 3.11, Streamlit, moviepy 2.x, loguru, stdlib `unittest`.

**Spec:** `docs/superpowers/specs/2026-06-09-preview-approval-gate-design.md`

**Run tests from the project root.** Single test: `uv run python -m unittest test.services.test_task.TestTaskService.test_name -v`

---

## File Structure

- `app/models/const.py` — add `PREVIEW_DURATION` constant.
- `app/services/video.py` — add `trim_audio()` helper (audio → first N seconds).
- `app/services/task.py` — add `generate_preview()`, extract `finalize_from_materials()` from `start()`, enrich the `stop_at=="materials"` return.
- `webui/Main.py` — two-phase `session_state` flow + "Preview before full render" checkbox.
- `webui/i18n/en.json`, `webui/i18n/zh.json` — new UI strings.
- `test/services/test_video.py` — new test file for `trim_audio`.
- `test/services/test_task.py` — tests for `generate_preview`, `finalize_from_materials`, enriched materials return.

---

## Task 1: Add `PREVIEW_DURATION` constant

**Files:**
- Modify: `app/models/const.py`

- [ ] **Step 1: Add the constant**

Append to `app/models/const.py`:

```python
# 预览片段时长（秒）：完整渲染前先产出这么长的样片供用户确认。
PREVIEW_DURATION = 10
```

- [ ] **Step 2: Verify it imports**

Run: `uv run python -c "from app.models import const; print(const.PREVIEW_DURATION)"`
Expected: `10`

- [ ] **Step 3: Commit**

```bash
git add app/models/const.py
git commit -m "feat: add PREVIEW_DURATION constant"
```

---

## Task 2: `trim_audio()` helper in `video.py`

`video.combine_videos` derives the output length from the audio file's duration, so a 10s preview is produced by feeding it a 10s-trimmed copy of the narration. moviepy 2.x uses `subclipped(start, end)` (see existing usage at `video.py:651`) and `close_clip` (defined at `video.py:418`).

**Files:**
- Create: `test/services/test_video.py`
- Modify: `app/services/video.py`

- [ ] **Step 1: Write the failing test**

Create `test/services/test_video.py`:

```python
import unittest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# add project root to python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import video


class TestTrimAudio(unittest.TestCase):
    @patch.object(video, "AudioFileClip")
    def test_trim_audio_caps_to_requested_duration(self, mock_audio_cls):
        src = mock_audio_cls.return_value
        src.duration = 30.0
        sub = src.subclipped.return_value

        out = video.trim_audio("/x/audio.mp3", "/x/audio-preview.mp3", 10)

        mock_audio_cls.assert_called_once_with("/x/audio.mp3")
        src.subclipped.assert_called_once_with(0, 10)
        sub.write_audiofile.assert_called_once()
        self.assertEqual(out, "/x/audio-preview.mp3")

    @patch.object(video, "AudioFileClip")
    def test_trim_audio_does_not_exceed_source_length(self, mock_audio_cls):
        src = mock_audio_cls.return_value
        src.duration = 4.0  # shorter than requested 10s

        video.trim_audio("/x/audio.mp3", "/x/audio-preview.mp3", 10)

        src.subclipped.assert_called_once_with(0, 4.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest test.services.test_video -v`
Expected: FAIL — `AttributeError: module 'app.services.video' has no attribute 'trim_audio'`

- [ ] **Step 3: Implement `trim_audio`**

Add to `app/services/video.py` (after the `close_clip` function, near line 418):

```python
def trim_audio(audio_file: str, output_file: str, duration: float) -> str:
    """将旁白音频裁剪为前 duration 秒，用于渲染短预览。
    combine_videos 依据音频时长决定成片长度，所以裁短音频即可得到短样片。"""
    audio_clip = AudioFileClip(audio_file)
    try:
        end = min(duration, audio_clip.duration)
        sub_clip = audio_clip.subclipped(0, end)
        sub_clip.write_audiofile(output_file, logger=None)
        close_clip(sub_clip)
    finally:
        close_clip(audio_clip)
    return output_file
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m unittest test.services.test_video -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/services/video.py test/services/test_video.py
git commit -m "feat: add trim_audio helper for short previews"
```

---

## Task 3: `generate_preview()` in `task.py`

**Files:**
- Modify: `app/services/task.py`
- Test: `test/services/test_task.py`

- [ ] **Step 1: Write the failing test**

Add to `test/services/test_task.py` inside `class TestTaskService` (imports `patch` already present; add `from unittest.mock import patch` already imported):

```python
    def test_generate_preview_renders_truncated_clip(self):
        """预览复用真实渲染路径：裁剪音频 -> 合成 -> 生成视频，返回 preview.mp4 路径。"""
        params = VideoParams(
            video_subject="x",
            video_aspect="9:16",
            video_concat_mode="random",
            video_transition_mode="None",
            video_clip_duration=3,
            n_threads=2,
        )
        with patch.object(tm.video, "trim_audio") as trim, \
             patch.object(tm.video, "combine_videos") as combine, \
             patch.object(tm.video, "generate_video") as gen:
            preview = tm.generate_preview(
                task_id="preview-task",
                params=params,
                downloaded_videos=["/v/1.mp4", "/v/2.mp4"],
                audio_file="/a/audio.mp3",
                subtitle_path="/a/subtitle.srt",
            )

        self.assertTrue(preview.endswith("preview.mp4"))
        trim.assert_called_once()
        # 预览音频是裁剪后的副本，时长用常量
        self.assertEqual(trim.call_args.args[2], tm.const.PREVIEW_DURATION)
        combine.assert_called_once()
        gen.assert_called_once()
        # generate_video 的输出文件就是返回值
        self.assertEqual(gen.call_args.kwargs["output_file"], preview)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest test.services.test_task.TestTaskService.test_generate_preview_renders_truncated_clip -v`
Expected: FAIL — `AttributeError: module 'app.services.task' has no attribute 'generate_preview'`

- [ ] **Step 3: Implement `generate_preview`**

Add to `app/services/task.py` after `generate_final_videos` (before `def start`):

```python
def generate_preview(
    task_id, params, downloaded_videos, audio_file, subtitle_path,
    duration=const.PREVIEW_DURATION,
):
    """渲染一个约 duration 秒的样片：与成片同一条渲染管线，仅按裁剪后的音频截短。
    每次调用都用 random 拼接，便于“重新生成预览”得到不同的镜头顺序。"""
    preview_audio = path.join(utils.task_dir(task_id), "audio-preview.mp3")
    video.trim_audio(audio_file, preview_audio, duration)

    combined_preview = path.join(utils.task_dir(task_id), "combined-preview.mp4")
    video.combine_videos(
        combined_video_path=combined_preview,
        video_paths=downloaded_videos,
        audio_file=preview_audio,
        video_aspect=params.video_aspect,
        video_concat_mode=VideoConcatMode.random,
        video_transition_mode=params.video_transition_mode,
        max_clip_duration=params.video_clip_duration,
        threads=params.n_threads,
    )

    preview_path = path.join(utils.task_dir(task_id), "preview.mp4")
    video.generate_video(
        video_path=combined_preview,
        audio_path=preview_audio,
        subtitle_path=subtitle_path,
        output_file=preview_path,
        params=params,
    )
    return preview_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m unittest test.services.test_task.TestTaskService.test_generate_preview_renders_truncated_clip -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/task.py test/services/test_task.py
git commit -m "feat: add generate_preview for 10s sample render"
```

---

## Task 4: Extract `finalize_from_materials()` from `start()`

This is a behavior-preserving refactor. Stages 6–8 of `start()` (currently `app/services/task.py:340-427`: concat-mode coercion, `generate_final_videos`, the failure check, success log, cross-post, YouTube upload, kwargs build, final `update_task`, and `return kwargs`) move into a reusable function. `start()` calls it.

**Files:**
- Modify: `app/services/task.py`
- Test: `test/services/test_task.py`

- [ ] **Step 1: Write the failing test**

Add to `test/services/test_task.py` inside `class TestTaskService`:

```python
    def test_finalize_from_materials_returns_videos(self):
        """收尾阶段（拼接渲染 + 跨平台发布）独立可调用，返回 videos 列表。"""
        params = VideoParams(
            video_subject="x",
            video_aspect="9:16",
            video_concat_mode="random",
            video_transition_mode="None",
            video_clip_duration=3,
            video_count=1,
            n_threads=2,
        )
        with patch.object(
            tm, "generate_final_videos",
            return_value=(["/t/final-1.mp4"], ["/t/combined-1.mp4"]),
        ) as final, \
             patch.object(tm.upload_post.upload_post_service, "is_configured", return_value=False), \
             patch.object(tm.youtube_upload.youtube_upload_service, "is_configured", return_value=False):
            result = tm.finalize_from_materials(
                task_id="finalize-task",
                params=params,
                downloaded_videos=["/v/1.mp4"],
                audio_file="/a/audio.mp3",
                subtitle_path="/a/subtitle.srt",
                video_script="script text",
                video_terms=["t1"],
                audio_duration=12,
            )

        final.assert_called_once()
        self.assertEqual(result["videos"], ["/t/final-1.mp4"])
        self.assertEqual(result["combined_videos"], ["/t/combined-1.mp4"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest test.services.test_task.TestTaskService.test_finalize_from_materials_returns_videos -v`
Expected: FAIL — `AttributeError: module 'app.services.task' has no attribute 'finalize_from_materials'`

- [ ] **Step 3: Implement `finalize_from_materials` and rewire `start()`**

Add this new function to `app/services/task.py` immediately after `generate_final_videos` (and after `generate_preview` from Task 3):

```python
def finalize_from_materials(
    task_id, params, downloaded_videos, audio_file, subtitle_path,
    video_script, video_terms, audio_duration,
):
    """成片收尾：拼接渲染 -> 可选跨平台发布 -> YouTube 上传，返回结果 kwargs。
    start() 全流程与 WebUI 预览通过后都复用这里，避免逻辑重复。"""
    # 仅完整视频生成流程才需要处理视频拼接模式；
    # 这样可以避免 /subtitle 和 /audio 这类请求访问不存在的字段。
    if type(params.video_concat_mode) is str:
        params.video_concat_mode = VideoConcatMode(params.video_concat_mode)

    # 6. Generate final videos
    final_video_paths, combined_video_paths = generate_final_videos(
        task_id, params, downloaded_videos, audio_file, subtitle_path
    )

    if not final_video_paths:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    logger.success(
        f"task {task_id} finished, generated {len(final_video_paths)} videos."
    )

    # 7. Cross-post to TikTok/Instagram (if enabled)
    cross_post_results = []
    if upload_post.upload_post_service.is_configured() and upload_post.upload_post_service.auto_upload:
        logger.info("\n\n## cross-posting videos to TikTok/Instagram")
        for video_path in final_video_paths:
            result = upload_post.cross_post_video(
                video_path=video_path,
                title=params.video_subject or "Check out this video! #shorts #viral"
            )
            cross_post_results.append(result)
            if result.get('success'):
                logger.info(f"✅ Cross-posted: {video_path}")
            else:
                logger.warning(f"⚠️ Failed to cross-post: {video_path} - {result.get('error', 'Unknown error')}")

    # 8. Upload to YouTube via the official Data API v3 (if enabled)
    youtube_results = []
    if (
        youtube_upload.youtube_upload_service.is_configured()
        and youtube_upload.youtube_upload_service.auto_upload
    ):
        logger.info("\n\n## uploading videos to YouTube")
        for index, video_path in enumerate(final_video_paths):
            # 复用现有社媒文案能力，按 YouTube Shorts 规格产出 title/描述/标签。
            meta = llm.generate_social_metadata(
                video_subject=params.video_subject,
                video_script=video_script,
                language=params.video_language,
                platform="youtube_shorts",
            )
            hashtags = meta.get("hashtags", [])
            caption = meta.get("caption", "")
            description = (
                f"{caption}\n\n{' '.join(hashtags)}".strip() if hashtags else caption
            )
            thumbnail_path = path.join(
                utils.task_dir(task_id), f"thumbnail-{index + 1}.jpg"
            )
            thumbnail = video.extract_thumbnail(video_path, thumbnail_path)
            result = youtube_upload.youtube_upload_service.upload_video(
                video_path=video_path,
                title=meta.get("title") or params.video_subject or "Untitled",
                description=description,
                tags=hashtags,
                thumbnail_path=thumbnail,
            )
            youtube_results.append(result)
            if result.get("success"):
                logger.success(f"✅ Uploaded to YouTube: {result.get('url')}")
            else:
                logger.warning(
                    f"⚠️ Failed to upload to YouTube: {video_path} - {result.get('error', 'Unknown error')}"
                )

    kwargs = {
        "videos": final_video_paths,
        "combined_videos": combined_video_paths,
        "script": video_script,
        "terms": video_terms,
        "audio_file": audio_file,
        "audio_duration": audio_duration,
        "subtitle_path": subtitle_path,
        "materials": downloaded_videos,
        "cross_post_results": cross_post_results if cross_post_results else None,
        "youtube_results": youtube_results if youtube_results else None,
    }
    sm.state.update_task(
        task_id, state=const.TASK_STATE_COMPLETE, progress=100, **kwargs
    )
    return kwargs
```

Then **replace** the tail of `start()` — everything from the `# 仅完整视频生成流程才需要处理视频拼接模式;` comment block through the final `return kwargs` (currently `app/services/task.py:340-427`) — with:

```python
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=50)

    # 6-8. Render + cross-post + upload (shared with WebUI preview-approval path)
    return finalize_from_materials(
        task_id, params, downloaded_videos, audio_file, subtitle_path,
        video_script, video_terms, audio_duration,
    )
```

Leave the `if stop_at == "materials":` block (lines 329-336) untouched for now — Task 5 edits it.

- [ ] **Step 4: Run the new test and the full suite**

Run: `uv run python -m unittest test.services.test_task.TestTaskService.test_finalize_from_materials_returns_videos -v`
Expected: PASS

Run (regression — refactor must not change behavior): `uv run python -m unittest test.services.test_task -v`
Expected: existing tests still PASS (note: `test_task_local_materials` performs a real render and may be slow / network-dependent — if it was passing before, it must still pass; if it was already environment-gated, leave it as-is).

- [ ] **Step 5: Commit**

```bash
git add app/services/task.py test/services/test_task.py
git commit -m "refactor: extract finalize_from_materials from task.start"
```

---

## Task 5: Enrich the `stop_at=="materials"` return

The WebUI resume needs `audio_file`, `subtitle_path`, `script`, `terms`, and `audio_duration` alongside `materials`. Adding keys is backward-compatible (existing callers read only `materials`).

**Files:**
- Modify: `app/services/task.py`
- Test: `test/services/test_task.py`

- [ ] **Step 1: Write the failing test**

Add to `test/services/test_task.py` inside `class TestTaskService`:

```python
    def test_stop_at_materials_returns_resume_context(self):
        """stop_at='materials' 需返回 WebUI 续跑所需的全部上下文。"""
        params = VideoParams(
            video_subject="x",
            video_source="pexels",
            video_aspect="9:16",
            video_concat_mode="random",
            video_transition_mode="None",
            video_clip_duration=3,
            video_count=1,
            n_threads=2,
        )
        with patch.object(tm, "generate_script", return_value="script text"), \
             patch.object(tm, "generate_terms", return_value=["t1", "t2"]), \
             patch.object(tm, "generate_audio", return_value=("/a/audio.mp3", 12, object())), \
             patch.object(tm, "generate_subtitle", return_value="/a/subtitle.srt"), \
             patch.object(tm, "get_video_materials", return_value=["/v/1.mp4"]), \
             patch.object(tm, "save_script_data"):
            res = tm.start("ctx-task", params, stop_at="materials")

        self.assertEqual(res["materials"], ["/v/1.mp4"])
        self.assertEqual(res["audio_file"], "/a/audio.mp3")
        self.assertEqual(res["subtitle_path"], "/a/subtitle.srt")
        self.assertEqual(res["script"], "script text")
        self.assertEqual(res["terms"], ["t1", "t2"])
        self.assertEqual(res["audio_duration"], 12)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest test.services.test_task.TestTaskService.test_stop_at_materials_returns_resume_context -v`
Expected: FAIL — `KeyError: 'audio_file'` (the current return only has `materials`).

- [ ] **Step 3: Enrich the return dict**

In `app/services/task.py`, replace the `if stop_at == "materials":` block (currently lines 329-336):

```python
    if stop_at == "materials":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            materials=downloaded_videos,
        )
        return {"materials": downloaded_videos}
```

with:

```python
    if stop_at == "materials":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            materials=downloaded_videos,
        )
        # 额外返回续跑所需上下文，供 WebUI 预览通过后直接收尾，无需重读磁盘。
        return {
            "materials": downloaded_videos,
            "audio_file": audio_file,
            "subtitle_path": subtitle_path,
            "script": video_script,
            "terms": video_terms,
            "audio_duration": audio_duration,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m unittest test.services.test_task.TestTaskService.test_stop_at_materials_returns_resume_context -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/task.py test/services/test_task.py
git commit -m "feat: return resume context from stop_at=materials"
```

---

## Task 6: WebUI two-phase preview-approval flow

No automated test (Streamlit). The `tm` module already exposes `tm.sm.state`, `tm.const`, `tm.generate_preview`, and `tm.finalize_from_materials`, so no new imports are needed.

**Files:**
- Modify: `webui/Main.py` (the Generate-Video block, currently lines 1575-1681)

- [ ] **Step 1: Replace the Generate-Video block**

In `webui/Main.py`, replace the entire block from `start_button = st.button(...)` (line 1575) through the final `config.save_config()` (line 1681) with the following. (The validation and uploaded-audio/materials persistence logic is preserved verbatim — only the orchestration around it changes.)

```python
# --- preview-approval gate state (survives Streamlit reruns within a session) ---
if "preview_stage" not in st.session_state:
    st.session_state["preview_stage"] = "idle"
if "preview_ctx" not in st.session_state:
    st.session_state["preview_ctx"] = None


def _attach_log_sink():
    log_container = st.empty()
    log_records = []

    def log_received(msg):
        if config.ui["hide_log"]:
            return
        with log_container:
            log_records.append(msg)
            st.code("\n".join(log_records))

    logger.add(log_received)


def _render_final_result(result, task_id):
    if not result or "videos" not in result:
        st.error(tr("Video Generation Failed"))
        logger.error(tr("Video Generation Failed"))
        scroll_to_bottom()
        st.stop()
    video_files = result.get("videos", [])
    st.success(tr("Video Generation Completed"))
    try:
        if video_files:
            player_cols = st.columns(len(video_files) * 2 + 1)
            for i, url in enumerate(video_files):
                player_cols[i * 2 + 1].video(url)
    except Exception:
        pass
    open_task_folder(task_id)
    logger.info(tr("Video Generation Completed"))
    scroll_to_bottom()


preview_enabled = st.checkbox(
    tr("Preview Before Render"),
    value=config.ui.get("preview_before_render", True),
)
config.ui["preview_before_render"] = preview_enabled

start_button = st.button(tr("Generate Video"), use_container_width=True, type="primary")

if start_button and st.session_state["preview_stage"] == "idle":
    config.save_config()
    task_id = str(uuid4())
    if not params.video_subject and not params.video_script:
        st.error(tr("Video Script and Subject Cannot Both Be Empty"))
        scroll_to_bottom()
        st.stop()

    if params.video_source not in ["pexels", "pixabay", "local"]:
        st.error(tr("Please Select a Valid Video Source"))
        scroll_to_bottom()
        st.stop()

    if params.video_source == "pexels" and not config.app.get("pexels_api_keys", ""):
        st.error(tr("Please Enter the Pexels API Key"))
        scroll_to_bottom()
        st.stop()

    if params.video_source == "pixabay" and not config.app.get("pixabay_api_keys", ""):
        st.error(tr("Please Enter the Pixabay API Key"))
        scroll_to_bottom()
        st.stop()

    if uploaded_audio_file:
        task_dir = utils.task_dir(task_id)
        # 上传文件名来自浏览器，不能直接拼到磁盘路径里；这里只保留扩展名，
        # 并使用固定文件名保存到当前任务目录，避免路径穿越或特殊字符问题。
        _, audio_ext = os.path.splitext(os.path.basename(uploaded_audio_file.name))
        audio_ext = audio_ext.lower() or ".mp3"
        custom_audio_path = os.path.join(task_dir, f"custom-audio{audio_ext}")
        with open(custom_audio_path, "wb") as f:
            f.write(uploaded_audio_file.getbuffer())
        params.custom_audio_file = custom_audio_path

    if uploaded_files:
        local_videos_dir = utils.storage_dir("local_videos", create=True)
        # 每次重新上传时都以本次选择的素材为准，避免旧素材不断重复追加。
        params.video_materials = []
        persisted_local_materials = []
        for file in uploaded_files:
            file_path = os.path.join(local_videos_dir, f"{file.file_id}_{file.name}")
            with open(file_path, "wb") as f:
                f.write(file.getbuffer())
                m = MaterialInfo()
                m.provider = "local"
                m.url = file_path
                params.video_materials.append(m)
                persisted_local_materials.append(
                    {
                        "provider": m.provider,
                        "url": m.url,
                        "duration": m.duration,
                    }
                )
        # 将已上传并保存到本地的视频素材写入会话，供后续只改文案时直接复用。
        st.session_state["local_video_materials"] = persisted_local_materials
    elif params.video_source == "local" and st.session_state["local_video_materials"]:
        # 当用户没有重新上传文件时，复用最近一次已经保存到磁盘的本地素材列表。
        params.video_materials = []
        for material in st.session_state["local_video_materials"]:
            m = MaterialInfo()
            m.provider = material.get("provider", "local")
            m.url = material.get("url", "")
            m.duration = material.get("duration", 0)
            if m.url:
                params.video_materials.append(m)

    _attach_log_sink()
    st.toast(tr("Generating Video"))
    logger.info(tr("Start Generating Video"))
    logger.info(utils.to_json(params))
    scroll_to_bottom()

    if not preview_enabled:
        # 预览关闭：保持原有一次性全流程行为。
        result = tm.start(task_id=task_id, params=params)
        _render_final_result(result, task_id)
    else:
        # Phase 1: 跑到素材下载完成，再渲染 10 秒样片，暂停等待确认。
        result = tm.start(task_id=task_id, params=params, stop_at="materials")
        if not result or "materials" not in result:
            st.error(tr("Video Generation Failed"))
            logger.error(tr("Video Generation Failed"))
            scroll_to_bottom()
            st.stop()
        try:
            preview_path = tm.generate_preview(
                task_id=task_id,
                params=params,
                downloaded_videos=result["materials"],
                audio_file=result["audio_file"],
                subtitle_path=result["subtitle_path"],
            )
        except Exception as e:
            st.error(f'{tr("Video Generation Failed")}: {e}')
            logger.error(f"failed to generate preview: {e}")
            scroll_to_bottom()
            st.stop()
        st.session_state["preview_ctx"] = {
            "task_id": task_id,
            "params": params,
            "materials": result["materials"],
            "audio_file": result["audio_file"],
            "subtitle_path": result["subtitle_path"],
            "script": result.get("script", ""),
            "terms": result.get("terms", ""),
            "audio_duration": result.get("audio_duration", 0),
            "preview_path": preview_path,
        }
        st.session_state["preview_stage"] = "awaiting_approval"
        st.rerun()

if st.session_state["preview_stage"] == "awaiting_approval":
    ctx = st.session_state["preview_ctx"]
    st.info(tr("Preview Ready"))
    st.video(ctx["preview_path"])
    col_a, col_r, col_c = st.columns(3)
    approve = col_a.button(
        tr("Approve Preview"), use_container_width=True, type="primary"
    )
    regenerate = col_r.button(tr("Regenerate Preview"), use_container_width=True)
    cancel = col_c.button(tr("Cancel"), use_container_width=True)

    if approve:
        _attach_log_sink()
        st.toast(tr("Generating Video"))
        scroll_to_bottom()
        result = tm.finalize_from_materials(
            task_id=ctx["task_id"],
            params=ctx["params"],
            downloaded_videos=ctx["materials"],
            audio_file=ctx["audio_file"],
            subtitle_path=ctx["subtitle_path"],
            video_script=ctx["script"],
            video_terms=ctx["terms"],
            audio_duration=ctx["audio_duration"],
        )
        st.session_state["preview_stage"] = "idle"
        st.session_state["preview_ctx"] = None
        _render_final_result(result, ctx["task_id"])

    elif regenerate:
        _attach_log_sink()
        st.toast(tr("Generating Video"))
        try:
            ctx["preview_path"] = tm.generate_preview(
                task_id=ctx["task_id"],
                params=ctx["params"],
                downloaded_videos=ctx["materials"],
                audio_file=ctx["audio_file"],
                subtitle_path=ctx["subtitle_path"],
            )
            st.session_state["preview_ctx"] = ctx
        except Exception as e:
            st.error(f'{tr("Video Generation Failed")}: {e}')
            logger.error(f"failed to regenerate preview: {e}")
        st.rerun()

    elif cancel:
        tm.sm.state.update_task(ctx["task_id"], state=tm.const.TASK_STATE_FAILED)
        st.session_state["preview_stage"] = "idle"
        st.session_state["preview_ctx"] = None
        st.warning(tr("Task Cancelled"))
        st.stop()

config.save_config()
```

- [ ] **Step 2: Syntax-check the file**

Run: `uv run python -c "import ast; ast.parse(open('webui/Main.py', encoding='utf-8').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add webui/Main.py
git commit -m "feat: add 10s preview approval gate to WebUI"
```

---

## Task 7: Add i18n strings

`tr(key)` returns the key itself when a locale lacks it (`webui/Main.py:223`), so the other 5 locales fall back to the English text automatically; only `en.json` and `zh.json` need entries.

**Files:**
- Modify: `webui/i18n/en.json`
- Modify: `webui/i18n/zh.json`

- [ ] **Step 1: Add keys to `en.json`**

Insert these key/value pairs into the `"Translation"` object in `webui/i18n/en.json` (any position inside the object; mind the trailing comma on the line before):

```json
    "Preview Before Render": "Preview before full render",
    "Preview Ready": "Preview ready — review the 10-second clip below, then approve or regenerate",
    "Approve Preview": "Approve & Render Full Video",
    "Regenerate Preview": "Regenerate Preview",
    "Cancel": "Cancel",
    "Task Cancelled": "Task cancelled",
```

- [ ] **Step 2: Add keys to `zh.json`**

Insert into the `"Translation"` object in `webui/i18n/zh.json`:

```json
    "Preview Before Render": "渲染前预览",
    "Preview Ready": "预览已生成 — 请查看下面的 10 秒片段，然后通过或重新生成",
    "Approve Preview": "通过并渲染完整视频",
    "Regenerate Preview": "重新生成预览",
    "Cancel": "取消",
    "Task Cancelled": "任务已取消",
```

- [ ] **Step 3: Validate both JSON files parse**

Run: `uv run python -c "import json; json.load(open('webui/i18n/en.json', encoding='utf-8')); json.load(open('webui/i18n/zh.json', encoding='utf-8')); print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add webui/i18n/en.json webui/i18n/zh.json
git commit -m "i18n: add preview-approval strings (en, zh)"
```

---

## Task 8: Document the config key + full regression

**Files:**
- Modify: `config.example.toml`

- [ ] **Step 1: Document the UI toggle**

In `config.example.toml`, locate the `[ui]` section and add (matching the surrounding comment style):

```toml
# WebUI: render a ~10s preview and require approval before the full render (default true)
preview_before_render = true
```

If there is no `[ui]` section, add one near the other WebUI settings.

- [ ] **Step 2: Run the full test suite**

Run: `uv run python -m unittest discover test`
Expected: all tests PASS (or the same set that passed before this work — no new failures introduced).

- [ ] **Step 3: Manual WebUI verification**

Start the WebUI (`webui.bat` or `uv run streamlit run ./webui/Main.py`) and confirm:
- With "Preview before full render" **checked** (default): clicking Generate produces a ~10s `preview.mp4` that plays in the page, with Approve / Regenerate / Cancel buttons.
- **Approve** → full videos render and play as before; `final-1.mp4` exists in the task dir.
- **Regenerate Preview** → a new preview renders (different clip ordering) without re-downloading footage or re-running TTS (check logs — no "downloading videos" / no "generating audio" lines).
- **Cancel** → returns to the idle form; task marked failed.
- With the checkbox **unchecked** → behaves exactly as before (no preview, straight to full render).

- [ ] **Step 4: Commit**

```bash
git add config.example.toml
git commit -m "docs: document preview_before_render UI config key"
```

---

## Self-Review Notes

- **Spec coverage:** preview content (Task 2+3), two-phase flow (Task 6), Approve/Regenerate/Cancel (Task 6), default-on toggle (Task 6+8), single preview for `video_count>1` (Task 3 renders one `preview.mp4`; Approve renders N via `finalize_from_materials`), enriched materials return (Task 5), behavior-preserving refactor (Task 4), i18n (Task 7), error handling (Task 6 try/except + falsy-result guards), testing (Tasks 2-5 + Task 8 manual). All spec sections mapped.
- **Type consistency:** `generate_preview` and `finalize_from_materials` signatures are identical between their definition tasks (3, 4) and their call sites (Task 6). `result` keys from the enriched materials return (Task 5: `audio_file`, `subtitle_path`, `script`, `terms`, `audio_duration`) match the keys read in Task 6's phase-1 block.
- **No placeholders:** every code step contains complete code; every run step has an exact command + expected output.
