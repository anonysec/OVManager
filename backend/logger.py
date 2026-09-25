# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

import logging
import logging.handlers
import os
import sys

from backend.config import config
from backend.data_paths import DATA_DIR

LOG_FILE = str(DATA_DIR / "app.log")

os.makedirs(DATA_DIR, exist_ok=True)

level_map = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}
log_level = level_map.get(str(config.DEBUG).upper(), logging.WARNING)

# Rotating file (was: unbounded append) + stderr (was: file-only, invisible
# to `docker logs`) + second/module/line in the format (was: minute only).
_file_handler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
_stream_handler = logging.StreamHandler(sys.stderr)
_formatter = logging.Formatter(
    "{asctime} - {levelname} - {name} - {module}:{lineno} - {message}",
    style="{",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_file_handler.setFormatter(_formatter)
_stream_handler.setFormatter(_formatter)

logging.basicConfig(
    handlers=[_file_handler, _stream_handler],
    level=log_level,
)

logger = logging.getLogger("AppLogger")
