"""Zeabur-friendly backend launcher.

This script can be executed from the repository root without changing the
working directory. It ensures the backend package is importable and aligns the
host/port with common platform conventions (e.g., Zeabur's ``PORT`` env).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _ensure_backend_on_path() -> None:
    root = Path(__file__).resolve().parent
    backend_dir = root / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))


def _align_env_defaults() -> None:
    port = os.getenv("BACKEND_PORT") or os.getenv("APP_PORT") or os.getenv("PORT")
    if port and not os.getenv("BACKEND_PORT"):
        os.environ["BACKEND_PORT"] = port
    if port and not os.getenv("APP_PORT"):
        os.environ["APP_PORT"] = port

    if not os.getenv("BACKEND_HOST") and not os.getenv("APP_HOST"):
        # 0.0.0.0 makes the service reachable behind Zeabur's proxy
        os.environ["BACKEND_HOST"] = "0.0.0.0"
        os.environ["APP_HOST"] = "0.0.0.0"


def main() -> None:
    _ensure_backend_on_path()
    _align_env_defaults()

    from app.__main__ import main as backend_main

    backend_main()


if __name__ == "__main__":
    main()
