"""Long video -> viral vertical shorts with stylized captions."""
import json
import shutil
from pathlib import Path

from pydantic import BaseModel, Field

from .. import llm
from ..config import file_url, job_dir, settings
from ..media import captions, crop, ffmpeg
from ..media.transcribe import transcribe, words_between


class Highlight(BaseModel):
    start: float = Field(description="Clip start time in seconds (from the transcript timestamps)")
    end: float = Field(description="Clip end time in seconds")
    title: str = Field(description="Punchy title for the short, max 60 characters")
    hook: str = Field(description="The opening line that grabs attention")
    virality_score: int = Field(description="0-100 estimate of how likely this clip performs well")
    reason: str = Field(description="One sentence on why this moment is engaging")
    hashtags: list[str]


class Highlights(BaseModel):
    clips: list[Highlight]


SYSTEM = """You are a senior short-form video editor who has cut thousands of viral TikToks, Reels and YouTube Shorts.
You pick moments that work completely on their own, out of context, for a scrolling viewer:
- A strong hook in the first 2 seconds (bold claim, question, surprising fact, conflict, emotion).
- One clear idea or story with a payoff; never end mid-thought.
- Start exactly where a sentence starts and end where a sentence ends.
- Prefer high energy, humor, strong opinions, vulnerable stories, actionable tips and counter-intuitive insights.
Clips must not overlap. Use only timestamps that appear in the transcript."""


def download(url: str, dest: Path, progress) -> tuple[Path, str]:
    import yt_dlp

    def hook(d):
        if d.get("status") == "downloading" and d.get("total_bytes"):
            progress(0.02 + 0.13 * d["downloaded_bytes"] / d["total_bytes"], "Downloading video…")

    opts = {
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(dest / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "progress_hooks": [hook],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    files = sorted(dest.glob("source.*"), key=lambda p: p.stat().st_size, reverse=True)
    if not files:
        raise RuntimeError("Download failed — no video file produced.")
    return files[0], info.get("title") or "Video"


def transcript_text(transcript: dict) -> str:
    return "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in transcript["segments"])


def snap(transcript: dict, start: float, end: float, duration: float) -> tuple[float, float]:
    """Snap clip edges to word boundaries with a little breathing room."""
    words = [w for s in transcript["segments"] for w in s["words"]]
    if words:
        start = min(words, key=lambda w: abs(w["start"] - start))["start"]
        end = min(words, key=lambda w: abs(w["end"] - end))["end"]
    return max(0.0, start - 0.15), min(duration, end + 0.35)


def find_highlights(transcript: dict, n: int, min_s: int, max_s: int, title: str, duration: float) -> list[dict]:
    prompt = (
        f"Video title: {title}\nVideo length: {duration:.0f}s\n\n"
        f"Find the {n} best moments to turn into standalone vertical shorts, each between {min_s} and {max_s} seconds long. "
        f"Order them by virality_score, highest first.\n\nTranscript (timestamps in seconds):\n{transcript_text(transcript)}"
    )
    result = llm.structured(SYSTEM, prompt, Highlights)
    clips = []
    for h in result.clips:
        start, end = snap(transcript, h.start, h.end, duration)
        if end - start < min_s * 0.6:
            continue
        if end - start > max_s * 1.15:
            end = start + max_s
        if any(start < c["end"] and end > c["start"] for c in clips):
            continue
        clips.append({**h.model_dump(), "start": round(start, 2), "end": round(end, 2)})
    return sorted(clips, key=lambda c: -c["virality_score"])[:n]


def render_clip(src: Path, meta: dict, clip: dict, transcript: dict, out: Path, layout: str, style: str):
    start, end = clip["start"], clip["end"]
    track = crop.face_track(src, start, end) if layout == "face" and meta["width"] > meta["height"] else None
    vf = crop.reframe_filter(meta["width"], meta["height"], track, layout)
    if style != "none":
        ass = captions.write_ass(out.with_suffix(".ass"), words_between(transcript, start, end), style)
        vf += "," + ffmpeg.subtitles_filter(ass)
    audio = ffmpeg.ACODEC if meta["has_audio"] else ["-an"]
    ffmpeg.run(["-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", src, "-vf", vf,
                *ffmpeg.VCODEC, *audio, "-movflags", "+faststart", out])


def run(job_id: str, data: dict, progress) -> dict:
    d = job_dir(job_id)
    n = int(data.get("num_clips", 5))
    min_s, max_s = int(data.get("min_seconds", 20)), int(data.get("max_seconds", 60))
    layout = data.get("layout", "face")
    style = data.get("caption_style", "bold")

    progress(0.02, "Fetching video…")
    if data.get("upload_path"):
        src = d / ("source" + Path(data["upload_path"]).suffix)
        shutil.copy(settings.DATA_DIR / data["upload_path"], src)
        title = data.get("title") or Path(data["upload_path"]).stem
    else:
        src, title = download(data["url"], d, progress)
    meta = ffmpeg.probe(src)
    if not meta["has_audio"]:
        raise RuntimeError("This video has no audio track, so there is nothing to transcribe.")

    progress(0.16, "Transcribing audio…")
    wav = ffmpeg.extract_audio(src, d / "audio.wav")
    transcript = transcribe(wav, d / "transcript.json", data.get("language"),
                            on_progress=lambda f: progress(0.16 + 0.34 * f, "Transcribing audio…"))
    wav.unlink(missing_ok=True)
    if not transcript["segments"]:
        raise RuntimeError("No speech was detected in this video.")

    progress(0.52, "Finding the most engaging moments…")
    clips = find_highlights(transcript, n, min_s, max_s, title, meta["duration"])
    if not clips:
        raise RuntimeError("Couldn't find suitable moments — try a different clip length range.")

    results = []
    for i, clip in enumerate(clips, 1):
        progress(0.6 + 0.38 * (i - 1) / len(clips), f"Rendering short {i} of {len(clips)}…")
        out = d / f"short_{i:02d}.mp4"
        render_clip(src, meta, clip, transcript, out, layout, style)
        thumb = ffmpeg.thumbnail(out, d / f"short_{i:02d}.jpg", at=min(1.0, (clip["end"] - clip["start"]) / 2))
        results.append({**clip, "video": file_url(out), "thumbnail": file_url(thumb),
                        "duration": round(clip["end"] - clip["start"], 1)})

    (d / "clips.json").write_text(json.dumps(results, indent=2))
    if not data.get("keep_source"):
        src.unlink(missing_ok=True)
    return {"title": title, "clips": results}
