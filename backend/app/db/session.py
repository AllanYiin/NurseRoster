from __future__ import annotations

from sqlalchemy import text
from sqlmodel import SQLModel, Session, create_engine

from app.core.config import DB_PATH

_engine = None
_engine_db_path: str | None = None


def get_engine():
    global _engine, _engine_db_path
    if _engine is None or _engine_db_path != str(DB_PATH):
        url = f"sqlite:///{DB_PATH}"
        _engine = create_engine(url, connect_args={"check_same_thread": False})
        _engine_db_path = str(DB_PATH)
    return _engine


def init_db() -> None:
    engine = get_engine()
    # create tables
    SQLModel.metadata.create_all(engine)
    # set WAL
    with Session(engine) as s:
        s.exec(text("PRAGMA journal_mode=WAL;"))
        s.exec(text("PRAGMA synchronous=NORMAL;"))
        s.commit()


def get_session() -> Session:
    return Session(get_engine())
