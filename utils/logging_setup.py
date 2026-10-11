"""Logging: everything goes to the console AND to a timestamped file in logs/."""
import logging
import sys
from datetime import datetime
from pathlib import Path

from config import settings


def setup_logging(level: str = "INFO", prefix: str = "collect") -> Path:
    settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = settings.LOG_DIR / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}.log"

    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", "%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return log_file
