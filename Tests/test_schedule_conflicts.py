from __future__ import annotations

import json
from datetime import date

from fastapi.testclient import TestClient

from app.models.entities import Assignment, Project, Rule, RuleType


def test_schedule_conflicts_cover_rule(test_context):
    client: TestClient = test_context["make_client"]()
    with test_context["make_session"]() as session:
        project = Project(name="測試專案", month="2024-01")
        session.add(project)
        session.commit()
        session.refresh(project)
        project_id = project.id

        rules_payload = [
            Rule(
                project_id=project_id,
                title="白班人力不足",
                dsl_text=json.dumps({"constraints": [{"name": "daily_coverage", "shift": "D", "min": 2}]}),
                rule_type=RuleType.HARD,
                is_enabled=True,
            ),
            Rule(
                project_id=project_id,
                title="夜班連續限制",
                dsl_text=json.dumps({"constraints": [{"name": "max_consecutive", "shift": "N", "max_days": 1}]}),
                rule_type=RuleType.HARD,
                is_enabled=True,
            ),
            Rule(
                project_id=project_id,
                title="夜班後應排休",
                dsl_text=json.dumps({"constraints": [{"name": "prefer_off_after_night", "shift": "N", "off_code": "OFF"}]}),
                rule_type=RuleType.SOFT,
                is_enabled=True,
            ),
        ]
        for r in rules_payload:
            session.add(r)

        assignments = [
            Assignment(project_id=project_id, day=date(2024, 1, 1), nurse_staff_no="N001", shift_code="D"),
            Assignment(project_id=project_id, day=date(2024, 1, 1), nurse_staff_no="N001", shift_code="N"),
            Assignment(project_id=project_id, day=date(2024, 1, 2), nurse_staff_no="N001", shift_code="N"),
            Assignment(project_id=project_id, day=date(2024, 1, 2), nurse_staff_no="N002", shift_code="D"),
        ]
        for a in assignments:
            session.add(a)
        session.commit()

    resp = client.get(
        "/api/schedule/conflicts",
        params={"project_id": project_id, "start": "2024-01-01", "end": "2024-01-02"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    conflicts = payload["data"]

    assert any("小於需求" in c["message"] and c["severity"] == "error" for c in conflicts)
    assert any("連續" in c["message"] for c in conflicts)
    assert any(c["severity"] == "warn" and c.get("shift_code") == "OFF" for c in conflicts)
