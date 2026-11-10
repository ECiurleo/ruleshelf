# syntax=docker/dockerfile:1

# ---- frontend -------------------------------------------------------------
FROM --platform=$BUILDPLATFORM node:26-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- runtime --------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    RULESHELF_DATA_DIR=/data \
    PUID=1000 \
    PGID=1000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=frontend /build/dist ./static
COPY docker-entrypoint.sh /usr/local/bin/ruleshelf-entrypoint

RUN chmod +x /usr/local/bin/ruleshelf-entrypoint \
    && useradd --create-home --uid 1000 ruleshelf \
    && mkdir -p /data \
    && chown -R ruleshelf:ruleshelf /data /app

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

ENTRYPOINT ["/usr/local/bin/ruleshelf-entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
