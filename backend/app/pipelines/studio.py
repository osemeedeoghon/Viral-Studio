"""YouTube Studio: viral title ideas + thumbnail concepts (Claude) and thumbnail rendering (Pillow)."""
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from pydantic import BaseModel, Field

from .. import llm
from ..config import file_url, settings

TW, TH = 1280, 720


class TitleIdea(BaseModel):
    title: str = Field(description="Under 70 characters")
    angle: str = Field(description="The psychological trigger used, e.g. curiosity gap, stakes, contrarian")
    score: int = Field(description="0-100 predicted click-through strength")


class ThumbnailIdea(BaseModel):
    text: str = Field(description="Thumbnail text, 1-4 words, must complement (not repeat) the title")
    highlight_word: str = Field(description="The one word from `text` to color as the accent")
    visual: str = Field(description="What the image should show: subject, expression, props, composition")
    accent_color: str = Field(description="Hex color for the accent, e.g. #FFE500")


class StudioIdeas(BaseModel):
    titles: list[TitleIdea]
    thumbnails: list[ThumbnailIdea]
    description: str = Field(description="SEO-friendly YouTube description, 2 short paragraphs + 3 hashtags")
    tags: list[str]


SYSTEM = """You are a YouTube strategist who has packaged videos for top creators. You know packaging (title + thumbnail)
decides most of a video's views. Good titles create a curiosity gap or clear stakes, are specific, short and honest
(no clickbait that the video can't pay off). The thumbnail text never repeats the title: it adds a second hook.
Write for the given niche and audience."""


def ideas(data: dict) -> dict:
    prompt = (
        f"Video topic / working title: {data.get('topic', '')}\n"
        f"What happens in the video: {data.get('summary') or 'not provided'}\n"
        f"Niche: {data.get('niche') or 'infer'}\nAudience: {data.get('audience') or 'infer'}\n"
        f"Format: {data.get('format') or 'long-form YouTube video'}\n\n"
        "Give 10 title ideas sorted by score (highest first) and 4 thumbnail concepts."
    )
    return llm.structured(SYSTEM, prompt, StudioIdeas).model_dump()


def _font(size: int, name: str = "Anton-Regular.ttf"):
    for path in (Path(settings.FONTS_DIR) / name, Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")):
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _cover(im: Image.Image, w: int, h: int, focus_x: float = 0.5) -> Image.Image:
    scale = max(w / im.width, h / im.height)
    im = im.resize((int(im.width * scale) + 1, int(im.height * scale) + 1), Image.LANCZOS)
    x = int((im.width - w) * focus_x)
    y = (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def _fit_lines(draw, words: list[str], max_w: int, max_h: int) -> tuple[list[list[str]], ImageFont.FreeTypeFont]:
    for size in range(220, 60, -8):
        font = _font(size)
        lines, cur = [], []
        for word in words:
            trial = cur + [word]
            if cur and draw.textlength(" ".join(trial), font=font) > max_w:
                lines.append(cur)
                cur = [word]
            else:
                cur = trial
        lines.append(cur)
        line_h = font.getbbox("Ag")[3] * 1.05
        if len(lines) <= 3 and len(lines) * line_h <= max_h and all(
                draw.textlength(" ".join(l), font=font) <= max_w for l in lines):
            return lines, font
    return [words], _font(60)


def render_thumbnail(background: Path, text: str, highlight: str = "", accent: str = "#FFE500",
                     layout: str = "left", out_dir: Path | None = None) -> Path:
    out_dir = out_dir or (settings.DATA_DIR / "studio")
    out_dir.mkdir(parents=True, exist_ok=True)
    focus = {"left": 0.75, "right": 0.25}.get(layout, 0.5)
    im = _cover(Image.open(background).convert("RGB"), TW, TH, focus)
    im = ImageEnhance.Contrast(im).enhance(1.15)
    im = ImageEnhance.Color(im).enhance(1.25)

    # Darken the text side so words pop.
    shade = Image.new("L", (TW, TH), 0)
    sd = ImageDraw.Draw(shade)
    for i in range(TW if layout != "bottom" else TH):
        if layout == "left":
            a = max(0, 200 - int(i / (TW * 0.6) * 200))
            sd.line([(i, 0), (i, TH)], fill=a)
        elif layout == "right":
            a = max(0, 200 - int(i / (TW * 0.6) * 200))
            sd.line([(TW - i, 0), (TW - i, TH)], fill=a)
        else:
            a = max(0, 210 - int(i / (TH * 0.55) * 210))
            sd.line([(0, TH - i), (TW, TH - i)], fill=a)
    im.paste((0, 0, 0), (0, 0), shade)

    draw = ImageDraw.Draw(im)
    words = text.upper().split()
    hl = {w.strip(".,!?").upper() for w in highlight.split()} if highlight else set()
    area_w = int(TW * 0.52) if layout in ("left", "right") else int(TW * 0.9)
    area_h = int(TH * 0.75) if layout in ("left", "right") else int(TH * 0.42)
    lines, font = _fit_lines(draw, words, area_w, area_h)
    line_h = int(font.getbbox("Ag")[3] * 1.05)
    block_h = line_h * len(lines)
    y = (TH - block_h) // 2 if layout != "bottom" else TH - block_h - 40
    stroke = max(4, font.size // 18)

    for line in lines:
        line_w = draw.textlength(" ".join(line), font=font)
        if layout == "left":
            x = 60
        elif layout == "right":
            x = TW - 60 - line_w
        else:
            x = (TW - line_w) / 2
        for word in line:
            color = accent if word.strip(".,!?") in hl else "#FFFFFF"
            # drop shadow, then stroked text
            draw.text((x + 6, y + 8), word, font=font, fill=(0, 0, 0))
            draw.text((x, y), word, font=font, fill=color, stroke_width=stroke, stroke_fill="#000000")
            x += draw.textlength(word + " ", font=font)
        y += line_h

    im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=60))
    out = out_dir / f"thumb_{uuid.uuid4().hex[:8]}_{layout}.jpg"
    im.save(out, quality=93)
    return out


def thumbnails(background: Path, text: str, highlight: str, accent: str) -> list[str]:
    return [file_url(render_thumbnail(background, text, highlight, accent, layout))
            for layout in ("left", "right", "bottom")]
