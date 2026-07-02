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
        ssl_keyfile=config.SSL_KEYFILE,
        ssl_certfile=config.SSL_CERTFILE,
    )


if __name__ == "__main__":
    main()
