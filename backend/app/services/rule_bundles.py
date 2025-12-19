from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Iterable, Optional

from sqlmodel import Session, select

from app.models.entities import (
    Project,
    ProjectSnapshot,
    Rule,
    RuleBundle,
    RuleBundleItem,
    RuleScopeType,
    RuleType,
    RuleVersion,
    SchedulePeriod,
    TemplateRuleLink,
    ValidationStatus,
)
from app.services.rules import _merge_constraints, is_law_dsl, load_rule_constraints, load_rule_constraints_from_dsl, validate_dsl

logger = logging.getLogger(__name__)


def _hash_dsl(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _bundle_hash(items: Iterable[RuleBundleItem]) -> str:
    rows = []
    for it in items:
        rows.append(
            "|".join(
                [
                    str(it.layer),
                    str(it.rule_id),
                    str(it.rule_version_id),
                    str(it.dsl_sha256),
                    str(it.rule_type),
                    str(it.priority_at_time),
                    "1" if it.enabled_at_time else "0",
                ]
            )
        )
    payload = "\n".join(sorted(rows))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _latest_rule_version(session: Session, rule_id: int) -> Optional[RuleVersion]:
    return session.exec(select(RuleVersion).where(RuleVersion.rule_id == rule_id).order_by(RuleVersion.version.desc())).first()


def _ensure_rule_version(session: Session, rule: Rule) -> Optional[RuleVersion]:
    version = _latest_rule_version(session, rule.id or 0)
    if version:
        return version
    if not rule.dsl_text:
        return None
    version = RuleVersion(
        rule_id=rule.id or 0,
        version=1,
        nl_text=rule.nl_text,
        dsl_text=rule.dsl_text,
        reverse_translation="",
        validation_status=ValidationStatus.PENDING,
        validation_report={"issues": ["從主檔初始化，尚未驗證"], "warnings": []},
    )
    session.add(version)
    session.commit()
    session.refresh(version)
    return version


def _validate_bundle(
    items: list[RuleBundleItem],
    rules: dict[int, Rule],
    versions: dict[int, RuleVersion],
    session: Session,
) -> tuple[ValidationStatus, dict]:
    issues: list[str] = []
    warnings: list[str] = []
    constraints = []
    for item in items:
        rule = rules.get(item.rule_id)
        version = versions.get(item.rule_version_id)
        if not rule or not version:
            issues.append(f"缺少規則或版本（rule_id={item.rule_id}, version_id={item.rule_version_id}）")
            continue
        validation = validate_dsl(version.dsl_text or "{}", session=session, rule=rule)
        issues.extend(validation.get("issues", []))
        warnings.extend(validation.get("warnings", []))
        parsed, _ = load_rule_constraints_from_dsl(version.dsl_text or "{}", rule, session=session)
        for c in parsed:
            c.priority = item.priority_at_time
            c.rule_id = rule.id
            c.category = item.rule_type.value.lower()
        constraints.extend(parsed)

    _, conflicts = _merge_constraints(constraints)
    for conflict in conflicts:
        warnings.append(f"規則覆寫衝突：{conflict.get('message')}")

    status = ValidationStatus.PASS
    if issues:
        status = ValidationStatus.FAIL
    elif warnings:
        status = ValidationStatus.WARN
    return status, {"issues": issues, "warnings": warnings, "conflicts": conflicts}


def resolve_rule_bundle(session: Session, bundle_id: int) -> tuple[list, list[dict]]:
    bundle = session.get(RuleBundle, bundle_id)
    if not bundle:
        return [], []
    items = session.exec(select(RuleBundleItem).where(RuleBundleItem.bundle_id == bundle_id)).all()
    if not items:
        return [], []
    rule_ids = {it.rule_id for it in items}
    version_ids = {it.rule_version_id for it in items}
    rules = session.exec(select(Rule).where(Rule.id.in_(rule_ids))).all()
    versions = session.exec(select(RuleVersion).where(RuleVersion.id.in_(version_ids))).all()
    rule_map = {r.id: r for r in rules if r.id is not None}
    version_map = {v.id: v for v in versions if v.id is not None}

    constraints = []
    for item in items:
        rule = rule_map.get(item.rule_id)
        version = version_map.get(item.rule_version_id)
        if not rule or not version:
            continue
        validation = validate_dsl(version.dsl_text or "{}", session=session, rule=rule)
        if not validation.get("ok"):
            logger.warning("bundle rule validation failed: rule_id=%s, version_id=%s", item.rule_id, item.rule_version_id)
            continue
        parsed, _ = load_rule_constraints_from_dsl(version.dsl_text or "{}", rule, session=session)
        for c in parsed:
            c.priority = item.priority_at_time
            c.rule_id = rule.id
            c.category = item.rule_type.value.lower()
        constraints.extend(parsed)

    law_rules = session.exec(select(Rule).where(Rule.project_id == bundle.project_id)).all()
    existing_rule_ids = {it.rule_id for it in items}
    for rule in law_rules:
        if rule.id in existing_rule_ids:
            continue
        if not is_law_dsl(rule.dsl_text):
            continue
        if rule.scope_type == RuleScopeType.HOSPITAL and (bundle.hospital_id is None or rule.scope_id != bundle.hospital_id):
            continue
        if rule.scope_type == RuleScopeType.DEPARTMENT and (bundle.department_id is None or rule.scope_id != bundle.department_id):
            continue
        if rule.scope_type == RuleScopeType.NURSE:
            continue
        parsed, validation = load_rule_constraints(rule, session=session)
        if not validation.get("ok"):
            logger.warning("LAW rule validation failed: rule_id=%s", getattr(rule, "id", None))
            continue
        constraints.extend(parsed)

    merged, conflicts = _merge_constraints(constraints)
    return merged, conflicts


def generate_rule_bundle(
    session: Session,
    *,
    period_id: int,
    project_id: int,
    hospital_id: Optional[int],
    department_id: Optional[int],
    law_rule_ids: Optional[list[int]],
    hospital_rule_ids: Optional[list[int]],
    template_id: Optional[int],
    nurse_pref_from_period_id: Optional[int],
    validate_only: bool,
    nurse_pref_mode: str,
) -> RuleBundle:
    period = session.get(SchedulePeriod, period_id)
    if not period:
        raise ValueError("找不到排班期")

    rules = session.exec(select(Rule).where(Rule.project_id == project_id)).all()
    rule_map = {r.id: r for r in rules if r.id}

    def _filter_rules(
        scope_type: RuleScopeType,
        scope_id: Optional[int],
        allow_types: set[RuleType],
        include_ids: Optional[list[int]],
        *,
        include_law_disabled: bool = False,
    ):
        if scope_type == RuleScopeType.HOSPITAL and scope_id is None:
            return []
        result = []
        for r in rules:
            if r.scope_type != scope_type:
                continue
            if scope_id is not None and r.scope_id != scope_id:
                continue
            if r.rule_type not in allow_types:
                continue
            if include_ids is not None and r.id not in include_ids:
                continue
            if not r.is_enabled and not (include_law_disabled and is_law_dsl(r.dsl_text)):
                continue
            result.append(r)
        return result

    law_rules = []
    law_rules.extend(_filter_rules(RuleScopeType.GLOBAL, None, {RuleType.HARD}, law_rule_ids, include_law_disabled=True))
    law_rules.extend(_filter_rules(RuleScopeType.HOSPITAL, hospital_id, {RuleType.HARD}, law_rule_ids, include_law_disabled=True))
    if department_id is not None:
        law_rules.extend(
            _filter_rules(RuleScopeType.DEPARTMENT, department_id, {RuleType.HARD}, law_rule_ids, include_law_disabled=True)
        )
    hospital_rules = _filter_rules(RuleScopeType.HOSPITAL, hospital_id, {RuleType.HARD}, hospital_rule_ids)

    template_rules: list[Rule] = []
    if template_id:
        links = session.exec(select(TemplateRuleLink).where(TemplateRuleLink.template_id == template_id, TemplateRuleLink.included == True)).all()  # noqa: E712
        link_rule_ids = [link.rule_id for link in links if link.rule_id]
        if link_rule_ids:
            template_rules = [rule_map[rid] for rid in link_rule_ids if rid in rule_map and rule_map[rid].scope_type != RuleScopeType.NURSE]

    nurse_pref_items: list[RuleBundleItem] = []
    if nurse_pref_from_period_id:
        prev = session.get(SchedulePeriod, nurse_pref_from_period_id)
        if prev and prev.active_rule_bundle_id:
            prev_items = session.exec(
                select(RuleBundleItem).where(
                    RuleBundleItem.bundle_id == prev.active_rule_bundle_id,
                    RuleBundleItem.layer == "NURSE_PREF",
                )
            ).all()
            if nurse_pref_mode == "CLONE_LATEST_VERSION":
                for it in prev_items:
                    latest = _latest_rule_version(session, it.rule_id)
                    if latest:
                        it.rule_version_id = latest.id
                        it.dsl_sha256 = _hash_dsl(latest.dsl_text or "")
                nurse_pref_items = prev_items
            else:
                nurse_pref_items = prev_items

    items: list[RuleBundleItem] = []
    now = datetime.utcnow()

    def _append_rule_items(layer: str, rule_list: list[Rule]):
        for rule in rule_list:
            if not rule.id:
                continue
            version = _ensure_rule_version(session, rule)
            if not version or not version.id:
                continue
            items.append(
                RuleBundleItem(
                    bundle_id=0,
                    layer=layer,
                    rule_id=rule.id,
                    rule_version_id=version.id,
                    dsl_sha256=_hash_dsl(version.dsl_text or ""),
                    rule_type=rule.rule_type,
                    priority_at_time=rule.priority,
                    enabled_at_time=rule.is_enabled,
                    created_at=now,
                )
            )

    _append_rule_items("LAW", law_rules)
    _append_rule_items("HOSPITAL", hospital_rules)
    _append_rule_items("TEMPLATE", template_rules)
    for it in nurse_pref_items:
        items.append(
            RuleBundleItem(
                bundle_id=0,
                layer="NURSE_PREF",
                rule_id=it.rule_id,
                rule_version_id=it.rule_version_id,
                dsl_sha256=it.dsl_sha256,
                rule_type=it.rule_type,
                priority_at_time=it.priority_at_time,
                enabled_at_time=it.enabled_at_time,
                created_at=now,
            )
        )

    if not items:
        raise ValueError("無任何規則可生成規則集")

    bundle = RuleBundle(
        project_id=project_id,
        period_id=period_id,
        hospital_id=hospital_id,
        department_id=department_id,
        name=f"Period {period_id} Rule Bundle",
        bundle_sha256="",
        source_config_json={
            "law": {"include_rule_ids": law_rule_ids},
            "hospital": {"include_rule_ids": hospital_rule_ids, "hospital_id": hospital_id},
            "template": {"template_id": template_id},
            "nurse_pref": {"from_period_id": nurse_pref_from_period_id, "mode": nurse_pref_mode},
        },
        validation_status=ValidationStatus.PENDING,
        validation_report_json={},
    )
    session.add(bundle)
    session.commit()
    session.refresh(bundle)

    for it in items:
        it.bundle_id = bundle.id or 0
        session.add(it)
    session.commit()

    rule_ids = {it.rule_id for it in items}
    version_ids = {it.rule_version_id for it in items}
    rule_map = {r.id: r for r in session.exec(select(Rule).where(Rule.id.in_(rule_ids))).all() if r.id}
    version_map = {v.id: v for v in session.exec(select(RuleVersion).where(RuleVersion.id.in_(version_ids))).all() if v.id}
    status, report = _validate_bundle(items, rule_map, version_map, session)
    bundle.validation_status = status
    bundle.validation_report_json = report
    bundle.bundle_sha256 = _bundle_hash(items)
    session.add(bundle)
    session.commit()
    session.refresh(bundle)

    if validate_only:
        return bundle

    return bundle


def activate_rule_bundle(session: Session, *, period_id: int, bundle_id: int, label: str | None, create_snapshot: bool) -> RuleBundle:
    period = session.get(SchedulePeriod, period_id)
    bundle = session.get(RuleBundle, bundle_id)
    if not period or not bundle:
        raise ValueError("找不到排班期或規則集")
    period.active_rule_bundle_id = bundle.id
    period.updated_at = datetime.utcnow()
    session.add(period)
    session.commit()

    if create_snapshot:
        project = session.get(Project, period.project_id or bundle.project_id)
        if project:
            snap = ProjectSnapshot(
                project_id=project.id,
                name=label or f"Rule bundle activated {bundle.id}",
                snapshot={
                    "active_rule_bundle_id": bundle.id,
                    "bundle_sha256": bundle.bundle_sha256,
                    "period_id": period.id,
                },
            )
            session.add(snap)
            session.commit()
    session.refresh(bundle)
    return bundle
