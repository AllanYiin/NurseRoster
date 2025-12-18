from __future__ import annotations

import logging
import sys

from .config import LOG_DIR

LOG_FILE = LOG_DIR / "app.log"


def setup_logging() -> None:
    """設定分級日誌，避免重複註冊 handler。"""
    if getattr(setup_logging, "_configured", False):
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    # console
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(fmt))
    root.addHandler(ch)

    # file
    fh = logging.FileHandler(str(LOG_FILE), encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(fmt))
    root.addHandler(fh)

    setup_logging._configured = True
