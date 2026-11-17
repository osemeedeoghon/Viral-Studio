"""Speaker-aware 9:16 reframing: find faces, then build an ffmpeg crop that follows the speaker
like a camera operator would (holds steady, re-frames only when the subject moves)."""
from pathlib import Path

from .ffmpeg import COVER, H, W


def face_track(src: Path, start: float, end: float, every: float = 0.5) -> list[tuple[float, float | None]]:
    """Return [(t_relative, face_center_x as 0..1 of frame width or None)]."""
    import cv2

    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cap = cv2.VideoCapture(str(src))
    track = []
    t = 0.0
    try:
        while start + t < end:
            cap.set(cv2.CAP_PROP_POS_MSEC, (start + t) * 1000)
            ok, frame = cap.read()
            if not ok:
                break
            h, w = frame.shape[:2]
            scale = 640 / w if w > 640 else 1.0
            small = cv2.resize(frame, (int(w * scale), int(h * scale))) if scale != 1.0 else frame
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(36, 36))
            if len(faces):
                x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
                track.append((t, (x + fw / 2) / small.shape[1]))
            else:
                track.append((t, None))
            t += every
    finally:
        cap.release()
    return track


def _fill_and_smooth(track: list[tuple[float, float | None]]) -> list[tuple[float, float]]:
    known = [(t, c) for t, c in track if c is not None]
    if not known:
        return []
    filled = []
    for t, c in track:
        if c is None:
            # nearest known sample
            c = min(known, key=lambda k: abs(k[0] - t))[1]
        filled.append((t, c))
    smoothed = []
    for i, (t, _) in enumerate(filled):
        window = sorted(c for _, c in filled[max(0, i - 2): i + 3])
        smoothed.append((t, window[len(window) // 2]))  # rolling median
    return smoothed


def reframe_filter(src_w: int, src_h: int, track: list[tuple[float, float | None]] | None, layout: str = "face") -> str:
    """ffmpeg -vf chain that turns the source into a W x H (9:16) frame."""
    if src_w / max(src_h, 1) <= 9 / 16 + 0.01:
        return COVER  # already vertical

    if layout == "blur":
        return (
            f"split[a][b];[a]{COVER},boxblur=24:2,eq=brightness=-0.08[bg];"
            f"[b]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1"
        )

    crop_w = int(src_h * 9 / 16) // 2 * 2
    max_x = src_w - crop_w
    centers = _fill_and_smooth(track or []) if layout == "face" else []

    if not centers:
        x_expr = str(max_x // 2)
    else:
        # Camera-operator keyframes: move only on a significant, sustained shift.
        keys = [(0.0, centers[0][1])]
        for t, c in centers[1:]:
            if abs(c - keys[-1][1]) > 0.07 and t - keys[-1][0] >= 1.5:
                keys.append((t, c))
        keys = keys[:60]

        def px(c: float) -> int:
            return int(min(max(c * src_w - crop_w / 2, 0), max_x))

        x_expr = str(px(keys[-1][1]))
        for (t_next, _), (_, c) in reversed(list(zip(keys[1:], keys[:-1]))):
            x_expr = f"if(lt(t,{t_next:.2f}),{px(c)},{x_expr})"

    return f"crop={crop_w}:{src_h}:'{x_expr}':0,scale={W}:{H},setsar=1"
