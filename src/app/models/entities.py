from __future__ import annotations

from datetime import datetime, date
from enum import Enum
from typing import Optional

from sqlalchemy import Column, Enum as SAEnum, JSON
from sqlmodel import Field, SQLModel


class RuleScopeType(str, Enum):
    GLOBAL = "GLOBAL"
    HOSPITAL = "HOSPITAL"
    DEPARTMENT = "DEPARTMENT"
    NURSE = "NURSE"


class RuleType(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"
    PREFERENCE = "PREFERENCE"


class ValidationStatus(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class User(SQLModel, table=True):
    model_config = {"use_enum_values": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    name: str
    role: str = Field(default="manager")
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Department(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    name: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class JobLevel(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    name: str
    priority: int = 0
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SkillCode(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    name: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ShiftCode(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    name: str
    start_time: str = ""
    end_time: str = ""
    color: str = "#E6EEF9"  # UI hint
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Nurse(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    staff_no: str = Field(index=True, unique=True)
    name: str
    department_code: str = Field(index=True)
    job_level_code: str = Field(index=True)
    skills_csv: str = ""  # 以逗號儲存 skill codes
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SchedulePeriod(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    start_date: date = Field(index=True)
    end_date: date = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    month: str = Field(index=True)  # YYYY-MM
    schedule_period_id: Optional[int] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ProjectSnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    name: str = ""
    snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Assignment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    day: date = Field(index=True)
    nurse_staff_no: str = Field(index=True)
    shift_code: str = ""
    note: str = ""
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Rule(SQLModel, table=True):
    model_config = {"use_enum_values": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    title: str
    nl_text: str = ""
    dsl_text: str = ""
    scope_type: RuleScopeType = Field(
        default=RuleScopeType.GLOBAL,
        sa_column=Column(SAEnum(RuleScopeType, native_enum=False), index=True),
    )
    scope_id: Optional[int] = Field(default=None, index=True)
    rule_type: RuleType = Field(
        default=RuleType.HARD,
        sa_column=Column(SAEnum(RuleType, native_enum=False), index=True),
    )
    priority: int = 0
    is_enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RuleVersion(SQLModel, table=True):
    model_config = {"use_enum_values": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    rule_id: int = Field(index=True)
    version: int = 1
    nl_text: str = ""
    dsl_text: str = ""
    reverse_translation: str = ""
    validation_status: ValidationStatus = Field(
        default=ValidationStatus.PENDING,
        sa_column=Column(SAEnum(ValidationStatus, native_enum=False), index=True),
    )
    validation_report: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class OptimizationJob(SQLModel, table=True):
    model_config = {"use_enum_values": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    status: JobStatus = Field(
        default=JobStatus.QUEUED,
        sa_column=Column(SAEnum(JobStatus, native_enum=False), index=True),
    )
    progress: int = 0
    parameters: dict = Field(default_factory=dict, sa_column=Column(JSON))
    result_assignment_set_id: Optional[int] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    message: str = ""
