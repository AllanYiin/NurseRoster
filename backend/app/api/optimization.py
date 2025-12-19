from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.api.deps import db_session
from app.models.entities import OptimizationJob, Project, SchedulePeriod
from app.schemas.common import err, ok
from app.services.optimization import apply_job_result, cancel_job, enqueue_job, stream_job_run

router = APIRouter(prefix="/optimization", tags=["optimization"])


class SolverConfig(BaseModel):
    threads: int | None = None
    log_search_progress: bool | None = None


class OptimizationJobRequest(BaseModel):
    project_id: int | None = Field(default=None, description="對應的專案 ID")
    plan_id: str | None = Field(default=None, description="排程 Plan ID")
    base_version_id: str | None = Field(default=None, description="基礎版本，用於 warm start")
    rule_bundle_id: int | None = Field(default=None, description="指定規則集 ID")
    mode: str = Field(default="strict_hard")
    respect_locked: bool = True
    time_limit_seconds: int = 10
    random_seed: int | None = None
    solver_threads: int | None = None
    solver: SolverConfig | None = None
    weights: dict | None = None
    scope_filter: dict | None = None
    output: dict | None = None
    parameters: dict | None = None


@router.post("/jobs")
def create_job(body: OptimizationJobRequest, s: Session = Depends(db_session)):
    payload = body.model_dump()
    if payload.get("rule_bundle_id") is None and body.project_id is not None:
        project = s.get(Project, body.project_id)
        if project and project.schedule_period_id:
            period = s.get(SchedulePeriod, project.schedule_period_id)
            if period and period.active_rule_bundle_id:
                payload["rule_bundle_id"] = period.active_rule_bundle_id
    # backward compatibility
    if body.solver and body.solver_threads is None:
        payload["solver_threads"] = body.solver.threads
    job = enqueue_job(s, payload)
    return ok(job.model_dump())


@router.get("/jobs")
def list_jobs(project_id: int | None = None, plan_id: str | None = None, s: Session = Depends(db_session)):
    stmt = select(OptimizationJob).order_by(OptimizationJob.id.desc())
    if project_id is not None:
        stmt = stmt.where(OptimizationJob.project_id == project_id)
    if plan_id is not None:
        stmt = stmt.where(OptimizationJob.plan_id == plan_id)
    jobs = s.exec(stmt).all()
    return ok([j.model_dump() for j in jobs])


@router.get("/jobs/{job_id}")
def get_job(job_id: int, s: Session = Depends(db_session)):
    job = s.get(OptimizationJob, job_id)
    if not job:
        return JSONResponse(status_code=404, content=err("NOT_FOUND", "job not found"))
    return ok(job.model_dump())


@router.get("/jobs/{job_id}/stream")
def stream_job(job_id: int):
    gen = stream_job_run(job_id)
    return StreamingResponse(gen, media_type="text/event-stream")


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: int):
    job = cancel_job(job_id)
    if not job:
        return JSONResponse(status_code=404, content=err("NOT_FOUND", "job not found"))
    return ok(job.model_dump())


@router.post("/jobs/{job_id}/apply")
def apply(job_id: int):
    job = apply_job_result(job_id)
    if not job:
        return JSONResponse(status_code=404, content=err("NOT_FOUND", "job not found"))
    return ok(job.model_dump())
