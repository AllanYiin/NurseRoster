from __future__ import annotations

import logging
import uvicorn

from app.core.logging import setup_logging
from app.core.config import APP_HOST, APP_PORT
from app.main import create_app


def main() -> None:
    setup_logging()
    try:
        app = create_app()
        uvicorn.run(app, host=APP_HOST, port=APP_PORT, log_level="info")
    except Exception:
        logging.exception("應用啟動失敗，請檢查設定或重試。")
        raise


if __name__ == "__main__":
    main()
