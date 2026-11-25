"""
================================================================================
 utils/logger.py - ONE SHARED LOGGER FOR THE WHOLE FRAMEWORK
================================================================================
WHY: without this, every file would set up its own logging differently,
and your terminal output (and log files) would look inconsistent. This
gives every agent, page object, and test the exact same log format for
free - just `from utils.logger import get_logger`.
================================================================================
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT / "reports" / "framework.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        # Already configured (avoids duplicate log lines if called twice).
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger