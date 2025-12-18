from __future__ import annotations

import json
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import db_session
from app.models.entities import Assignment, Project, Rule, RuleType, SchedulePeriod
from app.schemas.common import ok

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


class AssignmentPayload(BaseModel):
    project_id: int
    day: date
    nurse_staff_no: str
    shift_code: str = ""
    note: str = ""


class Conflict(BaseModel):
    rule_id: Optional[int]
    rule_title: str
    severity: str
    message: str
    date: Optional[date] = None
    nurse_staff_no: Optional[str] = None
    shift_code: Optional[str] = None


def _project_date_range(session: Session, project: Project, start: Optional[date], end: Optional[date]) -> tuple[date, date]:
    if start and end:
        return start, end
    if project.schedule_period_id:
        period = session.get(SchedulePeriod, project.schedule_period_id)
        if period:
            return start or period.start_date, end or period.end_date
    try:
        year, month = map(int, project.month.split("-"))
        first = date(year, month, 1)
        last = date(year, month, monthrange(year, month)[1])
        return start or first, end or last
    except Exception:
        today = date.today()
        return start or today, end or today


def _parse_constraints(rule: Rule) -> List[dict]:
    try:
        obj = json.loads(rule.dsl_text or "{}")
    except Exception:
        return []
    constraints = obj.get("constraints") or obj.get("constraint") or []
    if isinstance(constraints, dict):
        constraints = [constraints]
    return [c for c in constraints if isinstance(c, dict)]


def _severity(rule: Rule) -> str:
    return "error" if rule.rule_type == RuleType.HARD else "warn"


def _collect_assignments(session: Session, project_id: int, start: date, end: date) -> List[Assignment]:
    return session.exec(
        select(Assignment).where(Assignment.project_id == project_id, Assignment.day >= start, Assignment.day <= end)
    ).all()


@router.get("/assignments")
def list_assignments(project_id: int, start: Optional[date] = None, end: Optional[date] = None, session: Session = Depends(db_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="找不到專案")
    start_date, end_date = _project_date_range(session, project, start, end)
    assignments = _collect_assignments(session, project_id, start_date, end_date)
    return ok([a.model_dump() for a in assignments])


@router.put("/assignments")
def upsert_assignments(payload: List[AssignmentPayload], session: Session = Depends(db_session)):
    if not payload:
        return ok({"updated": 0})
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


@router.get("/conflicts")
def list_conflicts(project_id: int, start: Optional[date] = None, end: Optional[date] = None, session: Session = Depends(db_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="找不到專案")

    start_date, end_date = _project_date_range(session, project, start, end)
    assignments = _collect_assignments(session, project_id, start_date, end_date)
    assignments_by_date: Dict[date, List[Assignment]] = {}
    assignments_by_pair: Dict[tuple[str, date], Assignment] = {}
    for a in assignments:
        assignments_by_date.setdefault(a.day, []).append(a)
        assignments_by_pair[(a.nurse_staff_no, a.day)] = a

    all_dates: List[date] = []
    cur = start_date
    while cur <= end_date:
        all_dates.append(cur)
        cur += timedelta(days=1)

    nurse_ids = {a.nurse_staff_no for a in assignments}

    conflicts: List[Conflict] = []
    rules = session.exec(select(Rule).where(Rule.project_id == project_id, Rule.is_enabled == True)).all()  # noqa: E712

    for rule in rules:
        constraints = _parse_constraints(rule)
        for c in constraints:
            name = (c.get("name") or c.get("constraint") or c.get("type") or "").strip()
            if name == "daily_coverage":
                shift_code = str(c.get("shift") or "").strip()
                min_count = int(c.get("min") or 0)
                if not shift_code or min_count <= 0:
                    continue
                for d in all_dates:
                    actual = sum(1 for a in assignments_by_date.get(d, []) if a.shift_code == shift_code)
                    if actual < min_count:
                        conflicts.append(
                            Conflict(
                                rule_id=rule.id,
                                rule_title=rule.title,
                                severity=_severity(rule),
                                message=f"{d} {shift_code} 班人數 {actual} 小於需求 {min_count}",
                                date=d,
                                shift_code=shift_code,
                            )
                        )
            elif name == "max_consecutive":
                shift_code = str(c.get("shift") or "").strip()
                max_days = int(c.get("max_days") or c.get("max") or 0)
                if not shift_code or max_days <= 0:
                    continue
                for nurse in nurse_ids:
                    streak = 0
                    for d in all_dates:
                        assigned = assignments_by_pair.get((nurse, d))
                        if assigned and assigned.shift_code == shift_code:
                            streak += 1
                            if streak > max_days:
                                conflicts.append(
                                    Conflict(
                                        rule_id=rule.id,
                                        rule_title=rule.title,
                                        severity=_severity(rule),
                                        message=f"{nurse} 連續 {shift_code} 已超過 {max_days} 天",
                                        date=d,
                                        nurse_staff_no=nurse,
                                        shift_code=shift_code,
                                    )
                                )
                        else:
                            streak = 0
            elif name == "prefer_off_after_night":
                night_code = str(c.get("shift") or "N").strip() or "N"
                off_code = str(c.get("off_code") or "OFF").strip() or "OFF"
                for nurse in nurse_ids:
                    for idx in range(len(all_dates) - 1):
                        d = all_dates[idx]
                        d2 = all_dates[idx + 1]
                        a1 = assignments_by_pair.get((nurse, d))
                        a2 = assignments_by_pair.get((nurse, d2))
                        if a1 and a1.shift_code == night_code:
                            if not a2 or a2.shift_code != off_code:
                                conflicts.append(
                                    Conflict(
                                        rule_id=rule.id,
                                        rule_title=rule.title,
                                        severity="warn",
                                        message=f"{nurse} {d} 夜班後未安排 {off_code}",
                                        date=d2,
                                        nurse_staff_no=nurse,
                                        shift_code=off_code,
                                    )
                                )

    return ok([c.model_dump() for c in conflicts])
