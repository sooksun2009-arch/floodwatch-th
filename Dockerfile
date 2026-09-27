# Single-service image: Node builds the SPA, Python serves both the API and the
# built files. One container, one port, one deploy.

# ---------------------------------------------------------------- stage 1: SPA
FROM node:22-alpine AS frontend

WORKDIR /build
# Copy manifests first so the dependency layer is cached across source edits.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install

COPY frontend/ ./
# Build-time config. Override with --build-arg to use your own tile provider.
ARG VITE_MAP_STYLE=""
ENV VITE_MAP_STYLE=$VITE_MAP_STYLE
RUN npm run build

# ---------------------------------------------------------------- stage 2: API
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    STATIC_DIR=/app/static \
    UPLOAD_DIR=/data/uploads

WORKDIR /app

# curl is used by the container healthcheck below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=frontend /build/dist ./static

# Run as a non-root user; /data is a mount point for the uploads volume.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/uploads \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${PORT:-8000}/api/health || exit 1

# Railway and similar platforms inject $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
