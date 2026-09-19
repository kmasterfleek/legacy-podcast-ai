FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    LEGACY_STUDIO_DATA=/data LEGACY_WEB_DIR=/app/apps/web LEGACY_ENV=production
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[studio]"
COPY apps ./apps
COPY transcripts ./transcripts
RUN useradd --uid 10001 --create-home studio && mkdir /data && chown studio:studio /data
USER studio
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
CMD ["legacy-studio", "serve", "--host", "0.0.0.0"]
