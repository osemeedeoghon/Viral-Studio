"""Signed public links so external services (Instagram, TikTok, D-ID) can fetch media without dashboard auth."""
import hashlib
import hmac
from pathlib import Path

from .config import file_url, settings


def sign(rel_path: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), rel_path.encode(), hashlib.sha256).hexdigest()[:40]


def verify(rel_path: str, sig: str | None) -> bool:
    return bool(sig) and hmac.compare_digest(sign(rel_path), sig)


def public_url(path: Path) -> str:
    url = file_url(path)  # /files/<rel>
    rel = url[len("/files/"):]
    return f"{settings.PUBLIC_BASE_URL}{url}?sig={sign(rel)}"
