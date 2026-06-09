"""
YouTube Data API v3 integration for uploading generated videos to YouTube.

Docs: https://developers.google.com/youtube/v3/guide

不同于 upload_post.py（走 upload-post.com 第三方聚合服务），这里直接调用官方
YouTube Data API v3，使用 OAuth2 refresh_token 免交互上传。refresh_token 由
scripts/youtube_auth.py 一次性生成（client_id + client_secret 本身不足以上传）。
"""
import os
from typing import Optional

from loguru import logger

from app.config import config

# 上传只需要 youtube.upload 作用域，遵循最小权限原则。
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
TOKEN_URI = "https://oauth2.googleapis.com/token"
VALID_PRIVACY = {"public", "unlisted", "private"}

# YouTube 硬上限：标题 100 字符、描述 5000 字符。超长会被 API 直接拒绝。
MAX_TITLE_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 5000


class YouTubeUploadService:
    """
    Service for uploading videos to YouTube via the official Data API v3.
    """

    def __init__(self):
        self.enabled = config.app.get("youtube_enabled", False)
        self.client_id = config.app.get("youtube_client_id", "")
        self.client_secret = config.app.get("youtube_client_secret", "")
        self.refresh_token = config.app.get("youtube_refresh_token", "")
        self.privacy_status = config.app.get("youtube_privacy_status", "public")
        self.category_id = str(config.app.get("youtube_category_id", "22"))
        self.default_tags = config.app.get("youtube_default_tags", []) or []
        self.made_for_kids = config.app.get("youtube_made_for_kids", False)
        self.auto_upload = config.app.get("youtube_auto_upload", False)

    def is_configured(self) -> bool:
        """Check if YouTube upload is properly configured."""
        return bool(
            self.enabled
            and self.client_id
            and self.client_secret
            and self.refresh_token
        )

    def _build_youtube(self):
        """
        用 refresh_token 构造一个会自动续期的 YouTube API client。

        运行时不触发任何浏览器授权；google 客户端库较重，这里延迟到调用时再
        import，避免未安装依赖的环境在 import app.services 时直接报错。
        """
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        credentials = Credentials(
            token=None,
            refresh_token=self.refresh_token,
            client_id=self.client_id,
            client_secret=self.client_secret,
            token_uri=TOKEN_URI,
            scopes=[YOUTUBE_UPLOAD_SCOPE],
        )
        # cache_discovery=False：避免只读/容器环境下写 discovery 缓存触发告警。
        return build("youtube", "v3", credentials=credentials, cache_discovery=False)

    def _normalize_tags(self, tags: Optional[list]) -> list:
        # 合并入参标签与默认标签，去掉 '#' 前缀并去重（YouTube tags 不带 '#'）。
        merged = []
        for raw in list(tags or []) + list(self.default_tags):
            tag = str(raw).lstrip("#").strip()
            if tag and tag not in merged:
                merged.append(tag)
        return merged

    def upload_video(
        self,
        video_path: str,
        title: str,
        description: str = "",
        tags: Optional[list] = None,
        category_id: Optional[str] = None,
        privacy_status: Optional[str] = None,
        thumbnail_path: Optional[str] = None,
    ) -> dict:
        """
        Upload a single video file to YouTube.

        Args:
            video_path (str): Path to the video file.
            title (str): Video title (truncated to 100 chars).
            description (str): Video description (truncated to 5000 chars).
            tags (list): Video tags (merged with configured default tags).
            category_id (str): YouTube category id (defaults to config).
            privacy_status (str): public | unlisted | private (defaults to config).
            thumbnail_path (str): Optional custom thumbnail image.

        Returns:
            dict: {"success": bool, "video_id": str, "url": str, "error": str}
        """
        if not self.is_configured():
            logger.warning("YouTube upload is not configured. Skipping upload.")
            return {"success": False, "error": "YouTube upload not configured"}

        if not os.path.exists(video_path):
            logger.error(f"Video file not found: {video_path}")
            return {"success": False, "error": f"Video file not found: {video_path}"}

        privacy = (privacy_status or self.privacy_status or "public").lower()
        if privacy not in VALID_PRIVACY:
            privacy = "public"
        category = str(category_id or self.category_id or "22")
        title = (title or "Untitled").strip()[:MAX_TITLE_LENGTH]

        logger.info(f"Uploading video to YouTube (privacy={privacy}): {video_path}")

        try:
            from googleapiclient.http import MediaFileUpload

            youtube = self._build_youtube()
            body = {
                "snippet": {
                    "title": title,
                    "description": (description or "")[:MAX_DESCRIPTION_LENGTH],
                    "tags": self._normalize_tags(tags),
                    "categoryId": category,
                },
                "status": {
                    "privacyStatus": privacy,
                    "selfDeclaredMadeForKids": bool(self.made_for_kids),
                },
            }
            media = MediaFileUpload(video_path, resumable=True)
            request = youtube.videos().insert(
                part="snippet,status", body=body, media_body=media
            )

            # resumable 分块上传：大文件时避免一次性占满内存或触发超时。
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    logger.debug(
                        f"YouTube upload progress: {int(status.progress() * 100)}%"
                    )

            video_id = response.get("id")
            url = f"https://youtu.be/{video_id}" if video_id else ""
            logger.success(f"✅ Video uploaded to YouTube! {url}")

            if thumbnail_path and os.path.exists(thumbnail_path):
                self._set_thumbnail(youtube, video_id, thumbnail_path)

            return {"success": True, "video_id": video_id, "url": url}

        except Exception as e:
            logger.error(f"Failed to upload video to YouTube: {str(e)}")
            return {"success": False, "error": str(e)}

    def _set_thumbnail(self, youtube, video_id: str, thumbnail_path: str):
        # 自定义缩略图要求频道已验证；未验证会返回 403。失败不影响上传成功。
        try:
            from googleapiclient.http import MediaFileUpload

            youtube.thumbnails().set(
                videoId=video_id, media_body=MediaFileUpload(thumbnail_path)
            ).execute()
            logger.info("✅ YouTube thumbnail set.")
        except Exception as e:
            logger.warning(
                f"⚠️ Failed to set YouTube thumbnail (channel may be unverified): {str(e)}"
            )


# Singleton instance
youtube_upload_service = YouTubeUploadService()


def upload_to_youtube(
    video_path: str,
    title: str,
    description: str = "",
    tags: Optional[list] = None,
    thumbnail_path: Optional[str] = None,
) -> dict:
    """
    Convenience function to upload a video to YouTube.

    Args:
        video_path (str): Path to the video file.
        title (str): Video title/caption.
        description (str): Video description.
        tags (list): Video tags.
        thumbnail_path (str): Optional thumbnail image.

    Returns:
        dict: API result
    """
    return youtube_upload_service.upload_video(
        video_path=video_path,
        title=title,
        description=description,
        tags=tags,
        thumbnail_path=thumbnail_path,
    )
