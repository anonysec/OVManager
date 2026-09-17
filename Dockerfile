# Stage 1: Build frontend
FROM node:22-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Builder — resolve locked Python deps into /app/.venv
FROM python:3.12-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1

WORKDIR /app

# gcc is builder-only: it never reaches the runtime image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy package metadata and Python sources before installing the project.
COPY pyproject.toml uv.lock* README.md ./
COPY backend/ ./backend/
COPY bot/ ./bot/
COPY main.py ./

# Install uv then sync from the lock file for fully reproducible builds.
# --frozen fails closed if pyproject.toml and uv.lock are out of sync.
RUN pip install --no-cache-dir uv \
    && uv sync --frozen

# Stage 3: Runtime — ships only the venv, sources and frontend build
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

# Create non-root user
RUN useradd -m -u 1000 appuser

# Copy the pre-built venv (no uv, no compiler) and the sources.
COPY --from=builder /app/.venv ./.venv
COPY backend/ ./backend/
COPY bot/ ./bot/
COPY main.py ./
COPY .env.example ./.env.example

# The application writes SQLite, audit, metrics, backup, and log data here.
RUN mkdir -p /app/data \
    && chown -R appuser:appuser /app /home/appuser

# Copy the frontend build with the same read permissions as the runtime user.
COPY --from=frontend /src/frontend/dist ./frontend/dist
RUN chown -R appuser:appuser /app/frontend/dist

USER appuser

EXPOSE 2095
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import os,urllib.request; p=os.getenv('PORT','2095'); urllib.request.urlopen(f'http://localhost:{p}/health', timeout=1)" || exit 1

CMD ["/app/.venv/bin/python", "main.py"]
