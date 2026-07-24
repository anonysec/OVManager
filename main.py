#!/usr/bin/env python3
"""
Start OVManager panel and bot together in the same container.
"""
import sys
import os
import subprocess
import signal

# Ensure we're in the right directory
os.chdir('/app')
sys.path.insert(0, '/app')

from backend.config import config
import uvicorn


def main():
    """Run both OVManager panel and bot."""
    # Start bot in a subprocess
    bot_proc = subprocess.Popen([sys.executable, "-m", "bot.main"], cwd="/app")
    
    # Run panel in foreground
    try:
        uvicorn.run(
            "backend.app:api",
            host=str(config.HOST),
            port=config.PORT,
            reload=False,
            workers=1,
            limit_max_requests=1000,
            limit_concurrency=200,
            timeout_keep_alive=20,
            access_log=False,
            server_header=False,
            date_header=False,
            ssl_keyfile=config.SSL_KEYFILE or "",
            ssl_certfile=config.SSL_CERTFILE or "",
        )
    finally:
        # Terminate bot when panel stops
        bot_proc.terminate()
        try:
            bot_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            bot_proc.kill()


if __name__ == "__main__":
    main()