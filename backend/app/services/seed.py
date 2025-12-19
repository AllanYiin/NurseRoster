from __future__ import annotations

import os

from datetime import date, datetime

from sqlmodel import select

from app.db.session import get_session
from app.models.entities import (
    Department,
    JobLevel,
    Nurse,
    Project,
    ProjectSnapshot,
    SchedulePeriod,
    ShiftCode,
    SkillCode,
    User,
)


def seed_if_empty() -> None:
    """只在全新資料庫時灌入一份示範資料。"""
    if os.getenv("SKIP_SEED", "").lower() in {"1", "true", "yes"}:
        return
    with get_session() as s:
        has_dep = s.exec(select(Department)).first() is not None
        if has_dep:
            return

        deps = [
            Department(code="ER", name="急診"),
            Department(code="ICU", name="加護病房"),
            Department(code="WARD", name="一般病房"),
            Department(code="PED", name="小兒科"),
            Department(code="OBS", name="婦產科"),
        ]
        levels = [
            JobLevel(code="N1", name="N1", priority=1),
            JobLevel(code="N2", name="N2", priority=2),
            JobLevel(code="N3", name="N3", priority=3),
            JobLevel(code="N4", name="N4", priority=4),
        ]
        skills = [
            SkillCode(code="VENT", name="呼吸器"),
            SkillCode(code="IV", name="靜脈注射"),
            SkillCode(code="TRIAGE", name="檢傷"),
            SkillCode(code="NICU", name="新生兒照護"),
            SkillCode(code="LDR", name="產房"),
        ]
        shifts = [
            ShiftCode(code="D", name="白班", start_time="08:00", end_time="16:00", color="#E7F3FF"),
            ShiftCode(code="E", name="小夜", start_time="16:00", end_time="00:00", color="#FFF4E5"),
            ShiftCode(code="N", name="大夜", start_time="00:00", end_time="08:00", color="#EDE9FE"),
            ShiftCode(code="OFF", name="休假", start_time="", end_time="", color="#F3F4F6"),
        ]

        nurse_names = [
            "王雅婷",
            "林于婷",
            "陳姿吟",
            "張志豪",
            "李怡萱",
            "黃冠廷",
            "吳品妤",
            "邱柏安",
            "周嘉宏",
            "趙心瑜",
            "簡郁雯",
            "蔡宗翰",
            "劉亭妤",
            "許柏蓁",
            "何庭瑜",
            "江孟勳",
            "朱柏安",
            "郭于庭",
            "葉家瑋",
            "彭于婷",
            "方采潔",
            "洪竣皓",
            "蕭雅筑",
            "賴品妤",
            "鍾家綺",
            "阮姿君",
            "柯郁庭",
            "楊淑惠",
            "羅家豪",
            "戴毓庭",
        ]

        nurse_departments = ["ER", "ICU", "WARD", "PED", "OBS"]
        nurse_levels = ["N1", "N2", "N3", "N4"]
        nurse_skills = {
            "ER": ["TRIAGE", "IV"],
            "ICU": ["VENT", "IV"],
            "WARD": ["IV"],
            "PED": ["NICU", "IV"],
            "OBS": ["LDR", "IV"],
        }

        nurses = []
        for i, name in enumerate(nurse_names, start=1):
            dep = nurse_departments[(i - 1) % len(nurse_departments)]
            level = nurse_levels[(i // 6) % len(nurse_levels)]
            skills_csv = ",".join(nurse_skills.get(dep, ["IV"]))
            staff_no = f"N{1000 + i:03d}"
            nurses.append(
                Nurse(
                    staff_no=staff_no,
                    name=name,
                    department_code=dep,
                    job_level_code=level,
                    skills_csv=skills_csv,
                )
            )

        for x in deps + levels + skills + shifts + nurses:
            s.add(x)
        s.commit()

        # 建立一個預設使用者與排班期間/專案
        admin = User(email="manager@example.com", name="系統管理者", role="manager")
        s.add(admin)
        s.commit()

        start_date = date.today().replace(day=1)
        end_date = date(start_date.year, start_date.month, 28)
        icu = s.exec(select(Department).where(Department.code == "ICU")).first()
        period = SchedulePeriod(
            name=f"{start_date:%Y-%m} 排班周期",
            start_date=start_date,
            end_date=end_date,
            project_id=None,
            hospital_id=1,
            department_id=icu.id if icu else None,
        )
        s.add(period)
        s.commit()

        month = datetime.now().strftime("%Y-%m")
        proj = Project(name="示範專案", month=month, schedule_period_id=period.id)
        s.add(proj)
        s.commit()

        snapshot = ProjectSnapshot(project_id=proj.id, name="初始化快照", snapshot={"version": 1})
        s.add(snapshot)
        s.commit()
