from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import db_session
from app.models.entities import Rule
from app.schemas.common import ok
from app.services.rules import stream_nl_to_dsl, dsl_to_nl, validate_dsl

router = APIRouter(prefix="/api/rules", tags=["rules"])


class RuleUpsert(BaseModel):
    title: str
    nl_text: str = ""
    dsl_text: str = ""
    is_enabled: bool = True


@router.get("", response_model=None)
def list_rules(project_id: int, s: Session = Depends(db_session)):
    rows = s.exec(select(Rule).where(Rule.project_id == project_id).order_by(Rule.id)).all()
    return ok([r.model_dump() for r in rows])


@router.post("", response_model=None)
def create_rule(project_id: int, payload: RuleUpsert, s: Session = Depends(db_session)):
    r = Rule(project_id=project_id, title=payload.title, nl_text=payload.nl_text, dsl_text=payload.dsl_text, is_enabled=payload.is_enabled)
    s.add(r)
    s.commit()
    s.refresh(r)
    return ok(r.model_dump())


@router.put("/{rule_id}", response_model=None)
def update_rule(rule_id: int, payload: RuleUpsert, s: Session = Depends(db_session)):
    r = s.get(Rule, rule_id)
    if not r:
        return ok(None)
    r.title = payload.title
    r.nl_text = payload.nl_text
    r.dsl_text = payload.dsl_text
    r.is_enabled = payload.is_enabled
    r.updated_at = __import__("datetime").datetime.utcnow()
    s.add(r)
    s.commit()
    s.refresh(r)
    return ok(r.model_dump())


@router.delete("/{rule_id}", response_model=None)
def delete_rule(rule_id: int, s: Session = Depends(db_session)):
    r = s.get(Rule, rule_id)
    if r:
        s.delete(r)
        s.commit()
    return ok(True)


class NLReq(BaseModel):
    text: str


@router.get("/nl_to_dsl_stream")
def nl_to_dsl_stream(text: str):
    gen = stream_nl_to_dsl(text)
    return StreamingResponse(gen, media_type="text/event-stream")


@router.post("/dsl_to_nl")
def api_dsl_to_nl(payload: dict):
    return ok({"text": dsl_to_nl(payload.get("dsl_text", ""))})


@router.post("/validate")
def api_validate(payload: dict):
    return ok(validate_dsl(payload.get("dsl_text", "")))
