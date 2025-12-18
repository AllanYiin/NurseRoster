from __future__ import annotations

import importlib
import sys
from typing import Iterator

import pytest
from fastapi.testclient import TestClient


def _reload_module(name: str):
    if name in sys.modules:
        importlib.reload(sys.modules[name])
    else:
        importlib.import_module(name)


@pytest.fixture
def test_context(tmp_path, monkeypatch) -> Iterator[dict]:
    """為每個測試建立獨立環境（目錄、環境變數與資料庫）。"""
    data_dir = tmp_path / "data"
    log_dir = tmp_path / "logs"
    export_dir = tmp_path / "exports"
    for d in (data_dir, log_dir, export_dir):
        d.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("LOG_DIR", str(log_dir))
    monkeypatch.setenv("EXPORT_DIR", str(export_dir))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("SKIP_SEED", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    for mod in ["app.core.config", "app.db.session", "app.services.seed"]:
        _reload_module(mod)

    from app import main as app_main
    from app.db import session as db_session

    _reload_module("app.main")
    db_session.init_db()

    def make_session():
        return db_session.get_session()

    def make_client() -> TestClient:
        _reload_module("app.main")
        app = app_main.create_app()
        return TestClient(app)

    yield {"make_session": make_session, "make_client": make_client}
