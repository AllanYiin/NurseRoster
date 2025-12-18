from __future__ import annotations

from datetime import datetime, date
from typing import Optional

from sqlmodel import SQLModel, Field


class Department(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    name: str
    is_active: bool = True


class JobLevel(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    name: str
    priority: int = 0
    is_active: bool = True


class SkillCode(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    name: str
    is_active: bool = True


class ShiftCode(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    name: str
    start_time: str = ""
    end_time: str = ""
    color: str = "#E6EEF9"  # UI hint
    is_active: bool = True


class Nurse(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    staff_no: str = Field(index=True, unique=True)
    name: str
    department_code: str = Field(index=True)
    job_level_code: str = Field(index=True)
    skills_csv: str = ""  # 以逗號儲存 skill codes
    is_active: bool = True


class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    month: str = Field(index=True)  # YYYY-MM
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Assignment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    day: date = Field(index=True)
    nurse_staff_no: str = Field(index=True)
    shift_code: str = ""
    note: str = ""
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Rule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    title: str
    nl_text: str = ""
    dsl_text: str = ""
    is_enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class OptimizationJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    status: str = Field(default="queued", index=True)  # queued/running/succeeded/failed
    progress: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    message: str = ""
