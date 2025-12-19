from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import db_session
from app.models.entities import SchedulePeriod
from app.schemas.common import ok

router = APIRouter(prefix="/api/schedule-periods", tags=["schedule-periods"])
logger = logging.getLogger(__name__)


class SchedulePeriodCreateRequest(BaseModel):
    name: str
    start_date: date
    end_date: date
    project_id: Optional[int] = None
    hospital_id: Optional[int] = None
    department_id: Optional[int] = None


@router.post("")
def create_schedule_period(payload: SchedulePeriodCreateRequest, session: Session = Depends(db_session)):
    period = SchedulePeriod(
        name=payload.name,
        start_date=payload.start_date,
        end_date=payload.end_date,
        project_id=payload.project_id,
        hospital_id=payload.hospital_id,
        department_id=payload.department_id,
    )
    session.add(period)
    session.commit()
    session.refresh(period)
    return ok(period.model_dump())


@router.get("/{period_id}")
def get_schedule_period(period_id: int, session: Session = Depends(db_session)):
    period = session.get(SchedulePeriod, period_id)
    if not period:
        raise HTTPException(status_code=404, detail="找不到排班期")
    return ok(period.model_dump())


@router.get("/{period_id}/previous-periods")
def list_previous_periods(
    period_id: int,
    department_id: Optional[int] = None,
    limit: int = Query(default=12, ge=1, le=50),
    session: Session = Depends(db_session),
):
    period = session.get(SchedulePeriod, period_id)
    if not period:
        raise HTTPException(status_code=404, detail="找不到排班期")
    stmt = select(SchedulePeriod).where(SchedulePeriod.id != period_id)
    if department_id is not None:
        stmt = stmt.where(SchedulePeriod.department_id == department_id)
    stmt = stmt.order_by(SchedulePeriod.start_date.desc()).limit(limit)
    rows = session.exec(stmt).all()
    return ok([r.model_dump() for r in rows])
