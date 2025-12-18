from __future__ import annotations

import os
from pathlib import Path

# 專案根目錄（root/run_app.bat 同層）
PROJECT_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"
DEFAULT_EXPORT_DIR = PROJECT_ROOT / "exports"

DATA_DIR = Path(os.getenv("DATA_DIR", DEFAULT_DATA_DIR))
LOG_DIR = Path(os.getenv("LOG_DIR", DEFAULT_LOG_DIR))
EXPORT_DIR = Path(os.getenv("EXPORT_DIR", DEFAULT_EXPORT_DIR))

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = os.getenv("DB_PATH", str(DATA_DIR / "app.db"))
APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
