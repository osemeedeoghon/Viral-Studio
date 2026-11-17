"""Stock b-roll search (Pexels, free API key)."""
from pathlib import Path

import httpx

from ..config import settings


def search_and_download(query: str, dest: Path, min_duration: float = 3.0, used: set | None = None) -> Path | None:
    if not settings.PEXELS_API_KEY or not query:
        return None
    used = used if used is not None else set()
    try:
        r = httpx.get(
            "https://api.pexels.com/videos/search",
            params={"query": query, "orientation": "portrait", "size": "medium", "per_page": 10},
            headers={"Authorization": settings.PEXELS_API_KEY},
            timeout=30,
        )
        r.raise_for_status()
        for video in r.json().get("videos", []):
            if video["id"] in used or video.get("duration", 0) < min_duration:
                continue
            files = [f for f in video.get("video_files", [])
                     if f.get("file_type") == "video/mp4" and (f.get("height") or 0) >= 1280]
            if not files:
                continue
            best = min(files, key=lambda f: abs((f.get("height") or 0) - 1920))
            with httpx.stream("GET", best["link"], follow_redirects=True, timeout=120) as resp:
                resp.raise_for_status()
                with open(dest, "wb") as fh:
                    for chunk in resp.iter_bytes():
                        fh.write(chunk)
            used.add(video["id"])
            return dest
    except httpx.HTTPError:
        return None
    return None
