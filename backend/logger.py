import logging
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(os.path.dirname(BASE_DIR), "data", "app.log")

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

import logging
import os

from backend.config import config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(os.path.dirname(BASE_DIR), "data", "app.log")

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

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
    """
    Get the last 10 logs from the log file
    """
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, "r") as f:
        lines = f.readlines()
    return lines[-10:]
