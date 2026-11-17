"""Product URL -> complete UGC-style marketing short (presenter + voiceover + b-roll + captions)."""
import json
import shutil
import textwrap
from pathlib import Path
from typing import Literal

import anthropic
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pydantic import BaseModel, Field

from .. import llm
from ..config import file_url, job_dir, settings
from ..media import captions, ffmpeg
from ..media.ffmpeg import FPS, H, W
from ..media.transcribe import all_words, transcribe
from ..providers import avatar, broll, tts
from ..providers.scrape import download_images, scrape_product


class Scene(BaseModel):
    voiceover: str = Field(description="What the presenter says in this beat, spoken naturally")
    visual: Literal["presenter", "broll", "product"] = Field(
        description="presenter = person talking to camera; broll = stock footage; product = product photo")
    broll_query: str = Field(description="2-4 word stock-footage search query for this beat (always fill in)")
    on_screen_text: str = Field(description="Optional punchy overlay text, max 5 words, or empty string")


class UGCScript(BaseModel):
    title: str
    scenes: list[Scene]
    caption: str = Field(description="Social media caption for the post, 1-3 short sentences")
    hashtags: list[str]


SYSTEM = """You write scripts for UGC-style (user-generated content) short-form video ads for TikTok, Reels and Shorts.
They must feel like a real customer filming themselves on their phone, not like a polished commercial:
- First person, casual, conversational, contractions; sounds spoken, never written. No corporate language.
- Scene 1 is the hook (presenter on camera): a scroll-stopping first line in under 2 seconds.
- Show a relatable problem, then the product as the fix, with 1-3 concrete specifics taken from the product info.
- End with a natural call to action.
- Mix visuals: start and end on the presenter, cut to broll/product in between so it never feels static.
- Each scene is one short beat (one or two sentences). Do not invent claims, prices, discounts or results that are not in the product info."""

STYLES = {
    "testimonial": "Personal testimonial: 'I've been using this for X and...'",
    "problem-solution": "Problem/solution: open on a frustrating problem, reveal the product as the fix.",
    "unboxing": "Unboxing/first impressions: excited, discovering features one by one.",
    "listicle": "'3 reasons I love this' style list.",
    "storytime": "Storytime: a short personal story that leads naturally to the product.",
}


def write_script(product: dict, data: dict) -> UGCScript:
    seconds = int(data.get("duration", 30))
    info = {k: product.get(k) for k in ("name", "brand", "price", "description", "url")}
    prompt = (
        f"Product info:\n{json.dumps(info, indent=2)}\n\nPage text (may contain noise):\n{product.get('page_text', '')[:6000]}\n\n"
        f"Style: {STYLES.get(data.get('style', 'testimonial'), data.get('style'))}\n"
        f"Tone: {data.get('tone') or 'enthusiastic but genuine'}\n"
        f"Target audience: {data.get('audience') or 'infer from the product'}\n"
        f"Extra instructions: {data.get('notes') or 'none'}\n"
        f"Length: about {seconds} seconds spoken (~{int(seconds * 2.6)} words total), 5-9 scenes."
    )
    images = [{"type": "image", "source": {"type": "url", "url": u}} for u in product.get("images", [])[:3]]
    try:
        return llm.structured(SYSTEM, [*images, {"type": "text", "text": prompt}] if images else prompt, UGCScript)
    except anthropic.BadRequestError:
        return llm.structured(SYSTEM, prompt, UGCScript)  # an image URL couldn't be fetched


