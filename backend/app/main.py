import base64
import secrets
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

from . import db, publish, security
from .config import job_dir, settings, uploads_dir
from .tasks import enqueue

app = FastAPI(title="Viral", docs_url="/api/docs", openapi_url="/api/openapi.json")

ALLOWED_UPLOADS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".jpg", ".jpeg", ".png", ".webp", ".mp3", ".wav", ".m4a"}


# ---------------------------------------------------------------- auth
@app.middleware("http")
async def basic_auth(request: Request, call_next):
    path = request.url.path
    if not settings.APP_PASSWORD or path == "/api/health":
        return await call_next(request)
    if path.startswith("/files/") and security.verify(path[len("/files/"):], request.query_params.get("sig")):
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.startswith("Basic "):
        try:
            _, _, pw = base64.b64decode(header[6:]).decode().partition(":")
            if secrets.compare_digest(pw, settings.APP_PASSWORD):
                return await call_next(request)
        except Exception:
            pass
    return JSONResponse({"detail": "Unauthorized"}, status_code=401, headers={"WWW-Authenticate": 'Basic realm="Viral"'})


# ---------------------------------------------------------------- helpers
def _data_rel(path: str | None) -> str | None:
    """Validate a DATA_DIR-relative path supplied by the client."""
    if not path:
        return None
    path = path.removeprefix("/files/")
    full = (settings.DATA_DIR / path).resolve()
    if not full.is_relative_to(settings.DATA_DIR.resolve()) or not full.is_file():
        raise HTTPException(400, f"File not found: {path}")
    return path


def _new_job(kind: str, data: dict, title: str) -> dict:
    job_id = db.create_job(kind, data, title)
    enqueue(job_id)
    return db.get_job(job_id)


# ---------------------------------------------------------------- system
@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/status")
def status():
    return {
        "llm": bool(settings.ANTHROPIC_API_KEY),
        "model": settings.ANTHROPIC_MODEL,
        "tts": settings.TTS_PROVIDER,
        "tts_ready": settings.TTS_PROVIDER == "kokoro" or bool(settings.ELEVENLABS_API_KEY),
        "avatar": settings.AVATAR_PROVIDER,
        "broll": bool(settings.PEXELS_API_KEY),
        "whisper": settings.WHISPER_MODEL,
        "public_base_url": settings.PUBLIC_BASE_URL,
        "publish": publish.status(),
    }


