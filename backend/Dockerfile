FROM denoland/deno:bin-2.5.6 AS deno

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg fonts-dejavu-core fontconfig curl ca-certificates libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp needs a JavaScript runtime for YouTube.
COPY --from=deno /deno /usr/local/bin/deno

# Bold display fonts for subtitles and thumbnails (SIL Open Font License).
RUN mkdir -p /usr/share/fonts/viral \
    && curl -fsSL -o /usr/share/fonts/viral/Anton-Regular.ttf \
       https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf \
    && curl -fsSL -o /usr/share/fonts/viral/Bangers-Regular.ttf \
       https://github.com/google/fonts/raw/main/ofl/bangers/Bangers-Regular.ttf \
    ; fc-cache -f

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app

ENV DATA_DIR=/data
VOLUME /data
EXPOSE 8000
