# Railway-ready image. Built on Microsoft's official Playwright Python image
# so Chromium and all its system libs are pre-installed (the Nixpacks recipe
# kept breaking on xorg attribute renames in current nixpkgs).

FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATABASE_URL=sqlite:////data/db/usta.db \
    RAW_CACHE_DIR=/data/raw

WORKDIR /app

# Install deps first so cold rebuilds stay cheap.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --upgrade pip && pip install -e .

# Now copy the rest of the repo (templates, scripts, fixtures, docs).
COPY . .

# Persistent volume layout. Railway-attached volume will mount over /data;
# the directories must exist inside the image for first-boot init-db.
RUN mkdir -p /data/raw /data/db /data/exports
VOLUME ["/data"]

EXPOSE 8000

# Default to the web process. Railway's `startCommand` (in railway.json)
# overrides this and prepends `python -m src.cli.main init-db` so the
# schema exists before uvicorn binds. The worker service overrides CMD
# via Railway settings or via the Procfile entry below.
CMD ["sh", "-c", "python -m src.cli.main init-db && uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
