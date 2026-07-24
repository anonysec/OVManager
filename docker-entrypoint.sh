#!/bin/bash
set -e

# Start bot in background (using uv to manage dependencies)
uv run -C bot python -m bot.main &

# Run panel in foreground
exec uv run python main.py