def product_card(img: Path, out: Path) -> Path:
    """Product photo centered on a blurred version of itself, 9:16."""
    src = Image.open(img).convert("RGB")
    bg = src.copy()
    scale = max(W / bg.width, H / bg.height)
    bg = bg.resize((int(bg.width * scale) + 1, int(bg.height * scale) + 1))
    bg = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2, (bg.width - W) // 2 + W, (bg.height - H) // 2 + H))
    bg = bg.filter(ImageFilter.GaussianBlur(40)).point(lambda v: int(v * 0.75))
    fg = src.copy()
    fg.thumbnail((int(W * 0.86), int(H * 0.6)))
    mask = Image.new("L", fg.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *fg.size), radius=36, fill=255)
    shadow = Image.new("L", (fg.width + 80, fg.height + 80), 0)
    ImageDraw.Draw(shadow).rounded_rectangle((40, 40, fg.width + 40, fg.height + 40), radius=36, fill=150)
    shadow = shadow.filter(ImageFilter.GaussianBlur(24))
    x, y = (W - fg.width) // 2, (H - fg.height) // 2
    bg.paste((0, 0, 0), (x - 40, y - 20), shadow)
    bg.paste(fg, (x, y), mask)
    bg.save(out, quality=94)
    return out


def text_card(text: str, out: Path) -> Path:
    """Last-resort visual: gradient card with the line being spoken."""
    im = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(im)
    for yy in range(H):
        f = yy / H
        draw.line([(0, yy), (W, yy)], fill=(int(30 + 90 * f), int(20 + 30 * f), int(80 + 60 * (1 - f))))
    try:
        font = ImageFont.truetype(str(Path(settings.FONTS_DIR) / "Anton-Regular.ttf"), 96)
    except OSError:
        font = ImageFont.load_default()
    wrapped = textwrap.fill(text.upper(), 16)
    draw.multiline_text((W // 2, H // 2), wrapped, font=font, fill="white", anchor="mm", align="center", spacing=18)
    im.save(out, quality=94)
    return out


def still_segment(image: Path, out: Path, dur: float) -> Path:
    frames = int(dur * FPS) + 1
    vf = (f"scale={int(W * 1.1)}:{int(H * 1.1)}:force_original_aspect_ratio=increase,crop={int(W * 1.1)}:{int(H * 1.1)},"
          f"zoompan=z='1.0+0.08*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},setsar=1")
    ffmpeg.run(["-loop", "1", "-i", image, "-t", f"{dur:.3f}", "-vf", vf, *ffmpeg.VCODEC, "-an", out])
    return out


def run(job_id: str, data: dict, progress) -> dict:
    d = job_dir(job_id)
    style = data.get("caption_style", "bold")

    progress(0.03, "Reading product page…")
    product = scrape_product(data["product_url"])
    product_imgs = download_images(product["images"], d)
    (d / "product.json").write_text(json.dumps(product, indent=2))

    progress(0.12, "Writing the script…")
    script = write_script(product, data)
    scenes = [s for s in script.scenes if s.voiceover.strip()]
    if not scenes:
        raise RuntimeError("Script came back empty.")
    (d / "script.json").write_text(script.model_dump_json(indent=2))

    # --- Voiceover: one file per scene so we know exactly when each beat starts.
    timeline, parts, t = [], [], 0.0
    for i, s in enumerate(scenes):
        progress(0.2 + 0.15 * i / len(scenes), f"Recording voiceover {i + 1}/{len(scenes)}…")
        mp3 = tts.synthesize(s.voiceover, d / f"vo_{i:02d}.mp3", data.get("voice"))
        wav = d / f"vo_{i:02d}.wav"
        ffmpeg.run(["-i", mp3, "-af", "apad=pad_dur=0.12", "-ac", "1", "-ar", "48000", wav])
        dur = ffmpeg.probe(wav)["duration"]
        timeline.append((t, t + dur))
        parts.append(wav)
        t += dur
    total = t
    voice = d / "voice.wav"
    ffmpeg.run([*sum((["-i", p] for p in parts), []), "-filter_complex",
                "".join(f"[{i}:a]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1[a]",
                "-map", "[a]", voice])

    progress(0.38, "Timing captions…")
    words = all_words(transcribe(voice, d / "voice_transcript.json"))

    # --- Presenter
    presenter = None
    if data.get("avatar_path"):
        progress(0.45, "Animating presenter…")
        img = d / ("presenter" + Path(data["avatar_path"]).suffix.lower())
        shutil.copy(settings.DATA_DIR / data["avatar_path"], img)
        voice_mp3 = d / "voice.mp3"
        ffmpeg.run(["-i", voice, "-c:a", "libmp3lame", "-b:a", "192k", voice_mp3])
        presenter = avatar.render(img, voice_mp3, d / "presenter.mp4", total,
                                  progress=lambda _f, m: progress(0.5, m))

    # --- Scene visuals
    used: set = set()
    segments = []
    for i, (s, (t0, t1)) in enumerate(zip(scenes, timeline)):
        progress(0.6 + 0.3 * i / len(scenes), f"Building scene {i + 1}/{len(scenes)}…")
        dur = t1 - t0
        seg = d / f"seg_{i:02d}.mp4"
        visual = s.visual
        if visual == "presenter" and not presenter:
            visual = "broll"
        if visual == "product" and not product_imgs:
            visual = "broll"

        done = False
        if visual == "presenter":
            ffmpeg.run(["-ss", f"{t0:.3f}", "-t", f"{dur:.3f}", "-i", presenter, "-an",
                        "-vf", f"{ffmpeg.COVER},fps={FPS}", *ffmpeg.VCODEC, seg])
            done = True
        elif visual == "broll":
            clip = broll.search_and_download(s.broll_query, d / f"broll_{i:02d}.mp4", min(dur, 4), used)
            if clip:
                ffmpeg.run(["-stream_loop", "-1", "-i", clip, "-t", f"{dur:.3f}", "-an",
                            "-vf", f"{ffmpeg.COVER},fps={FPS}", *ffmpeg.VCODEC, seg])
                done = True
        if not done and product_imgs:
            card = product_card(product_imgs[i % len(product_imgs)], d / f"card_{i:02d}.jpg")
            still_segment(card, seg, dur)
            done = True
        if not done and presenter:
            ffmpeg.run(["-ss", f"{t0:.3f}", "-t", f"{dur:.3f}", "-i", presenter, "-an",
                        "-vf", f"{ffmpeg.COVER},fps={FPS}", *ffmpeg.VCODEC, seg])
            done = True
        if not done:
            still_segment(text_card(s.on_screen_text or s.voiceover[:60], d / f"card_{i:02d}.jpg"), seg, dur)
        segments.append(seg)

    progress(0.92, "Final render…")
    video = ffmpeg.concat(segments, d / "visuals.mp4")
    overlays = [(t0, min(t1, t0 + 2.5), s.on_screen_text) for s, (t0, t1) in zip(scenes, timeline)]
    ass = captions.write_ass(d / "captions.ass", words if style != "none" else [], style, overlays)

    inputs = ["-i", video, "-i", voice]
    afilter = "[1:a]loudnorm=I=-14:TP=-1.5[a]"
    if data.get("music_path"):
        inputs += ["-stream_loop", "-1", "-i", settings.DATA_DIR / data["music_path"]]
        afilter = ("[1:a]loudnorm=I=-14:TP=-1.5[v];[2:a]volume=0.12[m];"
                   "[v][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
    final = d / "ugc_final.mp4"
    ffmpeg.run([*inputs, "-filter_complex", f"[0:v]{ffmpeg.subtitles_filter(ass)}[v];{afilter}",
                "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
                *ffmpeg.VCODEC, *ffmpeg.ACODEC, "-movflags", "+faststart", final])
    thumb = ffmpeg.thumbnail(final, d / "ugc_final.jpg", at=0.8)

    for p in [*parts, *d.glob("vo_*.mp3"), *d.glob("seg_*.mp4"), *d.glob("broll_*.mp4"), video, d / "visuals.txt"]:
        Path(p).unlink(missing_ok=True)

    hashtags = list(script.hashtags)
    if data.get("disclose", True) and "#ad" not in [h.lower() for h in hashtags]:
        hashtags.insert(0, "#ad")
    return {
        "title": script.title,
        "video": file_url(final),
        "thumbnail": file_url(thumb),
        "duration": round(total, 1),
        "caption": script.caption,
        "hashtags": hashtags,
        "script": [s.model_dump() for s in scenes],
        "product": {k: product[k] for k in ("name", "url", "price")},
    }
