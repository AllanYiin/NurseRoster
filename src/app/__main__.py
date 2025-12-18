from __future__ import annotations

import uvicorn

from app.core.config import APP_HOST, APP_PORT
from app.main import create_app


def main() -> None:
    app = create_app()
    uvicorn.run(app, host=APP_HOST, port=APP_PORT, log_level="info")


if __name__ == "__main__":
    main()
