"""AI presenter ("talking person") providers. Each turns a portrait photo + voiceover into a 9:16 video."""
import time
from pathlib import Path

import httpx

from ..config import settings
from ..media import ffmpeg
from ..media.ffmpeg import FPS, H, W
from ..security import public_url


def render(image: Path, audio: Path, out: Path, duration: float, progress=None) -> Path:
    provider = settings.AVATAR_PROVIDER
    if provider == "did":
        raw = _did(image, audio, out.with_name("avatar_raw.mp4"), progress)
    elif provider == "lipsync_http":
        raw = _lipsync_http(image, audio, out.with_name("avatar_raw.mp4"))
    else:
        return photo_motion(image, out, duration)
    # Normalize whatever the provider returned to our 1080x1920/30fps format (video only).
    ffmpeg.run(["-i", raw, "-an", "-vf", ffmpeg.COVER, *ffmpeg.VCODEC, out])
    return out


def photo_motion(image: Path, out: Path, duration: float) -> Path:
    """Handheld-camera feel from a still: slow push-in with gentle sway. No lip-sync."""
    frames = int(duration * FPS) + 1
    vf = (
        f"scale={int(W * 1.25)}:{int(H * 1.25)}:force_original_aspect_ratio=increase,"
        f"crop={int(W * 1.25)}:{int(H * 1.25)},"
        f"zoompan=z='1.0+0.06*on/{frames}+0.006*sin(on/9)'"
        f":x='iw/2-(iw/zoom/2)+10*sin(on/23)':y='ih/2-(ih/zoom/2)+6*sin(on/31)'"
        f":d=1:s={W}x{H}:fps={FPS},setsar=1"
    )
    ffmpeg.run(["-loop", "1", "-i", image, "-t", f"{duration:.3f}", "-vf", vf, *ffmpeg.VCODEC, out])
    return out


def _did(image: Path, audio: Path, out: Path, progress=None) -> Path:
    if not settings.DID_API_KEY:
        raise RuntimeError("DID_API_KEY is not set.")
    headers = {"Authorization": f"Basic {settings.DID_API_KEY}", "Content-Type": "application/json"}
    body = {
        "source_url": public_url(image),
        "script": {"type": "audio", "audio_url": public_url(audio)},
        "config": {"stitch": True, "result_format": "mp4"},
    }
    r = httpx.post("https://api.d-id.com/talks", headers=headers, json=body, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"D-ID error {r.status_code}: {r.text[:300]} "
                           "(D-ID must be able to reach PUBLIC_BASE_URL over the internet)")
    talk_id = r.json()["id"]
    for i in range(240):
        time.sleep(5)
        s = httpx.get(f"https://api.d-id.com/talks/{talk_id}", headers=headers, timeout=30).json()
        if s.get("status") == "done":
            with httpx.stream("GET", s["result_url"], timeout=300) as resp:
                resp.raise_for_status()
                with open(out, "wb") as fh:
                    for chunk in resp.iter_bytes():
                        fh.write(chunk)
            return out
        if s.get("status") in ("error", "rejected"):
            raise RuntimeError(f"D-ID failed: {s.get('error') or s}")
        if progress:
            progress(None, f"Animating presenter (D-ID: {s.get('status', 'working')})…")
    raise RuntimeError("D-ID timed out after 20 minutes.")


def _lipsync_http(image: Path, audio: Path, out: Path) -> Path:
    """Generic contract for a self-hosted lip-sync server:
    POST {LIPSYNC_URL} multipart(image=<file>, audio=<file>) -> 200 with video/mp4 bytes."""
    if not settings.LIPSYNC_URL:
        raise RuntimeError("LIPSYNC_URL is not set.")
    with open(image, "rb") as fi, open(audio, "rb") as fa:
        r = httpx.post(settings.LIPSYNC_URL, files={"image": fi, "audio": fa}, timeout=3600)
    if r.status_code >= 400:
        raise RuntimeError(f"Lip-sync server error {r.status_code}: {r.text[:300]}")
    out.write_bytes(r.content)
    return out
