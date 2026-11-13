# SPDX-License-Identifier: AGPL-3.0-or-later
# Build from the repository root:
#   docker build -f docker/Dockerfile .

ARG NODE_VERSION=24
ARG PNPM_VERSION=12.10.1
ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.13.6

# --- Web page -------------------------------------------------------------------------------
# Static files only, so it is built on the platform of the build machine (no emulation).
FROM --platform=$BUILDPLATFORM node:${NODE_VERSION}-slim AS frontend
ARG PNPM_VERSION
RUN npm install --global pnpm@${PNPM_VERSION}
WORKDIR /src/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml frontend/.npmrc ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# --- Python ---------------------------------------------------------------------------------

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:${PYTHON_VERSION}-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/venv
WORKDIR /src
# Dependencies first, so that code changes do not invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY README.md ./
COPY src/ src/
RUN uv sync --frozen --no-dev --no-editable

FROM python:${PYTHON_VERSION}-slim
# Debian fixes reach the image with every build, even before the base image is rebuilt.
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/*
COPY --from=build /app/venv /app/venv
COPY --from=frontend /src/frontend/build /app/static
COPY LICENSE THIRD_PARTY_NOTICES.md /app/

# The container runs as the user given in compose.yaml (PUID:PGID), so that the media server can
# read what it writes; nothing here depends on a particular user.
ENV PATH=/app/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SHOWRUNNER_OUTPUT_DIR=/output \
    SHOWRUNNER_STATIC_DIR=/app/static
WORKDIR /app
USER 1000:1000
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4)"]
ENTRYPOINT ["showrunner"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]
