# syntax=docker/dockerfile:1
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# Distroless image: prebuilt SPA + static Go binary. The runtime layout mirrors
# install.sh — binary at the app root with web/dist beside it — because the
# server resolves appDir() from the working directory (OVM_APP_DIR overrides).

# --- SPA ---------------------------------------------------------------
# .dockerignore keeps web/ source but drops web/dist, so the UI is built here
# instead of shipping a possibly stale local bundle.
FROM node:22-slim AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# --- Go binary ---------------------------------------------------------
# modernc.org/sqlite is pure Go, so CGO_ENABLED=0 yields a static binary.
FROM golang:1.27 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY cmd/ ./cmd/
COPY internal/ ./internal/
RUN CGO_ENABLED=0 go build -o /out/ovmanager ./cmd
# Writable data dir for the nonroot user, created here so the runtime stage
# can COPY it with the right ownership (distroless has no shell).
RUN mkdir -p /data

# --- Runtime -----------------------------------------------------------
FROM gcr.io/distroless/static-debian12:nonroot
WORKDIR /app
COPY --from=build /out/ovmanager /app/ovmanager
COPY --from=web /src/web/dist /app/web/dist
COPY --from=build --chown=nonroot:nonroot /data /data

ENV OVM_APP_DIR=/app \
    DATA_DIR=/data \
    PORT=2095
EXPOSE 2095
USER nonroot
ENTRYPOINT ["/app/ovmanager"]
