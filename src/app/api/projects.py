from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.api.deps import db_session
from app.models.entities import Project
from app.schemas.common import ok

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("/current")
def get_current(session: Session = Depends(db_session)):
    month = datetime.now().strftime("%Y-%m")
    proj = session.exec(select(Project).where(Project.month == month)).first()
    if proj is None:
        proj = Project(name="新專案", month=month)
        session.add(proj)
        session.commit()
        session.refresh(proj)
    return ok({"id": proj.id, "name": proj.name, "month": proj.month})
