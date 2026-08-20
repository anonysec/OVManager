# Stage 1: Build frontend
FROM node:22-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Backend
FROM python:3.12-slim
WORKDIR /app

# Create non-root user
RUN useradd -m -u 1000 appuser

# Install build/runtime dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy package metadata and Python sources before installing the project.
COPY pyproject.toml uv.lock* README.md ./
COPY backend/ ./backend/
COPY bot/ ./bot/
COPY main.py ./
COPY .env.example ./.env.example

# Install uv then sync from the lock file for fully reproducible builds.
RUN pip install --no-cache-dir uv \
    && uv sync --frozen || uv sync

# The application writes SQLite, audit, metrics, backup, and log data here.
RUN mkdir -p /app/data \
    && chown -R appuser:appuser /app /home/appuser

# Copy the frontend build with the same read permissions as the runtime user.
COPY --from=frontend /src/frontend/dist ./frontend/dist
RUN chown -R appuser:appuser /app/frontend/dist

USER appuser

EXPOSE 2095
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:2095/health', timeout=1)" || exit 1

CMD ["uv", "run", "main.py"]
