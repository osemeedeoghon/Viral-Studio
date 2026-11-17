"""Text-to-speech providers. Each returns the path of an mp3 file."""
from pathlib import Path

import httpx

from ..config import settings


def synthesize(text: str, out: Path, voice: str | None = None) -> Path:
    provider = settings.TTS_PROVIDER
    if provider == "elevenlabs":
        return _elevenlabs(text, out, voice)
    if provider == "kokoro":
        return _kokoro(text, out, voice)
    raise RuntimeError(f"Unknown TTS_PROVIDER '{provider}' (use kokoro or elevenlabs).")


def _kokoro(text: str, out: Path, voice: str | None) -> Path:
    r = httpx.post(
        f"{settings.KOKORO_URL}/v1/audio/speech",
        json={"model": "kokoro", "input": text, "voice": voice or settings.KOKORO_VOICE,
              "response_format": "mp3", "speed": 1.05},
        timeout=300,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Kokoro TTS error {r.status_code}: {r.text[:300]}")
    out.write_bytes(r.content)
    return out


def _elevenlabs(text: str, out: Path, voice: str | None) -> Path:
    if not settings.ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY is not set.")
    r = httpx.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice or settings.ELEVENLABS_VOICE_ID}",
        headers={"xi-api-key": settings.ELEVENLABS_API_KEY, "Accept": "audio/mpeg"},
        json={"text": text, "model_id": settings.ELEVENLABS_MODEL,
              "voice_settings": {"stability": 0.4, "similarity_boost": 0.8, "style": 0.35}},
        timeout=300,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"ElevenLabs error {r.status_code}: {r.text[:300]}")
    out.write_bytes(r.content)
    return out
