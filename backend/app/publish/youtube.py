"""YouTube Data API v3 uploads (OAuth refresh token stored in the local DB)."""
from pathlib import Path

from .. import db
from ..config import settings

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
REDIRECT_PATH = "/api/oauth/youtube/callback"


def _client_config() -> dict:
    return {"web": {
        "client_id": settings.YOUTUBE_CLIENT_ID,
        "client_secret": settings.YOUTUBE_CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }}


def auth_url() -> str:
    from google_auth_oauthlib.flow import Flow

    if not (settings.YOUTUBE_CLIENT_ID and settings.YOUTUBE_CLIENT_SECRET):
        raise RuntimeError("Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env first.")
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES,
                                   redirect_uri=settings.PUBLIC_BASE_URL + REDIRECT_PATH)
    url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    db.kv_set("youtube_oauth_state", state)
    db.kv_set("youtube_code_verifier", flow.code_verifier or "")
    return url


def finish_auth(code: str, state: str):
    from google_auth_oauthlib.flow import Flow

    if state != db.kv_get("youtube_oauth_state"):
        raise RuntimeError("OAuth state mismatch — start the connection again.")
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, state=state,
                                   redirect_uri=settings.PUBLIC_BASE_URL + REDIRECT_PATH,
                                   code_verifier=db.kv_get("youtube_code_verifier") or None)
    flow.fetch_token(code=code)
    if not flow.credentials.refresh_token:
        raise RuntimeError("Google did not return a refresh token. Remove the app's access in your Google account and retry.")
    db.kv_set("youtube_refresh_token", flow.credentials.refresh_token)


def upload(path: Path, title: str, description: str, tags: list[str], privacy: str = "public") -> dict:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    refresh = db.kv_get("youtube_refresh_token")
    if not refresh:
        raise RuntimeError("YouTube is not connected (Settings → Connect YouTube).")
    creds = Credentials(None, refresh_token=refresh, token_uri="https://oauth2.googleapis.com/token",
                        client_id=settings.YOUTUBE_CLIENT_ID, client_secret=settings.YOUTUBE_CLIENT_SECRET,
                        scopes=SCOPES)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    if "#shorts" not in (title + description).lower():
        description = f"{description}\n#Shorts".strip()
    body = {
        "snippet": {"title": title[:100] or "New video", "description": description[:4900],
                    "tags": tags[:30], "categoryId": "22"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True))
    response = None
    while response is None:
        _, response = req.next_chunk()
    return {"id": response["id"], "url": f"https://youtube.com/shorts/{response['id']}"}
