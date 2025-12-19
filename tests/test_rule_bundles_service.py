from __future__ import annotations

from datetime import date

import pytest
from sqlmodel import select

from app.models.entities import (
    Project,
    Rule,
    RuleScopeType,
    RuleType,
    RuleVersion,
    SchedulePeriod,
    Template,
    TemplateRuleLink,
    RuleBundle,
    RuleBundleItem,
)
from app.services import rule_bundles


def _seed_period_and_project(session):
    project = Project(name="Bundle測試", month="2024-01")
    period = SchedulePeriod(
        name="2024-01",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        project_id=None,
    )
    session.add(project)
    session.add(period)
    session.commit()
    session.refresh(project)
    session.refresh(period)
    period.project_id = project.id
    session.add(period)
    session.commit()
    session.refresh(period)
    return project, period


def _create_rule(session, project_id: int, *, scope_type: RuleScopeType, scope_id: int | None, rule_type: RuleType, title: str):
    rule = Rule(
        project_id=project_id,
        title=title,
        scope_type=scope_type,
        scope_id=scope_id,
        rule_type=rule_type,
        priority=1,
        dsl_text='{"dsl_version":"sr-dsl/1.0","constraints":[{"name":"daily_coverage","shift":"D","min":2}]}',
        is_enabled=True,
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


def test_generate_rule_bundle_creates_items_and_validation(test_context):
    with test_context["make_session"]() as session:
        project, period = _seed_period_and_project(session)
        law_rule = _create_rule(
            session,
            project.id,
            scope_type=RuleScopeType.GLOBAL,
            scope_id=None,
            rule_type=RuleType.HARD,
            title="法律規則",
        )
        template_rule = _create_rule(
            session,
            project.id,
            scope_type=RuleScopeType.GLOBAL,
            scope_id=None,
            rule_type=RuleType.SOFT,
            title="模板規則",
        )
        template = Template(name="標準模板", hospital_id=None, department_id=None)
        session.add(template)
        session.commit()
        session.refresh(template)
        link = TemplateRuleLink(template_id=template.id, rule_id=template_rule.id, included=True)
        session.add(link)
        session.commit()

        bundle = rule_bundles.generate_rule_bundle(
            session,
            period_id=period.id,
            project_id=project.id,
            hospital_id=None,
            department_id=None,
            law_rule_ids=[law_rule.id],
            hospital_rule_ids=None,
            template_id=template.id,
            nurse_pref_from_period_id=None,
            validate_only=True,
            nurse_pref_mode="CLONE_LATEST_VERSION",
        )

        items = session.exec(select(RuleBundleItem).where(RuleBundleItem.bundle_id == bundle.id)).all()
        assert items, "應建立規則集項目"
        assert bundle.bundle_sha256, "規則集應計算 hash"
        assert bundle.validation_report_json, "規則集應產出驗證報告"


def test_generate_rule_bundle_clones_latest_nurse_pref_version(test_context):
    with test_context["make_session"]() as session:
        project, period = _seed_period_and_project(session)
        prev_period = SchedulePeriod(
            name="2023-12",
            start_date=date(2023, 12, 1),
            end_date=date(2023, 12, 31),
            project_id=project.id,
        )
        session.add(prev_period)
        session.commit()
        session.refresh(prev_period)

        nurse_pref_rule = _create_rule(
            session,
            project.id,
            scope_type=RuleScopeType.NURSE,
            scope_id=1,
            rule_type=RuleType.SOFT,
            title="個人偏好",
        )
        version = RuleVersion(
            rule_id=nurse_pref_rule.id,
            version=2,
            dsl_text=nurse_pref_rule.dsl_text,
        )
        session.add(version)
        session.commit()
        session.refresh(version)

        prev_bundle = RuleBundle(
            project_id=project.id,
            period_id=prev_period.id,
            hospital_id=None,
            department_id=None,
            name="Prev Bundle",
            bundle_sha256="",
            source_config_json={},
        )
        session.add(prev_bundle)
        session.commit()
        session.refresh(prev_bundle)
        prev_item = RuleBundleItem(
            bundle_id=prev_bundle.id,
            layer="NURSE_PREF",
            rule_id=nurse_pref_rule.id,
            rule_version_id=version.id,
            dsl_sha256=rule_bundles._hash_dsl(version.dsl_text),
            rule_type=nurse_pref_rule.rule_type,
            priority_at_time=nurse_pref_rule.priority,
            enabled_at_time=nurse_pref_rule.is_enabled,
        )
        session.add(prev_item)
        prev_period.active_rule_bundle_id = prev_bundle.id
        session.add(prev_period)
        session.commit()

        bundle = rule_bundles.generate_rule_bundle(
            session,
            period_id=period.id,
            project_id=project.id,
            hospital_id=None,
            department_id=None,
            law_rule_ids=None,
            hospital_rule_ids=None,
            template_id=None,
            nurse_pref_from_period_id=prev_period.id,
            validate_only=True,
            nurse_pref_mode="CLONE_LATEST_VERSION",
        )

        items = session.exec(select(RuleBundleItem).where(RuleBundleItem.bundle_id == bundle.id)).all()
        nurse_pref_item = next((item for item in items if item.layer == "NURSE_PREF"), None)
        assert nurse_pref_item is not None
        assert nurse_pref_item.rule_version_id == version.id


def test_generate_rule_bundle_raises_when_no_rules(test_context):
    with test_context["make_session"]() as session:
        project, period = _seed_period_and_project(session)
        with pytest.raises(ValueError, match="無任何規則可生成規則集"):
            rule_bundles.generate_rule_bundle(
                session,
                period_id=period.id,
                project_id=project.id,
                hospital_id=None,
                department_id=None,
                law_rule_ids=None,
                hospital_rule_ids=None,
                template_id=None,
                nurse_pref_from_period_id=None,
                validate_only=True,
                nurse_pref_mode="CLONE_LATEST_VERSION",
            )
