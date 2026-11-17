# Viral Studio

Self-hosted short-form video platform. One dashboard, four tools, no watermarks:

| Tool | What it does |
|---|---|
| **Clip Generator** | YouTube URL or upload → transcribes it (local Whisper), Claude picks the most engaging standalone moments, each one gets reframed to 9:16 around the speaker and has animated word-by-word subtitles burned in. |
| **UGC Ad Creator** | Product URL → scrapes the page (name, description, price, images) → Claude writes a UGC-style script → voiceover → presenter + stock b-roll + product shots → captioned 9:16 ad. |
| **YouTube Studio** | 10 scored title ideas, thumbnail concepts, an SEO description and tags, plus a thumbnail renderer (1280×720, 3 layouts) from any image or video frame. |
| **Library & Publish** | Every finished video. Download it, or post it directly to YouTube Shorts, TikTok and Instagram Reels. |

## Quick start

```bash
cp .env.example .env        # then set ANTHROPIC_API_KEY, APP_PASSWORD, SECRET_KEY
docker compose up -d --build
open http://localhost:8000  # user: admin, password: APP_PASSWORD
```

The first clip job downloads the Whisper model (~500 MB for `small`) into the data volume.
Add a [Pexels API key](https://www.pexels.com/api/) (free) for b-roll.

**Server requirements:** 4+ CPU cores and 8 GB RAM work. Transcribing a 1-hour video on CPU takes roughly
10–20 minutes with `small`. An NVIDIA GPU (`WHISPER_DEVICE=cuda`, uncomment the GPU block in
`docker-compose.yml`) makes it many times faster. Run more workers with `docker compose up -d --scale worker=3`.

## Architecture

```
browser ──► api (FastAPI + dashboard) ──► redis queue ──► worker(s) (ffmpeg, Whisper, OpenCV)
                    │                                          │
                    └──────────── /data volume (SQLite + media) ┘        kokoro (local TTS)
```

- `backend/app/pipelines/` has `clips.py`, `ugc.py` and `studio.py`, one file per tool.
- `backend/app/providers/` has the swappable services: TTS, presenter/avatar, b-roll and the product scraper.
- `backend/app/publish/` has the YouTube, TikTok and Instagram uploaders.
- `backend/app/media/` has the ffmpeg helpers, captions (ASS/libass), speaker-tracking crop and transcription.
- `frontend/` is a static dashboard with no build step.

## The AI presenter: read this

How realistic the talking person looks depends entirely on `AVATAR_PROVIDER`:

| Provider | Lip-sync | Cost | Notes |
|---|---|---|---|
| `photo` (default) | ✗ | free | Animates your presenter photo with a handheld-camera push-in. Works offline, but the mouth doesn't move, so it reads as a voiceover over a photo. |
| `did` | ✓ | paid API | D-ID talking-head API. D-ID downloads the photo and audio from this server, so `PUBLIC_BASE_URL` must be reachable from the internet. |
| `lipsync_http` | ✓ | free, needs GPU | Your own lip-sync model (SadTalker, LatentSync, MuseTalk…) behind a small HTTP wrapper: `POST {LIPSYNC_URL}` with multipart fields `image` and `audio`, returning `video/mp4` bytes. |

For the most realistic UGC, start from a real creator photo you have the rights to, or a high-quality
AI-generated face, and use `did` or a GPU `lipsync_http` server.

**Disclosure:** the creator adds `#ad` to captions by default. Most platforms and the FTC also require
paid or AI-generated testimonials to be disclosed. Don't present an AI presenter as a real customer,
and only use photos of people who have consented.

## Publishing setup

Each platform needs a developer app. This is a platform requirement, not something the code can skip:

- **YouTube:** in Google Cloud, enable *YouTube Data API v3* and create an OAuth *Web application* client
  with redirect URI `{PUBLIC_BASE_URL}/api/oauth/youtube/callback`. Set the ID and secret in `.env`, then
  click **Settings → Connect YouTube**. Uploads from apps that haven't been verified may be locked to private
  until Google audits the app.
- **TikTok:** create an app with the *Content Posting API* (`video.publish` scope) and put a user access token
  in `TIKTOK_ACCESS_TOKEN`. Apps that haven't been audited can only post with `SELF_ONLY` (private) visibility.
- **Instagram:** you need an Instagram Business or Creator account linked to a Facebook Page, plus a long-lived
  token with `instagram_content_publish`. Instagram pulls the video from a signed URL on this server, so
  `PUBLIC_BASE_URL` must be public https.

Put the stack behind a reverse proxy with TLS (Caddy, Traefik or nginx) on a domain for anything beyond local use.

## Notes

- Only clip videos you own or have permission to repurpose. Downloading other creators' videos may violate
  YouTube's Terms of Service and copyright law.
- yt-dlp breaks when YouTube changes things. If downloads fail, rebuild to pick up the latest version:
  `docker compose build --no-cache api worker`.
- Caption styles live in `backend/app/media/captions.py` (`PRESETS`). Fonts are Anton and Bangers (OFL),
  installed at build time.
- API docs: `http://localhost:8000/api/docs`.
