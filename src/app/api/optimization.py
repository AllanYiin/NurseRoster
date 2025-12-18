from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import db_session
from app.models.entities import OptimizationJob
from app.schemas.common import ok
from app.services.optimization import stream_job_run, enqueue_job

router = APIRouter(prefix="/api/optim", tags=["optimization"])


class JobCreate(BaseModel):
    project_id: int


@router.post("/jobs")
def create_job(body: JobCreate, s: Session = Depends(db_session)):
    job = enqueue_job(s, body.project_id)
    return ok(job.model_dump())


@router.get("/jobs")
def list_jobs(project_id: int, s: Session = Depends(db_session)):
    jobs = s.exec(select(OptimizationJob).where(OptimizationJob.project_id == project_id).order_by(OptimizationJob.id.desc())).all()
    return ok([j.model_dump() for j in jobs])


@router.get("/jobs/{job_id}")
def get_job(job_id: int, s: Session = Depends(db_session)):
    job = s.get(OptimizationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return ok(job.model_dump())


@router.get("/jobs/{job_id}/stream")
def stream_job(job_id: int):
    gen = stream_job_run(job_id)
    return StreamingResponse(gen, media_type="text/event-stream")
