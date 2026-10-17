# syntax=docker/dockerfile:1
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# Distroless image: one static Go binary with the SPA embedded (internal/webfs).
# No node stage and no web/dist in the image — the runtime carries only the
# binary, exactly like a release install.
#
# The SPA is still compiled into the binary, so the build needs a prebuilt
# web/dist in the context: run `make build` (which produces it) or let the
# Docker workflow build the frontend first.

# --- Go binary ---------------------------------------------------------
# modernc.org/sqlite is pure Go, so CGO_ENABLED=0 yields a static binary.
FROM golang:1.27 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY cmd/ ./cmd/
COPY internal/ ./internal/
COPY web/dist/ ./internal/webfs/dist/
RUN CGO_ENABLED=0 go build -o /out/ovmanager ./cmd
# Writable data dir for the nonroot user, created here so the runtime stage
# can COPY it with the right ownership (distroless has no shell).
RUN mkdir -p /data

# --- Runtime -----------------------------------------------------------
FROM gcr.io/distroless/static-debian12:nonroot
WORKDIR /app
COPY --from=build /out/ovmanager /app/ovmanager
COPY --from=build --chown=nonroot:nonroot /data /data

ENV OVM_APP_DIR=/app \
    DATA_DIR=/data \
    PORT=2095
EXPOSE 2095
USER nonroot
ENTRYPOINT ["/app/ovmanager"]
