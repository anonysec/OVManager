# OVManager Panel - Docker image
# Builds the Vue frontend (frontend/dist) then runs the FastAPI panel.
FROM node:22-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN npm ci || npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1 \
    PATH="/root/.local/bin:${PATH}"

WORKDIR /app

# Backend deps first for better layer caching
COPY pyproject.toml uv.lock* ./
COPY backend/ ./backend/
COPY .github/ ./.github/
# Copy full project (excludes handled by .dockerignore)
COPY . .

# Bring in the built frontend assets
COPY --from=frontend /src/frontend/dist ./frontend/dist

RUN pip install --no-cache-dir uv \
    && uv sync --frozen || uv sync

EXPOSE 2095
CMD ["sh", "-c", "uv run main.py"]
