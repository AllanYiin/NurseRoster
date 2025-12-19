from __future__ import annotations

import json

from app.services import rules
from app.models.entities import Department, Nurse, Project, Rule, RuleScopeType, RuleType, ShiftCode


def test_validate_dsl_success():
    dsl = json.dumps(
        {
            "description": "每日白班至少兩人",
            "constraints": [{"name": "daily_coverage", "shift": "D", "min": 2}],
        }
    )
    result = rules.validate_dsl(dsl)
    assert result["ok"] is True
    assert result["issues"] == []
    assert result["warnings"], "缺少 dsl_version 預期會有 warning"


def test_validate_dsl_failure_on_invalid_json():
    result = rules.validate_dsl("not json")
    assert result["ok"] is False
    assert any("JSON" in issue for issue in result["issues"])


def test_validate_dsl_body_expression_success():
    dsl = json.dumps(
        {
            "dsl_version": "sr-dsl/1.0",
            "category": "hard",
            "body": {
                "type": "constraint",
                "assert": {"op": "AND", "args": [True, {"op": "NOT", "args": [False]}]},
            },
        }
    )
    result = rules.validate_dsl(dsl)
    assert result["ok"] is True
    assert not result["issues"]


def test_validate_dsl_body_with_unsupported_operator():
    dsl = json.dumps(
        {
            "dsl_version": "sr-dsl/1.0",
            "category": "hard",
            "body": {"type": "constraint", "assert": {"op": "POWER", "args": [1, 2]}},
        }
    )
    result = rules.validate_dsl(dsl)
    assert result["ok"] is False
    assert any("未支援的 operator" in issue for issue in result["issues"])


def test_stream_nl_to_dsl_events_uses_mock_when_no_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    events = list(rules.stream_nl_to_dsl_events("夜班後希望安排休假"))

    tokens = [payload for event, payload in events if event == "token"]
    completed = [payload for event, payload in events if event == "completed"]

    assert tokens, "mock pipeline should stream token chunks"
    assert completed and "dsl_text" in completed[-1], "mock pipeline should yield final DSL text"


def test_dsl_to_nl_generates_human_text():
    dsl = json.dumps(
        {
            "description": "測試描述",
            "constraints": [
                {"name": "daily_coverage", "shift": "D", "min": 2},
                {"name": "max_consecutive", "shift": "N", "max_days": 1},
                {"name": "prefer_off_after_night"},
            ],
        }
    )
    text = rules.dsl_to_nl(dsl)
    assert "測試描述" in text
    assert "每天 D 班至少 2 人" in text
    assert "N 班連續不得超過 1 天" in text
    assert "大夜後偏好安排休假" in text


def test_validate_dsl_scope_and_shift_reference_errors(test_context):
    with test_context["make_session"]() as session:
        dept = Department(code="ER", name="急診")
        nurse = Nurse(staff_no="N002", name="林小華", department_code="ER", job_level_code="N1")
        session.add(dept)
        session.add(nurse)
        session.add(ShiftCode(code="D", name="白班"))
        session.commit()

        dsl = json.dumps(
            {
                "dsl_version": "sr-dsl/1.0",
                "scope": {"scope_type": "department", "scope_id": 999},
                "constraints": [
                    {"name": "daily_coverage", "shift": "X", "min": 2},
                    {"name": "prefer_off_after_night", "shift": "N", "params": {"off_code": "Z"}},
                ],
            }
        )

        result = rules.validate_dsl(dsl, session=session)

    assert result["ok"] is False
    assert any("參照未知班別" in issue for issue in result["issues"])
    assert any("科別不存在" in issue for issue in result["issues"])


def test_validate_dsl_soft_body_warns_weight_and_forbidden_function():
    dsl = json.dumps(
        {
            "dsl_version": "sr-dsl/1.0",
            "category": "soft",
            "body": {
                "type": "objective",
                "penalty": {"fn": "format_date", "args": {"date": "2024-01-01"}},
            },
        }
    )
    result = rules.validate_dsl(dsl)
    assert result["ok"] is True
    assert any("建議設定 weight" in warning for warning in result["warnings"])
    assert any("僅供解釋/UI" in warning for warning in result["warnings"])


def test_resolve_project_rules_overrides_and_conflicts(test_context):
    with test_context["make_session"]() as session:
        project = Project(name="覆寫測試", month="2024-01")
        dept = Department(code="ER", name="急診")
        nurse = Nurse(staff_no="N001", name="王小明", department_code="ER", job_level_code="N1")
        session.add(project)
        session.add(dept)
        session.add(nurse)
        session.commit()
        session.refresh(project)
        session.refresh(dept)
        session.refresh(nurse)

        rule_global = Rule(
            project_id=project.id,
            title="全域人力",
            scope_type=RuleScopeType.GLOBAL,
            rule_type=RuleType.HARD,
            priority=1,
            dsl_text=json.dumps(
                {
                    "dsl_version": "sr-dsl/1.0",
                    "constraints": [{"name": "daily_coverage", "shift": "D", "min": 2}],
                }
            ),
            is_enabled=True,
        )
        rule_dept_relax = Rule(
            project_id=project.id,
            title="科別放寬",
            scope_type=RuleScopeType.DEPARTMENT,
            scope_id=dept.id,
            rule_type=RuleType.HARD,
            priority=2,
            dsl_text=json.dumps(
                {
                    "dsl_version": "sr-dsl/1.0",
                    "constraints": [{"name": "daily_coverage", "shift": "D", "min": 1}],
                }
            ),
            is_enabled=True,
        )
        rule_soft = Rule(
            project_id=project.id,
            title="偏好休假",
            scope_type=RuleScopeType.GLOBAL,
            rule_type=RuleType.SOFT,
            priority=1,
            dsl_text=json.dumps(
                {
                    "dsl_version": "sr-dsl/1.0",
                    "constraints": [{"name": "prefer_off_after_night", "shift": "N", "weight": 3}],
                }
            ),
            is_enabled=True,
        )
        rule_soft_nurse = Rule(
            project_id=project.id,
            title="個人偏好",
            scope_type=RuleScopeType.NURSE,
            scope_id=nurse.id,
            rule_type=RuleType.SOFT,
            priority=3,
            dsl_text=json.dumps(
                {
                    "dsl_version": "sr-dsl/1.0",
                    "constraints": [{"name": "prefer_off_after_night", "shift": "N", "weight": 5}],
                }
            ),
            is_enabled=True,
        )
        session.add(rule_global)
        session.add(rule_dept_relax)
        session.add(rule_soft)
        session.add(rule_soft_nurse)
        session.commit()

        merged, conflicts = rules.resolve_project_rules(session, project.id)

    coverage_rule = next((c for c in merged if c.name == "daily_coverage"), None)
    assert coverage_rule is not None
    assert coverage_rule.params.get("min") == 2
    assert any("覆寫較寬鬆" in c.get("message", "") for c in conflicts)

    prefer_rule = next((c for c in merged if c.name == "prefer_off_after_night"), None)
    assert prefer_rule is not None
    assert prefer_rule.weight == 5
