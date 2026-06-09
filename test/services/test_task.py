import unittest
import os
import sys
from pathlib import Path
from unittest.mock import patch

# add project root to python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import task as tm
from app.models.schema import MaterialInfo, VideoParams

resources_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")

class TestTaskService(unittest.TestCase):
    def setUp(self):
        pass
    
    def tearDown(self):
        pass

    def test_generate_script_forwards_advanced_prompt_options(self):
        """
        任务生成入口和 WebUI/API 共用 VideoParams。这里验证自动生成文案时，
        高级提示词参数会继续传到 LLM 服务层，避免只在 /scripts 接口生效。
        """
        params = VideoParams(
            video_subject="咖啡",
            video_script="",
            video_language="zh-CN",
            paragraph_number=2,
            video_script_prompt="语气轻松",
            custom_system_prompt="Only write short narration.",
        )

        with patch.object(tm.llm, "generate_script", return_value="生成的文案") as generate:
            result = tm.generate_script("task-id", params)

        self.assertEqual(result, "生成的文案")
        generate.assert_called_once_with(
            video_subject="咖啡",
            language="zh-CN",
            paragraph_number=2,
            video_script_prompt="语气轻松",
            custom_system_prompt="Only write short narration.",
        )
    
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

    def test_task_local_materials(self):
        task_id = "00000000-0000-0000-0000-000000000000"
        video_materials=[]
        for i in range(1, 4):
            video_materials.append(MaterialInfo(
                provider="local",
                url=os.path.join(resources_dir, f"{i}.png"),
                duration=0
            ))

        params = VideoParams(
            video_subject="金钱的作用",
            video_script="金钱不仅是交换媒介，更是社会资源的分配工具。它能满足基本生存需求，如食物和住房，也能提供教育、医疗等提升生活品质的机会。拥有足够的金钱意味着更多选择权，比如职业自由或创业可能。但金钱的作用也有边界，它无法直接购买幸福、健康或真诚的人际关系。过度追逐财富可能导致价值观扭曲，忽视精神层面的需求。理想的状态是理性看待金钱，将其作为实现目标的工具而非终极目的。",
            video_terms="money importance, wealth and society, financial freedom, money and happiness, role of money",
            video_aspect="9:16",
            video_concat_mode="random",
            video_transition_mode="None",
            video_clip_duration=3,
            video_count=1,
            video_source="local",
            video_materials=video_materials,
            video_language="",
            voice_name="zh-CN-XiaoxiaoNeural-Female",
            voice_volume=1.0,
            voice_rate=1.0,
            bgm_type="random",
            bgm_file="",
            bgm_volume=0.2,
            subtitle_enabled=True,
            subtitle_position="bottom",
            custom_position=70.0,
            font_name="MicrosoftYaHeiBold.ttc",
            text_fore_color="#FFFFFF",
            text_background_color=True,
            font_size=60,
            stroke_color="#000000",
            stroke_width=1.5,
            n_threads=2,
            paragraph_number=1
        )
        result = tm.start(task_id=task_id, params=params)
        print(result)
    

if __name__ == "__main__":
    unittest.main()
