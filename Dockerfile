# Railway-ready image. Python 3.11 slim base; no Playwright / Chromium
# install (Clubspark is deferred — ADR-001 — so the runtime data plane
# uses only httpx + lxml, no browser needed). Skipping the Chromium
# bundle keeps the image tiny (~150MB vs 1GB) and the cold-start fast
# so Railway's healthcheck doesn't race the boot.

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATABASE_URL=sqlite:////data/db/usta.db \
    RAW_CACHE_DIR=/data/raw \
    PYTHONFAULTHANDLER=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so cold rebuilds stay cheap.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --upgrade pip \
 && pip install -e . --no-deps \
 && pip install \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.32" \
    "jinja2>=3.1" \
    "httpx>=0.27" \
    "pydantic>=2.9" \
    "pydantic-settings>=2.6" \
    "sqlalchemy>=2.0" \
    "aiosqlite>=0.20" \
    "loguru>=0.7" \
    "typer>=0.13" \
    "tenacity>=9.0" \
    "python-dateutil>=2.9" \
    "lxml>=5.3" \
    "beautifulsoup4>=4.12"

# Now copy the rest of the repo (templates, scripts, fixtures, docs).
COPY . .

# Pre-create the /data layout so init-db has somewhere to write. Even
# without a Railway volume attached, these directories exist in the
# image filesystem for first boot.
RUN mkdir -p /data/raw /data/db /data/exports

EXPOSE 8000

# Bind uvicorn to ${PORT} immediately — Railway probes /health the
# moment the port opens, and /health is a zero-IO 200 in src/main.py
# so the healthcheck wins the race.
CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
