from __future__ import annotations

import json

from app.services import rules


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


def test_validate_dsl_failure_on_invalid_json():
    result = rules.validate_dsl("not json")
    assert result["ok"] is False
    assert any("JSON" in issue for issue in result["issues"])


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
