from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from datetime import datetime

from app.api.deps import db_session
from app.models.entities import Template, TemplateRuleLink
from app.schemas.common import ok

router = APIRouter(prefix="/api/templates", tags=["templates"])


class TemplateCreateRequest(BaseModel):
    name: str
    hospital_id: Optional[int] = None
    department_id: Optional[int] = None
    description: str = ""


class TemplateRuleLinkUpsert(BaseModel):
    rule_id: int
    included: bool = True
    overrides: Optional[dict] = None


class TemplateRulesUpdateRequest(BaseModel):
    items: list[TemplateRuleLinkUpsert]


@router.get("")
def list_templates(
    hospital_id: Optional[int] = None,
    department_id: Optional[int] = None,
    session: Session = Depends(db_session),
):
    stmt = select(Template).where(Template.is_active == True)  # noqa: E712
    if hospital_id is not None:
        stmt = stmt.where(Template.hospital_id == hospital_id)
    if department_id is not None:
        stmt = stmt.where(Template.department_id == department_id)
    rows = session.exec(stmt.order_by(Template.updated_at.desc())).all()
    return ok([r.model_dump() for r in rows])


@router.post("")
def create_template(payload: TemplateCreateRequest, session: Session = Depends(db_session)):
    template = Template(
        name=payload.name,
        hospital_id=payload.hospital_id,
        department_id=payload.department_id,
        description=payload.description,
    )
    session.add(template)
    session.commit()
    session.refresh(template)
    return ok(template.model_dump())


@router.put("/{template_id}")
def update_template(template_id: int, payload: TemplateCreateRequest, session: Session = Depends(db_session)):
    template = session.get(Template, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="找不到公版")
    template.name = payload.name
    template.hospital_id = payload.hospital_id
    template.department_id = payload.department_id
    template.description = payload.description
    template.updated_at = datetime.utcnow()
    session.add(template)
    session.commit()
    session.refresh(template)
    return ok(template.model_dump())


@router.delete("/{template_id}")
def delete_template(template_id: int, session: Session = Depends(db_session)):
    template = session.get(Template, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="找不到公版")
    template.is_active = False
    template.updated_at = datetime.utcnow()
    session.add(template)
    session.commit()
    return ok(True)


@router.put("/{template_id}/rules")
def upsert_template_rules(template_id: int, payload: TemplateRulesUpdateRequest, session: Session = Depends(db_session)):
    template = session.get(Template, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="找不到公版")
    for item in payload.items:
        link = session.exec(
            select(TemplateRuleLink).where(TemplateRuleLink.template_id == template_id, TemplateRuleLink.rule_id == item.rule_id)
        ).first()
        if not link:
            link = TemplateRuleLink(template_id=template_id, rule_id=item.rule_id)
        link.included = item.included
        link.overrides_json = item.overrides or {}
        link.updated_at = datetime.utcnow()
        session.add(link)
    session.commit()
    links = session.exec(select(TemplateRuleLink).where(TemplateRuleLink.template_id == template_id)).all()
    return ok([l.model_dump() for l in links])


@router.get("/{template_id}/rules")
def list_template_rules(template_id: int, session: Session = Depends(db_session)):
    template = session.get(Template, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="找不到公版")
    links = session.exec(select(TemplateRuleLink).where(TemplateRuleLink.template_id == template_id)).all()
    return ok([l.model_dump() for l in links])
