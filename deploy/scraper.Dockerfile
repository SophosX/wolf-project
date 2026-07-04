# Wolf Radar — Scraper-Container (Python + yt-dlp/ffmpeg + supercronic)
# Zeitplan siehe deploy/crontab: alle 4 h YouTube+TikTok, täglich 05:30 UTC
# Instagram + Transkript-Backfill. Schreibt ins gemeinsame daten-Volume.

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 TZ=UTC

# ffmpeg/ffprobe stabil aus apt; curl für den supercronic-Download
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp/gallery-dl bewusst via pip (Debian-Pakete sind für YouTube/TikTok zu alt);
# beim monatlichen `docker compose build --no-cache scraper` kommen sie frisch.
RUN pip install --no-cache-dir requests yt-dlp gallery-dl

# supercronic: Container-Cron, reicht ENV an Jobs durch, loggt nach stdout
ARG SUPERCRONIC_VERSION=v0.2.34
ARG TARGETARCH=amd64
RUN curl -fsSL -o /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH}" \
    && chmod +x /usr/local/bin/supercronic

WORKDIR /app
COPY scraper /app/scraper
COPY deploy/crontab /app/crontab
RUN mkdir -p /app/daten

CMD ["supercronic", "-passthrough-logs", "/app/crontab"]
