import os
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


class Settings:
    DATA_DIR = Path(_env("DATA_DIR", "/data"))
    REDIS_URL = _env("REDIS_URL", "redis://redis:6379/0")
    FRONTEND_DIR = Path(_env("FRONTEND_DIR", "/app/frontend"))

    APP_PASSWORD = _env("APP_PASSWORD")
    SECRET_KEY = _env("SECRET_KEY", "change-me")
    PUBLIC_BASE_URL = _env("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

    ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
    ANTHROPIC_MODEL = _env("ANTHROPIC_MODEL", "claude-opus-5-5")

    WHISPER_MODEL = _env("WHISPER_MODEL", "small")
    WHISPER_DEVICE = _env("WHISPER_DEVICE", "cpu")
    WHISPER_COMPUTE_TYPE = _env("WHISPER_COMPUTE_TYPE", "int8")

    TTS_PROVIDER = _env("TTS_PROVIDER", "kokoro")
    KOKORO_URL = _env("KOKORO_URL", "http://kokoro:8880").rstrip("/")
    KOKORO_VOICE = _env("KOKORO_VOICE", "af_heart")
    ELEVENLABS_API_KEY = _env("ELEVENLABS_API_KEY")
    ELEVENLABS_VOICE_ID = _env("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
    ELEVENLABS_MODEL = _env("ELEVENLABS_MODEL", "eleven_multilingual_v2")

    AVATAR_PROVIDER = _env("AVATAR_PROVIDER", "photo")
    DID_API_KEY = _env("DID_API_KEY")
    LIPSYNC_URL = _env("LIPSYNC_URL")

    PEXELS_API_KEY = _env("PEXELS_API_KEY")

    YOUTUBE_CLIENT_ID = _env("YOUTUBE_CLIENT_ID")
    YOUTUBE_CLIENT_SECRET = _env("YOUTUBE_CLIENT_SECRET")
    TIKTOK_ACCESS_TOKEN = _env("TIKTOK_ACCESS_TOKEN")
    TIKTOK_PRIVACY_LEVEL = _env("TIKTOK_PRIVACY_LEVEL", "SELF_ONLY")
    IG_USER_ID = _env("IG_USER_ID")
    IG_ACCESS_TOKEN = _env("IG_ACCESS_TOKEN")
    GRAPH_API_VERSION = _env("GRAPH_API_VERSION", "v21.0")

    FONTS_DIR = _env("FONTS_DIR", "/usr/share/fonts/viral")
    CAPTION_FONT = _env("CAPTION_FONT", "Anton")


settings = Settings()
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)


def job_dir(job_id: str) -> Path:
    d = settings.DATA_DIR / "jobs" / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def uploads_dir() -> Path:
    d = settings.DATA_DIR / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def file_url(path: Path) -> str:
    """Dashboard URL for a file inside DATA_DIR."""
    rel = Path(path).resolve().relative_to(settings.DATA_DIR.resolve())
    return f"/files/{rel.as_posix()}"
