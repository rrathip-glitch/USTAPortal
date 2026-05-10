# Fallback Dockerfile for Railway, used if Nixpacks proves insufficient for
# Playwright system deps. Built on Microsoft's official Playwright Python
# image, which already has Chromium and every system library it needs.

FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e .

COPY . .

RUN mkdir -p /data/raw /data/db /data/exports
VOLUME ["/data"]

EXPOSE 8000

CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
