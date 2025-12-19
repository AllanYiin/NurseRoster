from __future__ import annotations

from datetime import datetime, date
from calendar import monthrange
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select, delete

from app.api.deps import db_session
from app.models.entities import Assignment, Project, ProjectSnapshot, Rule, RuleVersion, SchedulePeriod
from app.schemas.common import ok
from app.services.law_rules import ensure_law_rules

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    month: str
    schedule_period_id: Optional[int] = None


class SnapshotCreate(BaseModel):
    name: str = ""
    include_assignments: bool = True
    include_rules: bool = True
    payload: dict = Field(default_factory=dict)


def _get_project_or_404(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="找不到專案")
    return project


def _snapshot_content(session: Session, project_id: int, payload: dict, include_assignments: bool, include_rules: bool) -> dict:
    data = dict(payload or {})
    if include_assignments:
        assignments = session.exec(select(Assignment).where(Assignment.project_id == project_id)).all()
        data["assignments"] = [a.model_dump() for a in assignments]
    if include_rules:
        rules = session.exec(select(Rule).where(Rule.project_id == project_id)).all()
        data["rules"] = [r.model_dump() for r in rules]
        rule_ids = [r.id for r in rules if r.id]
        if rule_ids:
            versions = session.exec(select(RuleVersion).where(RuleVersion.rule_id.in_(rule_ids))).all()
            data["rule_versions"] = [rv.model_dump() for rv in versions]
    return data


def _restore_date_range(project: Project, session: Session) -> tuple[date, date]:
    if project.schedule_period_id:
        period = session.get(SchedulePeriod, project.schedule_period_id)
        if period:
            return period.start_date, period.end_date
    try:
        year, month = map(int, project.month.split("-"))
        start = date(year, month, 1)
        end = date(year, month, monthrange(year, month)[1])
        return start, end
    except Exception:
        today = date.today()
        return today, today


@router.post("")
def create_project(payload: ProjectCreate, session: Session = Depends(db_session)):
    proj = Project(name=payload.name, month=payload.month, schedule_period_id=payload.schedule_period_id)
    session.add(proj)
    session.commit()
    session.refresh(proj)
    ensure_law_rules(session, proj.id)
    return ok(proj.model_dump())


@router.get("/current")
def get_current(session: Session = Depends(db_session)):
    month = datetime.now().strftime("%Y-%m")
    proj = session.exec(select(Project).where(Project.month == month)).first()
    if proj is None:
        proj = Project(name="新專案", month=month)
        session.add(proj)
        session.commit()
        session.refresh(proj)
        ensure_law_rules(session, proj.id)
    return ok({"id": proj.id, "name": proj.name, "month": proj.month})


@router.get("/{project_id}")
def get_project(project_id: int, session: Session = Depends(db_session)):
    proj = _get_project_or_404(session, project_id)
    snapshots = session.exec(select(ProjectSnapshot).where(ProjectSnapshot.project_id == project_id).order_by(ProjectSnapshot.id.desc())).all()
    return ok({"project": proj.model_dump(), "snapshots": [s.model_dump() for s in snapshots]})


@router.get("/{project_id}/snapshots")
def list_snapshots(project_id: int, session: Session = Depends(db_session)):
    _get_project_or_404(session, project_id)
    snaps = session.exec(select(ProjectSnapshot).where(ProjectSnapshot.project_id == project_id).order_by(ProjectSnapshot.id.desc())).all()
    return ok([s.model_dump() for s in snaps])


@router.post("/{project_id}/snapshots")
def create_snapshot(project_id: int, payload: SnapshotCreate, session: Session = Depends(db_session)):
    project = _get_project_or_404(session, project_id)
    content = _snapshot_content(session, project_id, payload.payload, payload.include_assignments, payload.include_rules)
    name = payload.name or f"Snapshot {datetime.utcnow().isoformat(timespec='seconds')}"
    snap = ProjectSnapshot(project_id=project.id, name=name, snapshot=content)
    session.add(snap)
    session.commit()
    session.refresh(snap)
    return ok(snap.model_dump())


@router.post("/{project_id}/restore/{snapshot_id}")
def restore_snapshot(project_id: int, snapshot_id: int, session: Session = Depends(db_session)):
    _get_project_or_404(session, project_id)
    snap = session.get(ProjectSnapshot, snapshot_id)
    if not snap or snap.project_id != project_id:
        raise HTTPException(status_code=404, detail="找不到快照")

    data = snap.snapshot or {}

    # assignments
    session.exec(delete(Assignment).where(Assignment.project_id == project_id))
    for it in data.get("assignments", []):
        payload = {k: v for k, v in it.items() if k in {"project_id", "day", "nurse_staff_no", "shift_code", "note", "updated_at"}}
        payload.setdefault("project_id", project_id)
        session.add(Assignment(**payload))

    # rules & versions
    rule_ids = [r.id for r in session.exec(select(Rule.id).where(Rule.project_id == project_id)).all()]
    if rule_ids:
        session.exec(delete(RuleVersion).where(RuleVersion.rule_id.in_(rule_ids)))
    session.exec(delete(Rule).where(Rule.project_id == project_id))

    rule_id_map = {}
    for it in data.get("rules", []):
        payload = {k: v for k, v in it.items() if k in Rule.model_fields}
        payload["project_id"] = project_id
        r = Rule(**payload)
        session.add(r)
        session.flush()
        rule_id_map[it.get("id")] = r.id

    for it in data.get("rule_versions", []):
        original_rule_id = it.get("rule_id")
        new_rule_id = rule_id_map.get(original_rule_id)
        if not new_rule_id:
            continue
        payload = {k: v for k, v in it.items() if k in RuleVersion.model_fields}
        payload["rule_id"] = new_rule_id
        session.add(RuleVersion(**payload))

    session.commit()

    start, end = _restore_date_range(_get_project_or_404(session, project_id), session)
    return ok({"restored_snapshot_id": snapshot_id, "assignments": data.get("assignments", []), "date_range": {"start": start, "end": end}})
