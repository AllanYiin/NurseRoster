from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_
from sqlmodel import Session, select

from app.api.deps import db_session
from app.db.session import get_session
from app.models.entities import Rule, RuleScopeType, RuleType, RuleVersion, ValidationStatus
from app.schemas.common import ok
from app.services.rules import (
    sse_event,
    stream_nl_to_dsl,
    dsl_to_nl,
    dsl_to_nl_with_prompt,
    validate_dsl,
    stream_nl_to_dsl_events,
    is_law_dsl,
)

router = APIRouter(prefix="/api/rules", tags=["rules"])
logger = logging.getLogger(__name__)


class RuleUpsert(BaseModel):
    title: str
    nl_text: str = ""
    dsl_text: str = ""
    is_enabled: bool = True


class RuleVersionFromDsl(BaseModel):
    dsl_text: str
    nl_text: str = ""
    reverse_translation: str | None = None


def _ensure_rule(session: Session, rule_id: int) -> Rule:
    rule = session.get(Rule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="找不到規則")
    return rule


def _ensure_not_law(rule: Rule) -> None:
    if is_law_dsl(rule.dsl_text):
        raise HTTPException(status_code=403, detail="LAW 規則不可編輯或刪除")


def _next_version(session: Session, rule_id: int) -> int:
    latest = session.exec(
        select(RuleVersion.version).where(RuleVersion.rule_id == rule_id).order_by(RuleVersion.version.desc())
    ).first()
    return int(latest or 0) + 1


def _validation_status(result: dict) -> ValidationStatus:
    if not result.get("ok"):
        return ValidationStatus.FAIL
    if result.get("warnings"):
        return ValidationStatus.WARN
    return ValidationStatus.PASS


@router.get("", response_model=None)
def list_rules(
    project_id: int,
    scope_type: Optional[RuleScopeType] = None,
    scope_id: Optional[int] = None,
    type: Optional[RuleType] = None,
    q: Optional[str] = None,
    s: Session = Depends(db_session),
):
    stmt = select(Rule).where(Rule.project_id == project_id)
    if scope_type:
        stmt = stmt.where(Rule.scope_type == scope_type)
    if scope_id is not None:
        stmt = stmt.where(Rule.scope_id == scope_id)
    if type:
        stmt = stmt.where(Rule.rule_type == type)
    if q:
        keyword = f"%{q}%"
        stmt = stmt.where(or_(Rule.title.ilike(keyword), Rule.nl_text.ilike(keyword), Rule.dsl_text.ilike(keyword)))
    rows = s.exec(stmt.order_by(Rule.id)).all()
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
    _ensure_not_law(r)
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
        _ensure_not_law(r)
        s.delete(r)
        s.commit()
    return ok(True)


@router.get("/{rule_id}/versions")
def list_rule_versions(rule_id: int, s: Session = Depends(db_session)):
    _ensure_rule(s, rule_id)
    rows = s.exec(select(RuleVersion).where(RuleVersion.rule_id == rule_id).order_by(RuleVersion.version.desc())).all()
    return ok([r.model_dump() for r in rows])


@router.post("/{rule_id}/versions:from_dsl")
def create_rule_version_from_dsl(rule_id: int, payload: RuleVersionFromDsl, s: Session = Depends(db_session)):
    rule = _ensure_rule(s, rule_id)
    _ensure_not_law(rule)
    version = _next_version(s, rule_id)
    validation = validate_dsl(payload.dsl_text, session=s, rule=rule)
    status = _validation_status(validation)
    rv = RuleVersion(
        rule_id=rule_id,
        version=version,
        nl_text=payload.nl_text,
        dsl_text=payload.dsl_text,
        reverse_translation=payload.reverse_translation or dsl_to_nl(payload.dsl_text),
        validation_status=status,
        validation_report=validation,
    )
    s.add(rv)
    s.commit()
    s.refresh(rv)
    return ok(rv.model_dump())


class NLReq(BaseModel):
    text: str


