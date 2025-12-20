from __future__ import annotations

from pathlib import Path
from typing import Iterable

import yaml
from sqlmodel import Session, select

from app.models.entities import Rule, RuleScopeType, RuleType
from app.services.rules import get_dsl_id


HOSPITAL_RULES_PATH = Path(__file__).resolve().parents[1] / "resources" / "hospital_hard_rules.yaml"


def _load_hospital_rules_yaml() -> list[dict]:
    raw = yaml.safe_load(HOSPITAL_RULES_PATH.read_text(encoding="utf-8")) or {}
    rules = raw.get("rules") if isinstance(raw, dict) else None
    if not isinstance(rules, list):
        return []
    return [r for r in rules if isinstance(r, dict)]


def _render_rule_templates(*, template: str, hospital_id: int) -> str:
    return template.format_map({"hospital_id": hospital_id}).strip()


def iter_hospital_rule_specs(hospital_id: int) -> Iterable[dict]:
    rules = _load_hospital_rules_yaml()
    for rule in rules:
        title = str(rule.get("title") or "").strip()
        dsl_template = rule.get("dsl_template") or ""
        if not title or not isinstance(dsl_template, str):
            continue
        dsl_text = _render_rule_templates(template=dsl_template, hospital_id=hospital_id)
        yield {
            "title": title,
            "scope_type": RuleScopeType.HOSPITAL,
            "scope_id": hospital_id,
            "rule_type": RuleType.HARD,
            "priority": int(rule.get("priority") or 0),
            "dsl_text": dsl_text,
        }


def ensure_hospital_hard_rules(session: Session, project_id: int, hospital_id: int) -> list[Rule]:
    existing_rules = session.exec(
        select(Rule).where(
            Rule.project_id == project_id,
            Rule.scope_type == RuleScopeType.HOSPITAL,
            Rule.scope_id == hospital_id,
        )
    ).all()
    existing_ids = {get_dsl_id(r.dsl_text) for r in existing_rules if get_dsl_id(r.dsl_text)}

    created: list[Rule] = []
    for spec in iter_hospital_rule_specs(hospital_id):
        dsl_id = get_dsl_id(spec["dsl_text"])
        if dsl_id and dsl_id in existing_ids:
            continue
        rule = Rule(
            project_id=project_id,
            title=spec["title"],
            scope_type=spec["scope_type"],
            scope_id=spec["scope_id"],
            rule_type=spec["rule_type"],
            priority=spec["priority"],
            dsl_text=spec["dsl_text"],
            is_enabled=True,
        )
        session.add(rule)
        created.append(rule)
    if created:
        session.commit()
        for rule in created:
            session.refresh(rule)
    return created
