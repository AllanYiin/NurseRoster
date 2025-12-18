from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.deps import db_session
from app.models.entities import Department, JobLevel, SkillCode, ShiftCode, Nurse
from app.schemas.common import ok

router = APIRouter(prefix="/api/master", tags=["master"])


def _not_found():
    raise HTTPException(status_code=404, detail="找不到資料")


@router.get("/departments")
def list_departments(s: Session = Depends(db_session)):
    rows = s.exec(select(Department).order_by(Department.code)).all()
    return ok([r.model_dump() for r in rows])


@router.post("/departments")
def upsert_department(dep: Department, s: Session = Depends(db_session)):
    obj = None
    if dep.id:
        obj = s.get(Department, dep.id)
    if obj is None and dep.code:
        obj = s.exec(select(Department).where(Department.code == dep.code)).first()
    if obj is None:
        obj = Department(code=dep.code, name=dep.name, is_active=dep.is_active)
    else:
        obj.code = dep.code
        obj.name = dep.name
        obj.is_active = dep.is_active
    s.add(obj)
    s.commit()
    s.refresh(obj)
    return ok(obj.model_dump())


@router.delete("/departments/{dep_id}")
def delete_department(dep_id: int, s: Session = Depends(db_session)):
    obj = s.get(Department, dep_id)
    if not obj:
        _not_found()
    s.delete(obj)
    s.commit()
    return ok(True)


@router.get("/job_levels")
def list_job_levels(s: Session = Depends(db_session)):
    rows = s.exec(select(JobLevel).order_by(JobLevel.priority, JobLevel.code)).all()
    return ok([r.model_dump() for r in rows])


@router.post("/job_levels")
def upsert_job_level(row: JobLevel, s: Session = Depends(db_session)):
    if row.id:
        obj = s.get(JobLevel, row.id)
        if not obj:
            _not_found()
        obj.code = row.code
        obj.name = row.name
        obj.priority = row.priority
        obj.is_active = row.is_active
        s.add(obj)
        s.commit()
        s.refresh(obj)
        return ok(obj.model_dump())
    s.add(row)
    s.commit()
    s.refresh(row)
    return ok(row.model_dump())


@router.delete("/job_levels/{row_id}")
def delete_job_level(row_id: int, s: Session = Depends(db_session)):
    obj = s.get(JobLevel, row_id)
    if not obj:
        _not_found()
    s.delete(obj)
    s.commit()
    return ok(True)


@router.get("/skill_codes")
def list_skill_codes(s: Session = Depends(db_session)):
    rows = s.exec(select(SkillCode).order_by(SkillCode.code)).all()
    return ok([r.model_dump() for r in rows])


@router.post("/skill_codes")
def upsert_skill_code(row: SkillCode, s: Session = Depends(db_session)):
    if row.id:
        obj = s.get(SkillCode, row.id)
        if not obj:
            _not_found()
        obj.code = row.code
        obj.name = row.name
        obj.is_active = row.is_active
        s.add(obj)
        s.commit()
        s.refresh(obj)
        return ok(obj.model_dump())
    s.add(row)
    s.commit()
    s.refresh(row)
    return ok(row.model_dump())


@router.delete("/skill_codes/{row_id}")
def delete_skill_code(row_id: int, s: Session = Depends(db_session)):
    obj = s.get(SkillCode, row_id)
    if not obj:
        _not_found()
    s.delete(obj)
    s.commit()
    return ok(True)


@router.get("/shift_codes")
def list_shift_codes(s: Session = Depends(db_session)):
    rows = s.exec(select(ShiftCode).order_by(ShiftCode.code)).all()
    return ok([r.model_dump() for r in rows])


@router.post("/shift_codes")
def upsert_shift_code(row: ShiftCode, s: Session = Depends(db_session)):
    if row.id:
        obj = s.get(ShiftCode, row.id)
        if not obj:
            _not_found()
        obj.code = row.code
        obj.name = row.name
        obj.start_time = row.start_time
        obj.end_time = row.end_time
        obj.color = row.color
        obj.is_active = row.is_active
        s.add(obj)
        s.commit()
        s.refresh(obj)
        return ok(obj.model_dump())
    s.add(row)
    s.commit()
    s.refresh(row)
    return ok(row.model_dump())


@router.delete("/shift_codes/{row_id}")
def delete_shift_code(row_id: int, s: Session = Depends(db_session)):
    obj = s.get(ShiftCode, row_id)
    if not obj:
        _not_found()
    s.delete(obj)
    s.commit()
    return ok(True)


@router.get("/nurses")
def list_nurses(s: Session = Depends(db_session)):
    rows = s.exec(select(Nurse).order_by(Nurse.department_code, Nurse.staff_no)).all()
    return ok([r.model_dump() for r in rows])


@router.post("/nurses")
def upsert_nurse(row: Nurse, s: Session = Depends(db_session)):
    if row.id:
        obj = s.get(Nurse, row.id)
        if not obj:
            _not_found()
        obj.staff_no = row.staff_no
        obj.name = row.name
        obj.department_code = row.department_code
        obj.job_level_code = row.job_level_code
        obj.skills_csv = row.skills_csv
        obj.is_active = row.is_active
        s.add(obj)
        s.commit()
        s.refresh(obj)
        return ok(obj.model_dump())
    s.add(row)
    s.commit()
    s.refresh(row)
    return ok(row.model_dump())


@router.delete("/nurses/{row_id}")
def delete_nurse(row_id: int, s: Session = Depends(db_session)):
    obj = s.get(Nurse, row_id)
    if not obj:
        _not_found()
    s.delete(obj)
    s.commit()
    return ok(True)