@router.post("/{rule_id}/versions:from_nl")
def create_rule_version_from_nl(rule_id: int, payload: NLReq):
    def _stream():
        collected: List[str] = []
        final_text = ""
        version_id: int | None = None
        draft_version_no: int | None = None

        # 建立草稿版本
        with get_session() as session:
            rule = session.get(Rule, rule_id)
            if not rule:
                yield sse_event("error", {"message": "找不到規則"})
                return
            _ensure_not_law(rule)
            draft_version_no = _next_version(session, rule_id)
            draft = RuleVersion(
                rule_id=rule_id,
                version=draft_version_no,
                nl_text=payload.text,
                validation_status=ValidationStatus.PENDING,
                validation_report={"issues": ["尚未完成轉譯"], "warnings": []},
            )
            session.add(draft)
            session.commit()
            session.refresh(draft)
            version_id = draft.id

        if version_id:
            yield sse_event("draft", {"rule_version_id": version_id, "version": draft_version_no, "status": ValidationStatus.PENDING.value})

        for event, chunk in stream_nl_to_dsl_events(payload.text):
            if event == "token":
                collected.append(chunk.get("text", ""))
            if event == "completed":
                final_text = chunk.get("dsl_text", final_text)
            yield sse_event(event, chunk)

        dsl_text = final_text or "".join(collected)
        if not dsl_text:
            if version_id:
                with get_session() as session:
                    rv = session.get(RuleVersion, version_id)
                    if rv:
                        rv.validation_status = ValidationStatus.FAIL
                        rv.validation_report = {"issues": ["未產出 DSL"], "warnings": []}
                        session.add(rv)
                        session.commit()
            return

        with get_session() as session:
            rule = session.get(Rule, rule_id)
            if not rule:
                return
            validation = validate_dsl(dsl_text, session=session, rule=rule)
            status = _validation_status(validation)
            reverse = dsl_to_nl(dsl_text)
            rv = session.get(RuleVersion, version_id) if version_id else None
            if rv is None:
                version = _next_version(session, rule_id)
                rv = RuleVersion(rule_id=rule_id, version=version)
            rv.nl_text = payload.text
            rv.dsl_text = dsl_text
            rv.reverse_translation = reverse
            rv.validation_status = status
            rv.validation_report = validation
            session.add(rv)
            session.commit()

        yield sse_event(
            "validated",
            {
                "rule_version_id": version_id,
                "status": status.value,
                "issues": validation.get("issues", []),
                "warnings": validation.get("warnings", []),
            },
        )

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.get("/nl_to_dsl_stream")
def nl_to_dsl_stream(text: str):
    gen = stream_nl_to_dsl(text)
    return StreamingResponse(gen, media_type="text/event-stream")


@router.websocket("/nl_to_dsl_ws")
async def nl_to_dsl_ws(websocket: WebSocket):
    await websocket.accept()
    text = websocket.query_params.get("text", "")
    try:
        for event, payload in stream_nl_to_dsl_events(text):
            await websocket.send_json({"event": event, "data": payload})
    except WebSocketDisconnect:
        logger.info("NL→DSL WebSocket client disconnected")
    except Exception:
        logger.exception("NL→DSL WebSocket 失敗")
        await websocket.send_json({"event": "error", "data": {"message": "轉譯失敗，請稍後再試。"}})
    finally:
        try:
            await websocket.close()
        except Exception:
            # 已斷線則忽略
            pass


@router.post("/dsl_to_nl")
def api_dsl_to_nl(payload: dict):
    result = dsl_to_nl_with_prompt(payload.get("dsl_text", ""), payload.get("system_prompt"))
    # backward compatible text only consumers
    return ok(result)


@router.get("/dsl/reverse_translate")
def reverse_translate(dsl_text: str):
    return ok({"text": dsl_to_nl(dsl_text)})


@router.post("/validate")
def api_validate(payload: dict, s: Session = Depends(db_session)):
    rule_id = payload.get("rule_id")
    rule = s.get(Rule, int(rule_id)) if rule_id else None
    return ok(validate_dsl(payload.get("dsl_text", ""), session=s, rule=rule))


@router.post("/{rule_id}/activate/{version_id}")
def activate_rule_version(rule_id: int, version_id: int, s: Session = Depends(db_session)):
    rule = _ensure_rule(s, rule_id)
    _ensure_not_law(rule)
    version = s.get(RuleVersion, version_id)
    if not version or version.rule_id != rule_id:
        raise HTTPException(status_code=404, detail="找不到規則版本")
    rule.dsl_text = version.dsl_text
    rule.nl_text = version.nl_text
    rule.updated_at = datetime.utcnow()
    s.add(rule)
    s.commit()
    s.refresh(rule)
    return ok(rule.model_dump())
