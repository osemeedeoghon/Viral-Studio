"""Stylized, word-by-word highlighted subtitles rendered as an ASS file (burned in by ffmpeg/libass)."""
from pathlib import Path

from ..config import settings

PRESETS = {
    # Big uppercase words, current word pops in yellow.
    "bold": dict(font=settings.CAPTION_FONT, size=104, bold=0, color="#FFFFFF", highlight="#FFE500",
                 outline=7, shadow=2, upper=True, words=3, scale=112, margin_v=560),
    # Calm sentence-case captions with a green active word.
    "clean": dict(font="DejaVu Sans", size=66, bold=1, color="#FFFFFF", highlight="#4ADE80",
                  outline=4, shadow=1, upper=False, words=5, scale=100, margin_v=480),
    # Playful comic font, two words at a time, red highlight.
    "comic": dict(font="Bangers", size=124, bold=0, color="#FFFFFF", highlight="#FF4D4D",
                  outline=8, shadow=3, upper=True, words=2, scale=118, margin_v=600),
    # Karaoke: whole line visible, spoken words fill in.
    "karaoke": dict(font=settings.CAPTION_FONT, size=92, bold=0, color="#9CA3AF", highlight="#FFFFFF",
                    outline=6, shadow=2, upper=True, words=4, scale=100, margin_v=560),
}


def ass_color(hex_color: str, alpha: int = 0) -> str:
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ts(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def chunk_words(words: list[dict], max_words: int) -> list[list[dict]]:
    chunks, cur = [], []
    for i, w in enumerate(words):
        if cur and (len(cur) >= max_words or w["start"] - cur[-1]["end"] > 0.6):
            chunks.append(cur)
            cur = []
        cur.append(w)
        if w["word"][-1:] in ".!?" and i < len(words) - 1:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def build_ass(words: list[dict], style: str = "bold", overlays: list[tuple[float, float, str]] | None = None,
              width: int = 1080, height: int = 1920) -> str:
    p = PRESETS.get(style, PRESETS["bold"])
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{p['font']},{p['size']},{ass_color(p['color'])},{ass_color(p['highlight'])},&H00000000,&H64000000,{-1 if p['bold'] else 0},0,0,0,100,100,1,0,1,{p['outline']},{p['shadow']},2,80,80,{p['margin_v']},1
Style: Title,DejaVu Sans,58,&H00111111,&H00111111,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,18,0,8,90,90,250,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    hl = ass_color(p["highlight"])
    base = ass_color(p["color"])
    words = [dict(w, word=(w["word"].upper() if p["upper"] else w["word"])) for w in words if w["word"].strip()]
    chunks = chunk_words(words, p["words"]) if style != "none" else []

    for ci, chunk in enumerate(chunks):
        next_start = chunks[ci + 1][0]["start"] if ci + 1 < len(chunks) else None
        chunk_end = chunk[-1]["end"]
        # Hold the line through natural pauses instead of blinking off between sentences.
        if next_start is not None and next_start - chunk_end < 0.8:
            chunk_end = next_start
        else:
            chunk_end = chunk_end + 0.4 if next_start is None else min(chunk_end + 0.4, next_start)
        for wi, w in enumerate(chunk):
            start = w["start"]
            end = chunk[wi + 1]["start"] if wi + 1 < len(chunk) else chunk_end
            if end <= start:
                continue
            parts = []
            for wj, other in enumerate(chunk):
                txt = _escape(other["word"])
                if wj == wi:
                    parts.append(f"{{\\c{hl}\\fscx{p['scale']}\\fscy{p['scale']}}}{txt}{{\\c{base}\\fscx100\\fscy100}}")
                elif style == "karaoke" and wj < wi:
                    parts.append(f"{{\\c{hl}}}{txt}{{\\c{base}}}")
                else:
                    parts.append(txt)
            pop = "{\\fad(40,0)}" if wi == 0 else ""
            lines.append(f"Dialogue: 0,{ts(start)},{ts(end)},Caption,,0,0,0,,{pop}{' '.join(parts)}")

    for start, end, text in overlays or []:
        if text and text.strip() and end > start:
            lines.append(f"Dialogue: 1,{ts(start)},{ts(end)},Title,,0,0,0,,{{\\fad(120,120)}}{_escape(text.strip())}")

    return header + "\n".join(lines) + "\n"


def write_ass(path: Path, words: list[dict], style: str = "bold", overlays=None) -> Path:
    path.write_text(build_ass(words, style, overlays), encoding="utf-8")
    return path
