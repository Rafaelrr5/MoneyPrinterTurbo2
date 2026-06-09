import unittest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# add project root to python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import youtube_upload


def make_service(**overrides):
    """
    构造一个“已配置好”的 service 实例，绕过 config.toml，直接覆盖属性，
    让每个用例聚焦于上传逻辑本身。
    """
    svc = youtube_upload.YouTubeUploadService()
    svc.enabled = True
    svc.client_id = "cid"
    svc.client_secret = "csecret"
    svc.refresh_token = "rtoken"
    svc.privacy_status = "public"
    svc.category_id = "22"
    svc.default_tags = []
    svc.made_for_kids = False
    svc.auto_upload = False
    for key, value in overrides.items():
        setattr(svc, key, value)
    return svc


class TestYouTubeUploadService(unittest.TestCase):
    def test_is_configured(self):
        self.assertTrue(make_service().is_configured())
        self.assertFalse(make_service(refresh_token="").is_configured())
        self.assertFalse(make_service(enabled=False).is_configured())
        self.assertFalse(make_service(client_id="").is_configured())

    def test_normalize_tags_merges_and_strips_hash(self):
        svc = make_service(default_tags=["#default", "shared"])
        tags = svc._normalize_tags(["#one", "two", "two", "shared"])
        # 去 '#'、去重，并把默认标签追加在后面。
        self.assertEqual(tags, ["one", "two", "shared", "default"])

    def test_upload_not_configured(self):
        svc = make_service(refresh_token="")
        result = svc.upload_video(__file__, title="hi")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "YouTube upload not configured")

    def test_upload_missing_file_returns_error(self):
        result = make_service().upload_video("/no/such/file.mp4", title="hi")
        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"])

    def test_upload_builds_request_and_sets_thumbnail(self):
        svc = make_service(default_tags=["brand"])

        # 假 request 驱动 resumable 循环：先返回进度，再返回最终响应。
        fake_request = MagicMock()
        fake_request.next_chunk.side_effect = [
            (MagicMock(progress=lambda: 0.5), None),
            (None, {"id": "VID123"}),
        ]
        fake_youtube = MagicMock()
        fake_youtube.videos.return_value.insert.return_value = fake_request

        with patch.object(svc, "_build_youtube", return_value=fake_youtube), patch(
            "googleapiclient.http.MediaFileUpload", return_value="MEDIA"
        ):
            result = svc.upload_video(
                video_path=__file__,  # 真实存在的文件，绕过存在性检查
                title="t" * 200,  # 超长标题应被裁剪到 100
                description="d",
                tags=["#a"],
                thumbnail_path=__file__,
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["video_id"], "VID123")
        self.assertEqual(result["url"], "https://youtu.be/VID123")

        insert_kwargs = fake_youtube.videos.return_value.insert.call_args.kwargs
        body = insert_kwargs["body"]
        self.assertEqual(insert_kwargs["part"], "snippet,status")
        self.assertEqual(len(body["snippet"]["title"]), 100)
        self.assertEqual(body["snippet"]["tags"], ["a", "brand"])
        self.assertEqual(body["snippet"]["categoryId"], "22")
        self.assertEqual(body["status"]["privacyStatus"], "public")
        # 提供 thumbnail_path 时应调用一次 thumbnails().set。
        fake_youtube.thumbnails.return_value.set.assert_called_once()

    def test_upload_invalid_privacy_falls_back_to_public(self):
        svc = make_service()
        fake_request = MagicMock()
        fake_request.next_chunk.side_effect = [(None, {"id": "X"})]
        fake_youtube = MagicMock()
        fake_youtube.videos.return_value.insert.return_value = fake_request

        with patch.object(svc, "_build_youtube", return_value=fake_youtube), patch(
            "googleapiclient.http.MediaFileUpload", return_value="MEDIA"
        ):
            svc.upload_video(__file__, title="hi", privacy_status="bogus")

        body = fake_youtube.videos.return_value.insert.call_args.kwargs["body"]
        self.assertEqual(body["status"]["privacyStatus"], "public")


if __name__ == "__main__":
    unittest.main()
