"""
One-time YouTube OAuth helper.

直接走 YouTube Data API 上传需要一个长期 refresh_token，而它只能通过一次性的
浏览器授权获得（client_id + client_secret 本身不足以上传）。用法：

    uv run python scripts/youtube_auth.py

完成浏览器授权后，把打印出来的 refresh_token 填入 config.toml 的
`youtube_refresh_token`（[app] 段）。
"""
import os
import sys

# 允许直接从项目根运行该脚本。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import config

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"


def main():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print(
            "Missing dependency. Install first:\n"
            "    uv add google-auth-oauthlib google-api-python-client google-auth-httplib2"
        )
        sys.exit(1)

    client_id = config.app.get("youtube_client_id", "")
    client_secret = config.app.get("youtube_client_secret", "")

    if not client_id or not client_secret:
        print(
            "youtube_client_id / youtube_client_secret are not set in config.toml.\n"
            "Create an OAuth client (type 'Desktop app') in Google Cloud Console > "
            "APIs & Services > Credentials, then fill both values under [app] first."
        )
        sys.exit(1)

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(
        client_config, scopes=[YOUTUBE_UPLOAD_SCOPE]
    )
    # access_type=offline + prompt=consent 确保每次都能拿到 refresh_token。
    credentials = flow.run_local_server(
        port=0, access_type="offline", prompt="consent"
    )

    print("\n" + "=" * 64)
    print("YouTube authorization complete.")
    print("Paste this line into config.toml under [app]:\n")
    print(f'youtube_refresh_token = "{credentials.refresh_token}"')
    print("=" * 64)


if __name__ == "__main__":
    main()
