FROM node:20-slim AS frontend-builder

WORKDIR /frontend

# Copy dependency manifests first for better layer caching.
COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim AS app

ENV PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  PIP_DISABLE_PIP_VERSION_CHECK=1 \
  PIP_NO_CACHE_DIR=1 \
  PORT=8080 \
  TZ=Asia/Shanghai

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential tzdata gosu && \
  rm -rf /var/lib/apt/lists/*

# Copy project sources and install Python dependencies from pyproject.
COPY . /app
RUN pip install --no-cache-dir . && \
  pip install --no-cache-dir psycopg2-binary

# Install tgcrypto only on amd64 to avoid arm64 build failures.
ARG TARGETPLATFORM
RUN if [ "${TARGETPLATFORM:-}" = "linux/amd64" ] || [ "$(uname -m)" = "x86_64" ]; then \
    pip install --no-cache-dir tgcrypto; \
  else \
    echo "Skipping tgcrypto on ${TARGETPLATFORM:-unknown}"; \
  fi

# Frontend static files served from /web.
RUN mkdir -p /web
COPY --from=frontend-builder /frontend/out /web

# Data dir (mapped via volume).
RUN mkdir -p /data

# Non-root user.
ARG APP_UID=10001
ARG APP_GID=10001
RUN groupadd -r -g ${APP_GID} app && \
  useradd -r -u ${APP_UID} -g app -d /app -s /usr/sbin/nologin app && \
  chown -R app:app /data

# Runtime entrypoint auto-adapts to mounted /data ownership.
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080

# Healthcheck uses the PORT env var.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.getenv(\"PORT\", \"8080\")}/healthz').read()"

# Start with env-driven PORT (Zeabur sets this automatically).
ENTRYPOINT ["/entrypoint.sh"]
