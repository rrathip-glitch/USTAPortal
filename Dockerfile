# Railway-ready image. Python 3.11 slim base + playwright install-deps gives
# us the Chromium system libs without dragging in the MS Playwright image's
# Python 3.10 (which is incompatible with this project's requires-python).

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATABASE_URL=sqlite:////data/db/usta.db \
    RAW_CACHE_DIR=/data/raw \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

# Minimum runtime tooling. Playwright fetches the rest of its deps
# via `playwright install --with-deps` below.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    ca-certificates curl wget git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so cold rebuilds stay cheap. pip install -e .
# pulls playwright as a transitive dep; we then invoke `playwright install`
# to fetch the Chromium binary + every shared library it needs.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --upgrade pip \
 && pip install -e . \
 && python -m playwright install --with-deps chromium

# Now copy the rest of the repo (templates, scripts, fixtures, docs).
COPY . .

# Pre-create the /data layout so init-db has somewhere to write on
# first boot. Railway attaches its persistent storage at /data via
# the dashboard; no Docker-level directive is needed (or allowed).
RUN mkdir -p /data/raw /data/db /data/exports

EXPOSE 8000

# Default web command. Railway's startCommand in railway.json wins
# when set; the Procfile worker entry overrides CMD for the worker
# service.
CMD ["sh", "-c", "python -m src.cli.main init-db && uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