@app.post("/api/uploads")
async def upload(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_UPLOADS:
        raise HTTPException(400, f"Unsupported file type {ext or '(none)'}")
    dest = uploads_dir() / f"{uuid.uuid4().hex[:12]}{ext}"
    with open(dest, "wb") as fh:
        shutil.copyfileobj(file.file, fh, length=4 * 1024 * 1024)
    rel = dest.relative_to(settings.DATA_DIR).as_posix()
    if file.filename:
        db.kv_set(f"upload_name:{rel}", Path(file.filename).stem[:120])
    return {"path": rel, "url": f"/files/{rel}", "name": file.filename}


def _require_llm():
    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(400, "ANTHROPIC_API_KEY is not set — add it to .env and run `docker compose up -d`.")


# ---------------------------------------------------------------- jobs
class ClipsRequest(BaseModel):
    url: HttpUrl | None = None
    upload_path: str | None = None
    num_clips: int = Field(5, ge=1, le=20)
    min_seconds: int = Field(20, ge=5, le=180)
    max_seconds: int = Field(60, ge=10, le=180)
    layout: str = Field("face", pattern="^(face|center|blur)$")
    caption_style: str = Field("bold", pattern="^(bold|clean|comic|karaoke|none)$")
    language: str | None = None


@app.post("/api/clips")
def create_clips(req: ClipsRequest):
    if not req.url and not req.upload_path:
        raise HTTPException(400, "Provide a YouTube URL or upload a video.")
    if req.min_seconds >= req.max_seconds:
        raise HTTPException(400, "Minimum length must be shorter than maximum length.")
    _require_llm()
    data = req.model_dump(mode="json")
    data["upload_path"] = _data_rel(req.upload_path)
    if data["upload_path"]:
        data["title"] = db.kv_get(f"upload_name:{data['upload_path']}") or Path(data["upload_path"]).stem
    return _new_job("clips", data, str(req.url or data.get("title")))


class UGCRequest(BaseModel):
    product_url: HttpUrl
    style: str = "testimonial"
    duration: int = Field(30, ge=10, le=90)
    tone: str | None = None
    audience: str | None = None
    notes: str | None = None
    voice: str | None = None
    avatar_path: str | None = None
    music_path: str | None = None
    caption_style: str = Field("bold", pattern="^(bold|clean|comic|karaoke|none)$")
    disclose: bool = True


@app.post("/api/ugc")
def create_ugc(req: UGCRequest):
    _require_llm()
    data = req.model_dump(mode="json")
    data["avatar_path"] = _data_rel(req.avatar_path)
    data["music_path"] = _data_rel(req.music_path)
    return _new_job("ugc", data, str(req.product_url))


class PublishRequest(BaseModel):
    file: str
    platforms: list[str]
    title: str = ""
    caption: str = ""
    tags: list[str] = []
    privacy: str = Field("public", pattern="^(public|unlisted|private)$")


@app.post("/api/publish")
def create_publish(req: PublishRequest):
    if not req.platforms:
        raise HTTPException(400, "Pick at least one platform.")
    data = req.model_dump()
    data["file"] = _data_rel(req.file)
    return _new_job("publish", data, f"Publish → {', '.join(req.platforms)}")


@app.get("/api/jobs")
def jobs(kind: str | None = None, limit: int = 100):
    return db.list_jobs(limit, kind)


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    j = db.get_job(job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    return j


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    if not db.get_job(job_id):
        raise HTTPException(404, "Job not found")
    db.delete_job(job_id)
    shutil.rmtree(settings.DATA_DIR / "jobs" / job_id, ignore_errors=True)
    return {"ok": True}


# ---------------------------------------------------------------- YouTube Studio
class TitlesRequest(BaseModel):
    topic: str = Field(min_length=3)
    summary: str | None = None
    niche: str | None = None
    audience: str | None = None
    format: str | None = None


@app.post("/api/studio/ideas")
def studio_ideas(req: TitlesRequest):
    from .pipelines import studio

    try:
        return studio.ideas(req.model_dump())
    except RuntimeError as e:
        raise HTTPException(400, str(e))


class ThumbnailRequest(BaseModel):
    background_path: str
    text: str = Field(min_length=1, max_length=60)
    highlight_word: str = ""
    accent_color: str = Field("#FFE500", pattern="^#[0-9A-Fa-f]{6}$")
    frame_at: float | None = None  # if the background is a video, grab this second


@app.post("/api/studio/thumbnails")
def studio_thumbnails(req: ThumbnailRequest):
    from .media import ffmpeg
    from .pipelines import studio

    bg = settings.DATA_DIR / _data_rel(req.background_path)
    if bg.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}:
        frame = settings.DATA_DIR / "studio" / f"frame_{uuid.uuid4().hex[:8]}.jpg"
        frame.parent.mkdir(exist_ok=True)
        bg = ffmpeg.thumbnail(bg, frame, at=req.frame_at or 1.0)
    return {"images": studio.thumbnails(bg, req.text, req.highlight_word, req.accent_color)}


# ---------------------------------------------------------------- OAuth
@app.get("/api/oauth/youtube/start")
def youtube_start():
    from .publish import youtube

    try:
        return RedirectResponse(youtube.auth_url())
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@app.get("/api/oauth/youtube/callback")
def youtube_callback(code: str = "", state: str = "", error: str = ""):
    from .publish import youtube

    if error:
        return RedirectResponse(f"/#settings?error={error}")
    try:
        youtube.finish_auth(code, state)
    except Exception as e:
        return HTMLResponse(f"<p>YouTube connection failed: {e}</p><p><a href='/#settings'>Back</a></p>", 400)
    return RedirectResponse("/#settings?connected=youtube")


@app.post("/api/oauth/youtube/disconnect")
def youtube_disconnect():
    db.kv_set("youtube_refresh_token", None)
    return {"ok": True}


# ---------------------------------------------------------------- files + frontend
@app.get("/files/{path:path}")
def files(path: str):
    full = (settings.DATA_DIR / path).resolve()
    if not full.is_relative_to(settings.DATA_DIR.resolve()) or not full.is_file() or full.suffix == ".db":
        raise HTTPException(404)
    return FileResponse(full)


if settings.FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=settings.FRONTEND_DIR, html=True), name="frontend")
