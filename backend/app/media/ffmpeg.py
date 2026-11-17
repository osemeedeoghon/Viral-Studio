import json
import subprocess
from pathlib import Path

W, H, FPS = 1080, 1920, 30
# Shared encoder settings so segments can be concatenated losslessly.
VCODEC = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS)]
ACODEC = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000"]


class FFmpegError(RuntimeError):
    pass


def run(args: list[str]):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise FFmpegError(f"ffmpeg failed: {p.stderr.strip()[-1500:]}")


def probe(path: Path) -> dict:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        raise FFmpegError(f"ffprobe failed on {path}: {p.stderr.strip()}")
    info = json.loads(p.stdout)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    return {
        "duration": float(info["format"].get("duration", 0) or 0),
        "width": int(video["width"]) if video else 0,
        "height": int(video["height"]) if video else 0,
        "has_audio": audio is not None,
    }


def extract_audio(src: Path, dst: Path) -> Path:
    run(["-i", src, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", dst])
    return dst


def thumbnail(src: Path, dst: Path, at: float = 0.5) -> Path:
    run(["-ss", f"{at:.2f}", "-i", src, "-frames:v", "1", "-q:v", "3", dst])
    return dst


def concat(parts: list[Path], dst: Path) -> Path:
    lst = dst.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    run(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", dst])
    return dst


def subtitles_filter(ass_path: Path) -> str:
    from ..config import settings

    p = str(ass_path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    return f"subtitles=filename='{p}':fontsdir='{settings.FONTS_DIR}'"


COVER = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
