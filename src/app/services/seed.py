from __future__ import annotations

from sqlmodel import select

from app.db.session import get_session
from app.models.entities import Department, JobLevel, SkillCode, ShiftCode, Nurse, Project


def seed_if_empty() -> None:
    """只在全新資料庫時灌入一份示範資料。"""
    with get_session() as s:
        has_dep = s.exec(select(Department)).first() is not None
        if has_dep:
            return

        deps = [
            Department(code='ER', name='急診'),
            Department(code='ICU', name='加護病房'),
            Department(code='WARD', name='一般病房'),
        ]
        levels = [
            JobLevel(code='N1', name='N1', priority=1),
            JobLevel(code='N2', name='N2', priority=2),
            JobLevel(code='N3', name='N3', priority=3),
        ]
        skills = [
            SkillCode(code='VENT', name='呼吸器'),
            SkillCode(code='IV', name='靜脈注射'),
            SkillCode(code='TRIAGE', name='檢傷'),
        ]
        shifts = [
            ShiftCode(code='D', name='白班', start_time='08:00', end_time='16:00', color='#E7F3FF'),
            ShiftCode(code='E', name='小夜', start_time='16:00', end_time='00:00', color='#FFF4E5'),
            ShiftCode(code='N', name='大夜', start_time='00:00', end_time='08:00', color='#EDE9FE'),
            ShiftCode(code='OFF', name='休假', start_time='', end_time='', color='#F3F4F6'),
        ]
        nurses = [
            Nurse(staff_no='A1001', name='王小美', department_code='ER', job_level_code='N2', skills_csv='TRIAGE,IV'),
            Nurse(staff_no='A1002', name='陳怡君', department_code='ER', job_level_code='N1', skills_csv='TRIAGE'),
            Nurse(staff_no='B2001', name='林志豪', department_code='ICU', job_level_code='N3', skills_csv='VENT,IV'),
            Nurse(staff_no='C3001', name='張雅婷', department_code='WARD', job_level_code='N2', skills_csv='IV'),
        ]

        for x in deps + levels + skills + shifts + nurses:
            s.add(x)
        s.commit()

        # 建立一個預設專案（當月）
        from datetime import datetime
        month = datetime.now().strftime('%Y-%m')
        proj = Project(name='示範專案', month=month)
        s.add(proj)
        s.commit()
PY