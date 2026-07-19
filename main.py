import uvicorn
from backend.config import config


def main():
    uvicorn.run(
        "backend.app:api",
        host=str(config.HOST),
        port=config.PORT,
        # reload=True spawns an extra file-watcher process and constantly polls
        # the filesystem; it is a development-only feature. Disabled to reduce
        # CPU/RAM in production.
        reload=False,
        workers=1,
        # --- Resource tuning: keep RAM/CPU bounded on a small VPS ---
        # Recycle the worker periodically so memory can't creep up from leaks.
        limit_max_requests=1000,
        # Bound concurrent in-flight requests so RAM stays predictable under load.
        limit_concurrency=200,
        # Shorter keep-alive frees idle socket buffers (RAM) faster.
        timeout_keep_alive=20,
        # Drop per-request chatter: access logs and extra headers cost CPU.
        access_log=False,
        server_header=False,
        date_header=False,
        ssl_keyfile=config.SSL_KEYFILE,
        ssl_certfile=config.SSL_CERTFILE,
    )


if __name__ == "__main__":
    main()
