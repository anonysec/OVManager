# Stage 1: Build frontend
FROM node:22-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN npm ci || npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Backend
FROM python:3.12-slim
WORKDIR /app

# Create non-root user
RUN useradd -m -u 1000 appuser

# Install system dependencies if needed
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY pyproject.toml ./

# Install dependencies
RUN pip install --no-cache-dir .

# Copy source code
COPY backend/ ./backend/
COPY bot/ ./bot/
COPY main.py ./
COPY .env.example ./.env.example

# Note: the frontend dist will be copied from the builder stage
COPY --from=frontend /src/frontend/dist ./frontend/dist

# Switch to non-root user
USER appuser

EXPOSE 2095
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:2095/health', timeout=1)" || exit 1

CMD ["python", "main.py"]