from __future__ import annotations

from sqlmodel import SQLModel, Session, create_engine

from app.core.config import DB_PATH

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        url = f"sqlite:///{DB_PATH}"
        _engine = create_engine(url, connect_args={"check_same_thread": False})
    return _engine


def init_db() -> None:
    engine = get_engine()
    # create tables
    SQLModel.metadata.create_all(engine)
    # set WAL
    with Session(engine) as s:
        s.exec("PRAGMA journal_mode=WAL;")
        s.exec("PRAGMA synchronous=NORMAL;")
        s.commit()


def get_session() -> Session:
    return Session(get_engine())
