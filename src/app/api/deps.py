from __future__ import annotations

from fastapi import Depends
from sqlmodel import Session

from app.db.session import get_session


def db_session() -> Session:
    with get_session() as s:
        yield s
