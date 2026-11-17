"""TikTok Content Posting API — direct post via file upload."""
import time
from pathlib import Path

import httpx

from ..config import settings

API = "https://open.tiktokapis.com/v2"
CHUNK = 10 * 1024 * 1024


def upload(path: Path, caption: str) -> dict:
    if not settings.TIKTOK_ACCESS_TOKEN:
        raise RuntimeError("TIKTOK_ACCESS_TOKEN is not set.")
    headers = {"Authorization": f"Bearer {settings.TIKTOK_ACCESS_TOKEN}", "Content-Type": "application/json; charset=UTF-8"}
    size = path.stat().st_size
    chunk = size if size <= 64 * 1024 * 1024 else CHUNK
    count = max(1, size // chunk)  # TikTok folds the remainder into the last chunk
    init = httpx.post(f"{API}/post/publish/video/init/", headers=headers, timeout=60, json={
        "post_info": {"title": caption, "privacy_level": settings.TIKTOK_PRIVACY_LEVEL,
                      "disable_duet": False, "disable_comment": False, "disable_stitch": False},
        "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": count},
    }).json()
    if init.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok init failed: {init['error']}")
    upload_url, publish_id = init["data"]["upload_url"], init["data"]["publish_id"]

    with open(path, "rb") as f:
        for i in range(count):
            start = i * chunk
            end = size - 1 if i == count - 1 else start + chunk - 1
            f.seek(start)
            body = f.read(end - start + 1)
            r = httpx.put(upload_url, content=body, timeout=600, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(body)),
                "Content-Range": f"bytes {start}-{end}/{size}"})
            if r.status_code not in (200, 201, 206):
                raise RuntimeError(f"TikTok upload failed ({r.status_code}): {r.text[:200]}")

    for _ in range(60):
        time.sleep(5)
        s = httpx.post(f"{API}/post/publish/status/fetch/", headers=headers,
                       json={"publish_id": publish_id}, timeout=30).json()
        status = s.get("data", {}).get("status")
        if status == "PUBLISH_COMPLETE":
            return {"publish_id": publish_id, "status": status}
        if status == "FAILED":
            raise RuntimeError(f"TikTok processing failed: {s.get('data', {}).get('fail_reason')}")
    return {"publish_id": publish_id, "status": "PROCESSING"}
