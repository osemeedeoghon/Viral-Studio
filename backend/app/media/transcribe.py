"""Local speech-to-text with word timestamps (faster-whisper)."""
import json
from pathlib import Path

from ..config import settings

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(
            settings.WHISPER_MODEL,
            device=settings.WHISPER_DEVICE,
            compute_type=settings.WHISPER_COMPUTE_TYPE,
            download_root=str(settings.DATA_DIR / "models"),
        )
    return _model


def _load_audio(path: Path):
    """Decode any audio/video to 16 kHz mono float32 with ffmpeg. We hand whisper raw samples so it
    never touches PyAV, whose API changes have broken faster-whisper's own decoder (av>=16)."""
    import subprocess

    import numpy as np

    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def transcribe(audio: Path, cache: Path | None = None, language: str | None = None, on_progress=None) -> dict:
    if cache and cache.exists():
        return json.loads(cache.read_text())
    segments, info = _get_model().transcribe(
        _load_audio(audio), word_timestamps=True, vad_filter=True, language=language or None
    )
    out = {"language": info.language, "duration": info.duration, "segments": []}
    for seg in segments:
        words = [
            {"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word.strip()}
            for w in (seg.words or []) if w.word.strip()
        ]
        out["segments"].append(
            {"start": round(seg.start, 3), "end": round(seg.end, 3), "text": seg.text.strip(), "words": words}
        )
        if on_progress and info.duration:
            on_progress(min(seg.end / info.duration, 1.0))
    if cache:
        cache.write_text(json.dumps(out))
    return out


def all_words(transcript: dict) -> list[dict]:
    return [w for s in transcript["segments"] for w in s["words"]]


def words_between(transcript: dict, start: float, end: float, offset: float | None = None) -> list[dict]:
    """Words inside [start, end], re-timed so `start` (or `offset`) becomes 0."""
    base = start if offset is None else offset
    return [
        {"start": max(0.0, w["start"] - base), "end": max(0.0, w["end"] - base), "word": w["word"]}
        for w in all_words(transcript)
        if w["start"] >= start - 0.05 and w["end"] <= end + 0.05
    ]
