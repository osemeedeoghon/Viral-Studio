"""Publish a rendered video to one or more social platforms (runs as a background job)."""
from ..config import settings


def run(job_id: str, data: dict, progress) -> dict:
    from . import instagram, tiktok, youtube

    path = settings.DATA_DIR / data["file"]
    if not path.resolve().is_relative_to(settings.DATA_DIR.resolve()) or not path.exists():
        raise RuntimeError("Video file not found.")
    title = data.get("title", "").strip()
    caption = data.get("caption", "").strip()
    tags = [t.lstrip("#") for t in data.get("tags", []) if t]
    hashtags = " ".join(f"#{t}" for t in tags)

    platforms = data.get("platforms", [])
    results, errors = {}, {}
    for i, platform in enumerate(platforms):
        progress(0.05 + 0.9 * i / max(len(platforms), 1), f"Publishing to {platform}…")
        try:
            if platform == "youtube":
                results[platform] = youtube.upload(path, title or caption[:90], f"{caption}\n\n{hashtags}".strip(),
                                                   tags, data.get("privacy", "public"))
            elif platform == "tiktok":
                results[platform] = tiktok.upload(path, f"{caption} {hashtags}".strip()[:2200])
            elif platform == "instagram":
                results[platform] = instagram.upload(path, f"{caption}\n\n{hashtags}".strip()[:2200])
            else:
                raise RuntimeError(f"Unknown platform {platform}")
        except Exception as e:
            errors[platform] = str(e)[:400]
    if errors and not results:
        raise RuntimeError("; ".join(f"{k}: {v}" for k, v in errors.items()))
    return {"results": results, "errors": errors}


def status() -> dict:
    from .. import db

    return {
        "youtube": bool(settings.YOUTUBE_CLIENT_ID and db.kv_get("youtube_refresh_token")),
        "youtube_configured": bool(settings.YOUTUBE_CLIENT_ID and settings.YOUTUBE_CLIENT_SECRET),
        "tiktok": bool(settings.TIKTOK_ACCESS_TOKEN),
        "instagram": bool(settings.IG_USER_ID and settings.IG_ACCESS_TOKEN),
    }
