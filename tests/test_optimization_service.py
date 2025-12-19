from __future__ import annotations

import json
from datetime import date, datetime

from sqlmodel import select

from app.models.entities import Assignment, JobStatus, Nurse, OptimizationJob, Project, ProjectSnapshot, Rule
from app.services import optimization


def test_parse_enabled_rules_and_default_coverage(test_context):
    with test_context["make_session"]() as session:
        project = Project(name="解析規則", month="2024-01")
        session.add(project)
        session.commit()
        session.refresh(project)

        rule = Rule(
            project_id=project.id,
            title="需求規則",
            dsl_text='{"constraints":[{"name":"daily_coverage","shift":"D","min":3},{"name":"max_consecutive","shift":"N","max_days":2},{"name":"prefer_off_after_night","weight":5}]}',
            is_enabled=True,
        )
        session.add(rule)
        session.commit()

        conf = optimization._parse_enabled_rules(session, project.id, [])

    assert conf["coverage"]["D"] == 3
    assert conf["max_consecutive"]["N"] == 2
    assert conf["prefer_off_after_night"] == 5

    coverage = optimization._default_coverage(10, ["D", "E", "N"])
    assert coverage["D"] >= 1
    assert coverage["E"] >= 1
    assert coverage["N"] >= 1


def test_enqueue_and_cancel_job(test_context):
    with test_context["make_session"]() as session:
        project = Project(name="Job 測試", month="2024-01")
        session.add(project)
        session.commit()
        session.refresh(project)

        job = optimization.enqueue_job(
            session,
            {"project_id": project.id, "plan_id": "demo", "mode": "strict_hard", "time_limit_seconds": 1},
        )
        assert job.status == JobStatus.QUEUED
        assert job.plan_id == "demo"
        job_id = job.id

    cancelled = optimization.cancel_job(job_id)
    assert cancelled is not None
    assert cancelled.status == JobStatus.CANCELED
    assert cancelled.message == "已取消"


def test_apply_job_result_creates_snapshot(test_context):
    with test_context["make_session"]() as session:
        project = Project(name="套用結果", month="2024-01")
        session.add(project)
        session.commit()
        session.refresh(project)

        session.add(Assignment(project_id=project.id, day=date(2024, 1, 1), nurse_staff_no="N001", shift_code="D"))
        session.commit()

        result_snapshot = ProjectSnapshot(
            project_id=project.id,
            name="result",
            snapshot={"assignments": [{"nurse_staff_no": "N001", "day": "2024-01-01", "shift_code": "N"}]},
        )
        session.add(result_snapshot)
        session.commit()
        session.refresh(result_snapshot)

        job = OptimizationJob(
            project_id=project.id,
            status=JobStatus.SUCCEEDED,
            progress=100,
            message="完成",
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
            result_assignment_set_id=result_snapshot.id,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id
        project_id = project.id

    updated = optimization.apply_job_result(job_id)
    assert updated is not None
    assert updated.parameters.get("last_apply_rollback_id") is not None

    with test_context["make_session"]() as session:
        assignments = session.exec(select(Assignment).where(Assignment.project_id == project_id)).all()
        assert assignments and assignments[0].shift_code == "N"


def test_parse_dsl_rules_for_new_constraints_and_objectives(test_context):
    with test_context["make_session"]() as session:
        project = Project(name="解析 DSL v1.1.3", month="2024-02")
        session.add(project)
        session.commit()
        session.refresh(project)

        session.add_all(
            [
                Nurse(
                    staff_no="N001",
                    name="護理師一",
                    department_code="D1",
                    job_level_code="L1",
                    skills_csv="VENT,ICU",
                ),
                Nurse(
                    staff_no="N002",
                    name="護理師二",
                    department_code="D1",
                    job_level_code="L1",
                    skills_csv="ICU",
                ),
            ]
        )
        session.commit()

        hard_rule = Rule(
            project_id=project.id,
            title="硬性規則",
            dsl_text=json.dumps(
                {
                    "dsl_version": "1.0",
                    "id": "R-HARD",
                    "name": "硬性",
                    "scope": {"type": "GLOBAL", "id": None},
                    "type": "HARD",
                    "priority": 100,
                    "enabled": True,
                    "constraints": [
                        {"id": "C1", "name": "coverage_required", "params": {"shift_codes": ["D"], "required": 2}},
                        {"id": "C2", "name": "max_consecutive_shift", "params": {"shift_codes": ["N"], "max_days": 3}},
                        {"id": "C3", "name": "forbid_transition", "params": {"from": "E", "to": "N"}},
                        {"id": "C4", "name": "rest_after_shift", "params": {"shift_codes": ["N"], "rest_days": 1}},
                        {
                            "id": "C5",
                            "name": "max_assignments_in_window",
                            "params": {"window_days": 3, "max_assignments": 2, "shift_codes": ["D"]},
                        },
                        {
                            "id": "C6",
                            "name": "skill_coverage",
                            "params": {"skill_codes": ["VENT"], "required": 1, "shift_codes": ["D"]},
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            is_enabled=True,
        )
        soft_rule = Rule(
            project_id=project.id,
            title="軟性規則",
            dsl_text=json.dumps(
                {
                    "dsl_version": "1.0",
                    "id": "R-SOFT",
                    "name": "軟性",
                    "scope": {"type": "GLOBAL", "id": None},
                    "type": "SOFT",
                    "priority": 100,
                    "enabled": True,
                    "objectives": [
                        {"id": "O1", "name": "balance_shift_count", "weight": 5, "params": {"shift_codes": ["D"]}},
                        {"id": "O2", "name": "penalize_transition", "weight": 7, "params": {"from": "D", "to": "N"}},
                        {"id": "O3", "name": "prefer_off_on_weekends", "weight": 3},
                        {
                            "id": "O4",
                            "name": "penalize_consecutive_same_shift",
                            "weight": 9,
                            "params": {"shift_codes": ["E"]},
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            is_enabled=True,
        )
        session.add(hard_rule)
        session.add(soft_rule)
        session.commit()

        nurses = session.exec(select(Nurse)).all()
        conf = optimization._parse_enabled_rules(session, project.id, nurses)

    assert conf["coverage"]["D"] == 2
    assert conf["max_consecutive"]["N"] == 3
    assert conf["forbid_sequences"] == [{"from": "E", "to": "N", "staff": None}]
    assert conf["rest_after_shift_rules"][0]["shift_codes"] == ["N"]
    assert conf["max_assignments_in_window"][0]["max_assignments"] == 2
    assert conf["skill_coverage_rules"][0]["required"] == 1
    assert "N001" in conf["skill_coverage_rules"][0]["staff"]
    assert conf["weekend_off_weight"] == 3
    assert conf["avoid_sequences"] == [{"from": "D", "to": "N", "weight": 7}]
    assert conf["balance_shift_rules"][0]["shift_codes"] == ["D"]
    assert conf["consecutive_shift_penalties"][0]["shift_codes"] == ["E"]
