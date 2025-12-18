from __future__ import annotations

from datetime import date, datetime

from app.models.entities import Assignment, JobStatus, OptimizationJob, Project, ProjectSnapshot, Rule
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

        conf = optimization._parse_enabled_rules(session, project.id)

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

        job = OptimizationJob(
            project_id=project.id,
            status=JobStatus.SUCCEEDED,
            progress=100,
            message="完成",
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    updated = optimization.apply_job_result(job_id)
    assert updated is not None
    assert updated.result_version_id is not None

    with test_context["make_session"]() as session:
        snapshot = session.get(ProjectSnapshot, int(updated.result_version_id))
        assert snapshot is not None
        assert snapshot.project_id == updated.project_id
        assert snapshot.snapshot["assignments"]
