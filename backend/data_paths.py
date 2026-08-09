"""Centralized persistent-data paths for native and container deployments."""
from pathlib import Path

from backend.config import config

_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR = Path(config.DATA_DIR).expanduser() if config.DATA_DIR else _DEFAULT_DATA_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)
