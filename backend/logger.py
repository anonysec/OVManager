# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

import logging
import os

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

logging.basicConfig(
    filename=LOG_FILE,
    encoding="utf-8",
    filemode="a",
    format="{asctime} - {levelname} - {message}",
    style="{",
    datefmt="%Y-%m-%d %H:%M",
    level=log_level,
)

logger = logging.getLogger("AppLogger")


def get_10_logs():
    """Get the last 10 logs from the log file."""
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE) as f:
        lines = f.readlines()
    return lines[-10:]
