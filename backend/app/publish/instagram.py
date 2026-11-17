"""Instagram Reels via the Graph API (Instagram fetches the video from a signed public URL on this server)."""
import time
from pathlib import Path

import httpx

from ..config import settings
from ..security import public_url


def upload(path: Path, caption: str) -> dict:
    if not (settings.IG_USER_ID and settings.IG_ACCESS_TOKEN):
        raise RuntimeError("IG_USER_ID / IG_ACCESS_TOKEN are not set.")
    if settings.PUBLIC_BASE_URL.startswith("http://localhost"):
        raise RuntimeError("Instagram needs PUBLIC_BASE_URL to be a public https URL so it can download the video.")
    base = f"https://graph.facebook.com/{settings.GRAPH_API_VERSION}"
    token = settings.IG_ACCESS_TOKEN
    r = httpx.post(f"{base}/{settings.IG_USER_ID}/media", timeout=60, data={
        "media_type": "REELS", "video_url": public_url(path), "caption": caption,
        "share_to_feed": "true", "access_token": token}).json()
    if "id" not in r:
        raise RuntimeError(f"Instagram container failed: {r.get('error', r)}")
    container = r["id"]
    for _ in range(120):
        time.sleep(5)
        s = httpx.get(f"{base}/{container}", params={"fields": "status_code,status", "access_token": token}, timeout=30).json()
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram processing failed: {s.get('status')}")
    else:
        raise RuntimeError("Instagram processing timed out.")
    p = httpx.post(f"{base}/{settings.IG_USER_ID}/media_publish", timeout=60,
                   data={"creation_id": container, "access_token": token}).json()
    if "id" not in p:
        raise RuntimeError(f"Instagram publish failed: {p.get('error', p)}")
    return {"id": p["id"]}
