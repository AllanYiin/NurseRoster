from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta
from typing import Dict, Generator, List, Tuple

from sqlmodel import Session, select

from app.db.session import get_session
from app.models.entities import Assignment, JobStatus, Nurse, OptimizationJob, Project, Rule, ShiftCode

logger = logging.getLogger(__name__)


def sse_event(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def enqueue_job(session: Session, project_id: int) -> OptimizationJob:
    job = OptimizationJob(project_id=project_id, status=JobStatus.QUEUED, progress=0, message="")
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _parse_enabled_rules(session: Session, project_id: int) -> dict:
    """把已啟用規則的 DSL（JSON）合併成一份簡化的 solver 設定。

    v1 支援：
    - daily_coverage: {shift, min}
    - max_consecutive: {shift, max_days}
    - prefer_off_after_night: soft

    若 DSL 無法解析，會忽略該條規則（但不讓 solver 直接崩潰）。
    """

    conf = {
        "coverage": {},  # shift -> min
        "max_consecutive": {},  # shift -> max_days
        "prefer_off_after_night": 0,  # weight
    }

    rules = session.exec(select(Rule).where(Rule.project_id == project_id, Rule.is_enabled == True)).all()  # noqa: E712
    for r in rules:
        dsl_text = (r.dsl_text or "").strip()
        if not dsl_text:
            continue
        try:
            obj = json.loads(dsl_text)
            constraints = obj.get("constraints") or obj.get("constraint") or []
            if isinstance(constraints, dict):
                constraints = [constraints]
            if not isinstance(constraints, list):
                continue
            for c in constraints:
                if not isinstance(c, dict):
                    continue
                name = c.get("name") or c.get("constraint") or c.get("type")
                if name == "daily_coverage":
                    shift = str(c.get("shift") or "").strip()
                    mn = int(c.get("min") or 0)
                    if shift and mn > 0:
                        conf["coverage"][shift] = max(conf["coverage"].get(shift, 0), mn)
                elif name == "max_consecutive":
                    shift = str(c.get("shift") or "").strip()
                    mx = int(c.get("max_days") or 0)
                    if shift and mx > 0:
                        conf["max_consecutive"][shift] = min(conf["max_consecutive"].get(shift, mx), mx)
                elif name == "prefer_off_after_night":
                    w = int(c.get("weight") or c.get("penalty") or 1)
                    conf["prefer_off_after_night"] = max(conf["prefer_off_after_night"], w)
        except Exception as exc:
            logger.warning("規則 DSL 解析失敗，已忽略（rule_id=%s）：%s", getattr(r, "id", None), exc)
            continue

    return conf


def _default_coverage(n_nurses: int, shift_codes: List[str]) -> Dict[str, int]:
    """v1 預設人力需求（很簡化）。

    若沒有 DSL 指定，先用：
    - D: max(1, ceil(n/4))
    - E: max(1, ceil(n/4))
    - N: max(1, ceil(n/6))
    OFF 無下限。
    """

    def ceil_div(a: int, b: int) -> int:
        return (a + b - 1) // b

    cov = {}
    if "D" in shift_codes:
        cov["D"] = max(1, ceil_div(n_nurses, 4))
    if "E" in shift_codes:
        cov["E"] = max(1, ceil_div(n_nurses, 4))
    if "N" in shift_codes:
        cov["N"] = max(1, ceil_div(n_nurses, 6))
    return cov


def stream_job_run(job_id: int) -> Generator[str, None, None]:
    """SSE：執行最佳化並把結果寫入 assignments。"""

    try:
        with get_session() as s:
            job = s.get(OptimizationJob, job_id)
            if job is None:
                yield sse_event("error", {"message": "找不到 job"})
                return
            job.status = JobStatus.RUNNING
            job.progress = 0
            job.updated_at = datetime.utcnow()
            s.add(job)
            s.commit()

        yield sse_event("status", {"message": "初始化資料..."})

        with get_session() as s:
            job = s.get(OptimizationJob, job_id)
            project = s.get(Project, job.project_id) if job else None
            nurses = s.exec(select(Nurse).where(Nurse.is_active == True).order_by(Nurse.staff_no)).all()  # noqa: E712
            shift_rows = s.exec(select(ShiftCode).where(ShiftCode.is_active == True).order_by(ShiftCode.code)).all()  # noqa: E712
            rules_conf = _parse_enabled_rules(s, job.project_id)

        if not project:
            yield sse_event("error", {"message": "找不到 project"})
            return
        if not nurses:
            yield sse_event("error", {"message": "尚無護理師資料，請先到『資料維護』新增"})
            return

        shift_codes = [x.code for x in shift_rows if x.code] or ["D", "E", "N", "OFF"]
        if "OFF" not in shift_codes:
            shift_codes.append("OFF")

        start = date.today()
        days = [start + timedelta(days=i) for i in range(7)]

        # coverage
        coverage = _default_coverage(len(nurses), shift_codes)
        coverage.update({k: int(v) for k, v in (rules_conf.get("coverage") or {}).items()})

        max_consecutive = {k: int(v) for k, v in (rules_conf.get("max_consecutive") or {}).items()}
        prefer_off_after_night_weight = int(rules_conf.get("prefer_off_after_night") or 0)

        yield sse_event(
            "status",
            {
                "message": "建立模型...",
                "meta": {
                    "days": len(days),
                    "nurses": len(nurses),
                    "shifts": shift_codes,
                    "coverage": coverage,
                    "max_consecutive": max_consecutive,
                },
            },
        )

        # Try OR-Tools
        try:
            from ortools.sat.python import cp_model  # type: ignore
        except Exception:
            yield from _run_fallback_mock(job_id, project.id, nurses, shift_codes, days)
            return

        model = cp_model.CpModel()

        nurse_ids = [n.staff_no for n in nurses]
        idx_n = {n: i for i, n in enumerate(nurse_ids)}
        idx_d = {d: i for i, d in enumerate(days)}
        idx_s = {c: i for i, c in enumerate(shift_codes)}

        # x[n][d][s] in {0,1}
        x = {}
        for n in nurse_ids:
            for d in days:
                for sc in shift_codes:
                    x[(n, d, sc)] = model.NewBoolVar(f"x_{n}_{d.isoformat()}_{sc}")

        # Each nurse each day exactly one shift
        for n in nurse_ids:
            for d in days:
                model.Add(sum(x[(n, d, sc)] for sc in shift_codes) == 1)

        # Coverage constraints
        for d in days:
            for sc, mn in coverage.items():
                if sc not in idx_s:
                    continue
                model.Add(sum(x[(n, d, sc)] for n in nurse_ids) >= int(mn))

        # Max consecutive per shift (if configured)
        for sc, mx in max_consecutive.items():
            if sc not in idx_s or mx <= 0:
                continue
            # For each nurse, for any window of mx+1 days, not all are sc
            for n in nurse_ids:
                for start_i in range(0, len(days) - (mx + 1) + 1):
                    window = days[start_i : start_i + mx + 1]
                    model.Add(sum(x[(n, d, sc)] for d in window) <= mx)

        # Soft: prefer OFF after night
        penalties = []
        if prefer_off_after_night_weight > 0 and "N" in idx_s and "OFF" in idx_s:
            for n in nurse_ids:
                for i in range(len(days) - 1):
                    d = days[i]
                    d2 = days[i + 1]
                    # penalty if N on d and NOT OFF on d2
                    p = model.NewBoolVar(f"pen_{n}_{d.isoformat()}")
                    # p == 1 implies (x[n,d,N]=1 and x[n,d2,OFF]=0)
                    model.Add(x[(n, d, "N")] == 1).OnlyEnforceIf(p)
                    model.Add(x[(n, d2, "OFF")] == 0).OnlyEnforceIf(p)
                    # if p=0, no constraint
                    penalties.append(p)

        # Objective: minimize penalties + variance of night shifts
        objective_terms = []
        if penalties:
            objective_terms.append(prefer_off_after_night_weight * sum(penalties))

        if "N" in idx_s:
            # Minimize range of night shift count among nurses (rough fairness)
            night_counts = []
            for n in nurse_ids:
                c = model.NewIntVar(0, len(days), f"nightcnt_{n}")
                model.Add(c == sum(x[(n, d, "N")] for d in days))
                night_counts.append(c)
            mx = model.NewIntVar(0, len(days), "night_max")
            mn = model.NewIntVar(0, len(days), "night_min")
            model.AddMaxEquality(mx, night_counts)
            model.AddMinEquality(mn, night_counts)
            rng = model.NewIntVar(0, len(days), "night_range")
            model.Add(rng == mx - mn)
            objective_terms.append(5 * rng)

        if objective_terms:
            model.Minimize(sum(objective_terms))

        # Solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 10.0
        solver.parameters.num_search_workers = 8

        yield sse_event("status", {"message": "開始求解（OR-Tools CP-SAT）..."})
        status = solver.Solve(model)

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            yield sse_event("status", {"message": "找不到可行解，改用 mock 產生示範排班。"})
            yield from _run_fallback_mock(job_id, project.id, nurses, shift_codes, days)
            return

        # Write results
        total = len(days) * len(nurse_ids)
        done = 0
        for d in days:
            for n in nurse_ids:
                chosen = ""
                for sc in shift_codes:
                    if solver.Value(x[(n, d, sc)]) == 1:
                        chosen = sc
                        break
                with get_session() as s:
                    q = select(Assignment).where(
                        Assignment.project_id == project.id,
                        Assignment.day == d,
                        Assignment.nurse_staff_no == n,
                    )
                    row = s.exec(q).first()
                    if row is None:
                        row = Assignment(project_id=project.id, day=d, nurse_staff_no=n)
                    row.shift_code = chosen
                    row.updated_at = datetime.utcnow()
                    s.add(row)
                    s.commit()

                done += 1
                progress = int(done * 100 / max(1, total))
                if done % max(1, total // 50) == 0:
                    yield sse_event("progress", {"progress": progress, "message": f"{d} / {n} -> {chosen}"})

        with get_session() as s:
            job = s.get(OptimizationJob, job_id)
            if job:
                job.status = JobStatus.SUCCEEDED
                job.progress = 100
                job.updated_at = datetime.utcnow()
                job.message = "完成"
                s.add(job)
                s.commit()

        yield sse_event("completed", {"job_id": job_id, "status": JobStatus.SUCCEEDED.value})

    except Exception as e:
        logger.exception("最佳化任務失敗，job_id=%s", job_id)
        with get_session() as s:
            job = s.get(OptimizationJob, job_id)
            if job:
                job.status = JobStatus.FAILED
                job.updated_at = datetime.utcnow()
                job.message = f"failed: {e}"
                s.add(job)
                s.commit()
        yield sse_event("error", {"message": f"執行失敗：{e}"})


def _run_fallback_mock(
    job_id: int,
    project_id: int,
    nurses: List[Nurse],
    shift_codes: List[str],
    days: List[date],
) -> Generator[str, None, None]:
    """沒有 OR-Tools 時的降級：以可重現的方式填表，但仍走 streaming + DB。"""

    import random

    random.seed(job_id)
    pool = list(shift_codes)
    if "OFF" not in pool:
        pool.append("OFF")

    yield sse_event("status", {"message": "使用 mock 求解（未安裝 OR-Tools 或不可行）"})

    total = len(days) * len(nurses)
    done = 0
    for d in days:
        for n in nurses:
            sc = random.choice(pool)
            if random.random() < 0.12:
                sc = "OFF"
            with get_session() as s:
                q = select(Assignment).where(
                    Assignment.project_id == project_id,
                    Assignment.day == d,
                    Assignment.nurse_staff_no == n.staff_no,
                )
                row = s.exec(q).first()
                if row is None:
                    row = Assignment(project_id=project_id, day=d, nurse_staff_no=n.staff_no)
                row.shift_code = sc
                row.updated_at = datetime.utcnow()
                s.add(row)
                s.commit()

            done += 1
            progress = int(done * 100 / max(1, total))
            if done % max(1, total // 40) == 0:
                yield sse_event("progress", {"progress": progress, "message": f"{d} / {n.staff_no} -> {sc}"})
            time.sleep(0.01)

    with get_session() as s:
        job = s.get(OptimizationJob, job_id)
        if job:
            job.status = JobStatus.SUCCEEDED
            job.progress = 100
            job.updated_at = datetime.utcnow()
            job.message = "完成（mock）"
            s.add(job)
            s.commit()

    yield sse_event("completed", {"job_id": job_id, "status": JobStatus.SUCCEEDED.value})
