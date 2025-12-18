from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import db_session
from app.models.entities import Assignment
from app.schemas.common import ok

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


class AssignmentIn(BaseModel):
    project_id: int
    day: date
    nurse_staff_no: str
    shift_code: str = ""
    note: str = ""


@router.get("/assignments")
def list_assignments(project_id: int, start: date, end: date, session: Session = Depends(db_session)):
    q = select(Assignment).where(Assignment.project_id == project_id, Assignment.day >= start, Assignment.day <= end)
    items = session.exec(q).all()
    return ok([a.model_dump() for a in items])


@router.post("/assignments/batch_upsert")
def batch_upsert(payload: List[AssignmentIn], session: Session = Depends(db_session)):
    for it in payload:
        q = select(Assignment).where(
            Assignment.project_id == it.project_id,
            Assignment.day == it.day,
            Assignment.nurse_staff_no == it.nurse_staff_no,
        )
        existing = session.exec(q).first()
        if existing:
            existing.shift_code = it.shift_code
            existing.note = it.note
            existing.updated_at = datetime.utcnow()
            session.add(existing)
        else:
            session.add(Assignment(**it.model_dump()))
    session.commit()
    return ok({"updated": len(payload)})
