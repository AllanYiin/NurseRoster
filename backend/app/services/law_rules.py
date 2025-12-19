from __future__ import annotations

from pathlib import Path
from typing import Iterable

import yaml
from sqlmodel import Session, select

from app.models.entities import Department, Rule, RuleScopeType, RuleType
from app.services.rules import get_dsl_id, is_law_dsl


LAW_RULES_PATH = Path(__file__).resolve().parents[1] / "resources" / "law_rules.yaml"


def _load_law_rules_yaml() -> list[dict]:
    raw = yaml.safe_load(LAW_RULES_PATH.read_text(encoding="utf-8")) or {}
    rules = raw.get("rules") if isinstance(raw, dict) else None
    if not isinstance(rules, list):
        return []
    return [r for r in rules if isinstance(r, dict)]


def _render_rule_templates(*, template: str, department_code: str | None = None) -> str:
    if department_code is None:
        return template.strip()
    return template.format_map({"department_code": department_code}).strip()


def iter_law_rule_specs(session: Session) -> Iterable[dict]:
    departments = session.exec(select(Department)).all()
    rules = _load_law_rules_yaml()
    for rule in rules:
        scope_type = str(rule.get("scope_type") or "GLOBAL").upper()
        title = str(rule.get("title") or "").strip()
        dsl_template = rule.get("dsl_template") or ""
        if not title or not isinstance(dsl_template, str):
            continue
        if scope_type == RuleScopeType.DEPARTMENT.value:
            for dept in departments:
                dsl_text = _render_rule_templates(template=dsl_template, department_code=dept.code)
                yield {
                    "title": title,
                    "scope_type": RuleScopeType.DEPARTMENT,
                    "scope_id": dept.id,
                    "rule_type": RuleType.HARD,
                    "priority": int(rule.get("priority") or 0),
                    "dsl_text": dsl_text,
                }
        else:
            dsl_text = _render_rule_templates(template=dsl_template)
            yield {
                "title": title,
                "scope_type": RuleScopeType(scope_type) if scope_type in RuleScopeType.__members__ else RuleScopeType.GLOBAL,
                "scope_id": None,
                "rule_type": RuleType.HARD,
                "priority": int(rule.get("priority") or 0),
                "dsl_text": dsl_text,
            }


def ensure_law_rules(session: Session, project_id: int) -> list[Rule]:
    existing_rules = session.exec(select(Rule).where(Rule.project_id == project_id)).all()
    existing_law_ids = {
        dsl_id
        for r in existing_rules
        if is_law_dsl(r.dsl_text) and (dsl_id := get_dsl_id(r.dsl_text))
    }

    created: list[Rule] = []
    for spec in iter_law_rule_specs(session):
        dsl_id = get_dsl_id(spec["dsl_text"])
        if dsl_id and dsl_id in existing_law_ids:
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
