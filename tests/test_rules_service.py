from __future__ import annotations

from textwrap import dedent

from app.services import rules
from app.models.entities import Department, Nurse, Project, Rule, RuleScopeType, RuleType, ShiftCode


def _base_rule_yaml(*, rule_type: str, body: str, scope_type: str = "GLOBAL", scope_id: str | None = None) -> str:
    scope_id_value = "null" if scope_id is None else scope_id
    return dedent(
        f"""
        dsl_version: "1.0"
        id: "R_GLOBAL_001"
        name: "測試規則"
        scope:
          type: {scope_type}
          id: {scope_id_value}
        type: {rule_type}
        priority: 1
        enabled: true
        tags: ["test"]
        notes: "測試"
        {body}
        """
    ).strip()


def test_validate_dsl_success():
    dsl = _base_rule_yaml(
        rule_type="HARD",
        body=dedent(
            """
            constraints:
              - id: "C1"
                name: coverage_required
                params:
                  shift_codes: ["D"]
                  required: 2
            """
        ).strip(),
    )
    result = rules.validate_dsl(dsl)
    assert result["ok"] is True
    assert result["issues"] == []
    assert result["warnings"] == []


def test_validate_dsl_failure_on_invalid_json():
    result = rules.validate_dsl("{not yaml")
    assert result["ok"] is False
    assert any("DSL 解析失敗" in issue for issue in result["issues"])


def test_validate_dsl_forbidden_where_expression():
    dsl = _base_rule_yaml(
        rule_type="HARD",
        body=dedent(
            """
            constraints:
              - id: "C1"
                name: coverage_required
                where: assigned(nurse, day, "N")
                params:
                  shift_codes: ["N"]
                  required: 1
            """
        ).strip(),
    )
    result = rules.validate_dsl(dsl)
    assert result["ok"] is False
    assert any("不允許使用 assigned" in issue for issue in result["issues"])


def test_stream_nl_to_dsl_events_uses_mock_when_no_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    events = list(rules.stream_nl_to_dsl_events("夜班後希望安排休假"))

    tokens = [payload for event, payload in events if event == "token"]
    completed = [payload for event, payload in events if event == "completed"]

    assert tokens, "mock pipeline should stream token chunks"
    assert completed and "dsl_text" in completed[-1], "mock pipeline should yield final DSL text"


def test_dsl_to_nl_generates_human_text():
    dsl = _base_rule_yaml(
        rule_type="HARD",
        body=dedent(
            """
            constraints:
              - id: "C1"
                name: coverage_required
                params:
                  shift_codes: ["D"]
                  required: 2
              - id: "C2"
                name: max_consecutive_work_days
                params:
                  max_days: 3
            """
        ).strip(),
    )
    text = rules.dsl_to_nl(dsl)
    assert "HARD" in text
    assert "coverage_required" in text
    assert "max_consecutive_work_days" in text


def test_validate_dsl_scope_and_shift_reference_errors(test_context):
    with test_context["make_session"]() as session:
        dept = Department(code="ER", name="急診")
        nurse = Nurse(staff_no="N002", name="林小華", department_code="ER", job_level_code="N1")
        session.add(dept)
        session.add(nurse)
        session.add(ShiftCode(code="D", name="白班"))
        session.commit()

        dsl = dedent(
            """
            dsl_version: "1.0"
            id: "R_DEPT_001"
            name: "科別規則"
            scope:
              type: DEPARTMENT
              id: ICU
            type: HARD
            priority: 1
            enabled: true
            constraints:
              - id: "C1"
                name: coverage_required
                params:
                  shift_codes: ["X"]
                  required: 2
              - id: "C2"
                name: rest_after_shift
                params:
                  shift_codes: ["N"]
                  off_code: "Z"
            """
        ).strip()

        result = rules.validate_dsl(dsl, session=session)

    assert result["ok"] is False
    assert any("參照未知班別" in issue for issue in result["issues"])
    assert any("科別不存在" in issue for issue in result["issues"])


def test_validate_dsl_objective_requires_weight():
    dsl = _base_rule_yaml(
        rule_type="SOFT",
        body=dedent(
            """
            objectives:
              - id: "O1"
                name: prefer_off_on_weekends
            """
        ).strip(),
    )
    result = rules.validate_dsl(dsl)
    assert result["ok"] is False
    assert any("必須提供 weight" in issue for issue in result["issues"])


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
            dsl_text=_base_rule_yaml(
                rule_type="HARD",
                body=dedent(
                    """
                    constraints:
                      - id: "C1"
                        name: coverage_required
                        params:
                          shift_codes: ["D"]
                          required: 2
                    """
                ).strip(),
                scope_type="GLOBAL",
                scope_id=None,
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
            dsl_text=_base_rule_yaml(
                rule_type="HARD",
                body=dedent(
                    """
                    constraints:
                      - id: "C1"
                        name: coverage_required
                        params:
                          shift_codes: ["D"]
                          required: 1
                    """
                ).strip(),
                scope_type="DEPARTMENT",
                scope_id=dept.code,
            ),
            is_enabled=True,
        )
        rule_soft = Rule(
            project_id=project.id,
            title="偏好休假",
            scope_type=RuleScopeType.GLOBAL,
            rule_type=RuleType.SOFT,
            priority=1,
            dsl_text=_base_rule_yaml(
                rule_type="SOFT",
                body=dedent(
                    """
                    objectives:
                      - id: "O1"
                        name: prefer_shift
                        weight: 3
                        params:
                          shift_codes: ["N"]
                    """
                ).strip(),
                scope_type="GLOBAL",
                scope_id=None,
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
            dsl_text=_base_rule_yaml(
                rule_type="SOFT",
                body=dedent(
                    """
                    objectives:
                      - id: "O1"
                        name: prefer_shift
                        weight: 5
                        params:
                          shift_codes: ["N"]
                    """
                ).strip(),
                scope_type="NURSE",
                scope_id=nurse.staff_no,
            ),
            is_enabled=True,
        )
        session.add(rule_global)
        session.add(rule_dept_relax)
        session.add(rule_soft)
        session.add(rule_soft_nurse)
        session.commit()

        merged, conflicts = rules.resolve_project_rules(session, project.id)

    coverage_rule = next((c for c in merged if c.name == "coverage_required"), None)
    assert coverage_rule is not None
    assert coverage_rule.params.get("required") == 2
    assert any("覆寫較寬鬆" in c.get("message", "") for c in conflicts)

    prefer_rule = next((c for c in merged if c.name == "prefer_shift"), None)
    assert prefer_rule is not None
    assert prefer_rule.weight == 5
