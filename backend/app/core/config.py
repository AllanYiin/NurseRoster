from __future__ import annotations

import os
from pathlib import Path

# 專案根目錄（root/run_app.bat 同層）
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_env_file(PROJECT_ROOT / ".env")

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

_HOST_ENV = os.getenv("BACKEND_HOST") or os.getenv("APP_HOST")
_PORT_ENV = os.getenv("BACKEND_PORT") or os.getenv("APP_PORT") or os.getenv("PORT")

BACKEND_HOST = _HOST_ENV or ("0.0.0.0" if os.getenv("PORT") else "127.0.0.1")

try:
    BACKEND_PORT = int(_PORT_ENV) if _PORT_ENV else 8000
except ValueError:
    BACKEND_PORT = 8000

APP_HOST = BACKEND_HOST
APP_PORT = BACKEND_PORT
