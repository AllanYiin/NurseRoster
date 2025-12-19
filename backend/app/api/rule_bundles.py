from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.api.deps import db_session
from app.models.entities import RuleBundle, RuleBundleItem, SchedulePeriod
from app.schemas.common import ok
from app.services.rule_bundles import activate_rule_bundle, generate_rule_bundle

router = APIRouter(prefix="/api/rule-bundles", tags=["rule-bundles"])
logger = logging.getLogger(__name__)


class RuleSourceSelection(BaseModel):
    include_rule_ids: Optional[list[int]] = None


class TemplateSelection(BaseModel):
    template_id: Optional[int] = None


class NursePrefSelection(BaseModel):
    from_period_id: Optional[int] = None
    mode: str = "CLONE_AS_IS"


class RuleBundleGenerateOptions(BaseModel):
    validate_only: bool = False


class RuleBundleGenerateRequest(BaseModel):
    period_id: int
    project_id: int
    hospital_id: Optional[int] = None
    department_id: Optional[int] = None
    law: RuleSourceSelection = Field(default_factory=RuleSourceSelection)
    hospital: RuleSourceSelection = Field(default_factory=RuleSourceSelection)
    template: TemplateSelection = Field(default_factory=TemplateSelection)
    nurse_pref: NursePrefSelection = Field(default_factory=NursePrefSelection)
    options: RuleBundleGenerateOptions = Field(default_factory=RuleBundleGenerateOptions)


class RuleBundleActivateRequest(BaseModel):
    label: Optional[str] = None
    create_snapshot: bool = True


@router.post(":generate")
def generate_bundle(payload: RuleBundleGenerateRequest, session: Session = Depends(db_session)):
    try:
        bundle = generate_rule_bundle(
            session,
            period_id=payload.period_id,
            project_id=payload.project_id,
            hospital_id=payload.hospital_id,
            department_id=payload.department_id,
            law_rule_ids=payload.law.include_rule_ids,
            hospital_rule_ids=payload.hospital.include_rule_ids,
            template_id=payload.template.template_id,
            nurse_pref_from_period_id=payload.nurse_pref.from_period_id,
            validate_only=payload.options.validate_only,
            nurse_pref_mode=payload.nurse_pref.mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(bundle.model_dump())


@router.post("/{bundle_id}/activate")
def activate_bundle(bundle_id: int, payload: RuleBundleActivateRequest, session: Session = Depends(db_session)):
    bundle = session.get(RuleBundle, bundle_id)
    if not bundle:
        raise HTTPException(status_code=404, detail="找不到規則集")
    try:
        activated = activate_rule_bundle(
            session,
            period_id=bundle.period_id,
            bundle_id=bundle_id,
            label=payload.label,
            create_snapshot=payload.create_snapshot,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok({"period_id": activated.period_id, "active_rule_bundle_id": activated.id})


@router.get("/{bundle_id}")
def get_bundle(bundle_id: int, session: Session = Depends(db_session)):
    bundle = session.get(RuleBundle, bundle_id)
    if not bundle:
        raise HTTPException(status_code=404, detail="找不到規則集")
    return ok(bundle.model_dump())


@router.get("/{bundle_id}/items")
def list_bundle_items(bundle_id: int, layer: Optional[str] = None, session: Session = Depends(db_session)):
    stmt = select(RuleBundleItem).where(RuleBundleItem.bundle_id == bundle_id)
    if layer:
        stmt = stmt.where(RuleBundleItem.layer == layer)
    items = session.exec(stmt.order_by(RuleBundleItem.id)).all()
    return ok([it.model_dump() for it in items])


@router.get("/period/{period_id}")
def get_period_bundle(period_id: int, session: Session = Depends(db_session)):
    period = session.get(SchedulePeriod, period_id)
    if not period:
        raise HTTPException(status_code=404, detail="找不到排班期")
    bundle = None
    if period.active_rule_bundle_id:
        bundle = session.get(RuleBundle, period.active_rule_bundle_id)
    return ok({"period": period.model_dump(), "bundle": bundle.model_dump() if bundle else None})
