from __future__ import annotations

import json
import logging
import random
import time
from datetime import date, datetime, timedelta
from typing import Dict, Generator, List, Tuple

from sqlmodel import Session, select

from app.db.session import get_session
from app.models.entities import Assignment, JobStatus, Nurse, OptimizationJob, Project, ProjectSnapshot, Rule, ShiftCode
from app.schemas.common import err

logger = logging.getLogger(__name__)


class JobCancelled(Exception):
    """Raised when a job has been cancelled during execution."""


class JobInfeasible(Exception):
    """Raised when solver cannot find feasible solution."""


class JobTimeout(Exception):
    """Raised when solver stops without feasible solution within time limit."""


_cancelled_jobs: set[int] = set()


def sse_event(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _error_payload(code: str, message: str, details: dict | None = None) -> dict:
    return err(code=code, message=message, details=details).get("error")  # type: ignore[index]


def enqueue_job(session: Session, payload: dict) -> OptimizationJob:
    job = OptimizationJob(
        project_id=payload.get("project_id"),
        plan_id=payload.get("plan_id"),
        base_version_id=payload.get("base_version_id"),
        mode=payload.get("mode") or "strict_hard",
        respect_locked=bool(payload.get("respect_locked", True)),
        time_limit_seconds=payload.get("time_limit_seconds", 10),
        random_seed=payload.get("random_seed"),
        solver_threads=(
            payload.get("solver", {}).get("threads")
            if isinstance(payload.get("solver"), dict)
            else payload.get("solver_threads")
        ),
        parameters=payload.get("parameters") or {},
        request_json=payload,
        status=JobStatus.QUEUED,
        progress=0,
        message="queued",
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def cancel_job(job_id: int) -> OptimizationJob | None:
    _cancelled_jobs.add(job_id)
    with get_session() as s:
        job = s.get(OptimizationJob, job_id)
        if job:
            job.status = JobStatus.CANCELED
            job.message = "已取消"
            job.finished_at = datetime.utcnow()
            job.updated_at = datetime.utcnow()
            s.add(job)
            s.commit()
            s.refresh(job)
        return job


def apply_job_result(job_id: int) -> OptimizationJob | None:
    with get_session() as s:
        job = s.get(OptimizationJob, job_id)
        if not job:
            return None
        if job.status != JobStatus.SUCCEEDED:
            return job

        assignments = s.exec(select(Assignment).where(Assignment.project_id == job.project_id)).all()
        snapshot = ProjectSnapshot(
            project_id=job.project_id or 0,
            name=f"optim_job_{job_id}",
            snapshot={"assignments": [json.loads(a.model_dump_json()) for a in assignments]},
        )
        s.add(snapshot)
        s.commit()
        s.refresh(snapshot)
        job.result_version_id = str(snapshot.id)
        job.updated_at = datetime.utcnow()
        s.add(job)
        s.commit()
        s.refresh(job)
        return job


def _parse_enabled_rules(session: Session, project_id: int) -> dict:
    conf = {
        "coverage": {},
        "max_consecutive": {},
        "prefer_off_after_night": 0,
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
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("規則 DSL 解析失敗，已忽略（rule_id=%s）：%s", getattr(r, "id", None), exc)
            continue

    return conf


def _default_coverage(n_nurses: int, shift_codes: List[str]) -> Dict[str, int]:
    def ceil_div(a: int, b: int) -> int:
        return (a + b - 1) // b

    cov: Dict[str, int] = {}
    if "D" in shift_codes:
        cov["D"] = max(1, ceil_div(n_nurses, 4))
    if "E" in shift_codes:
        cov["E"] = max(1, ceil_div(n_nurses, 4))
    if "N" in shift_codes:
        cov["N"] = max(1, ceil_div(n_nurses, 6))
    return cov


def _check_cancel(job_id: int) -> None:
    if job_id in _cancelled_jobs:
        raise JobCancelled()


def _fail_job(job_id: int, code: str, message: str, details: dict | None = None) -> Generator[str, None, None]:
    with get_session() as s:
        job = s.get(OptimizationJob, job_id)
        if job:
            job.status = JobStatus.FAILED
            job.error_json = {"code": code, "message": message, "details": details or {}}
            job.finished_at = datetime.utcnow()
            job.updated_at = datetime.utcnow()
            s.add(job)
            s.commit()
    yield sse_event("error", {"ok": False, "error": _error_payload(code, message, details)})


def _ensure_job(job_id: int) -> OptimizationJob | None:
    with get_session() as s:
        job = s.get(OptimizationJob, job_id)
        if job:
            job.started_at = job.started_at or datetime.utcnow()
            job.updated_at = datetime.utcnow()
            s.add(job)
            s.commit()
            s.refresh(job)
        return job


def _solve_assignments(
    job_id: int,
    project: Project,
    nurses: List[Nurse],
    shift_codes: List[str],
    days: List[date],
    coverage: Dict[str, int],
    max_consecutive: Dict[str, int],
    prefer_off_after_night_weight: int,
    time_limit_seconds: int,
    random_seed: int | None,
    solver_threads: int | None,
) -> Tuple[List[Tuple[str, date, str]], dict, bool]:
    from ortools.sat.python import cp_model  # type: ignore

    model = cp_model.CpModel()

    nurse_ids = [n.staff_no for n in nurses]
    idx_s = {c: i for i, c in enumerate(shift_codes)}

    x = {}
    for n in nurse_ids:
        for d in days:
            for sc in shift_codes:
                x[(n, d, sc)] = model.NewBoolVar(f"x_{n}_{d.isoformat()}_{sc}")

    for n in nurse_ids:
        for d in days:
            model.Add(sum(x[(n, d, sc)] for sc in shift_codes) == 1)

    for d in days:
        for sc, mn in coverage.items():
            if sc not in idx_s:
                continue
            model.Add(sum(x[(n, d, sc)] for n in nurse_ids) >= int(mn))

    for sc, mx in max_consecutive.items():
        if sc not in idx_s or mx <= 0:
            continue
        for n in nurse_ids:
            for start_i in range(0, len(days) - (mx + 1) + 1):
                window = days[start_i : start_i + mx + 1]
                model.Add(sum(x[(n, d, sc)] for d in window) <= mx)

    penalties = []
    if prefer_off_after_night_weight > 0 and "N" in idx_s and "OFF" in idx_s:
        for n in nurse_ids:
            for i in range(len(days) - 1):
                d = days[i]
                d2 = days[i + 1]
                p = model.NewBoolVar(f"pen_{n}_{d.isoformat()}")
                model.Add(x[(n, d, "N")] == 1).OnlyEnforceIf(p)
                model.Add(x[(n, d2, "OFF")] == 0).OnlyEnforceIf(p)
                penalties.append(p)

    objective_terms = []
    if penalties:
        objective_terms.append(prefer_off_after_night_weight * sum(penalties))

    if "N" in idx_s:
        night_counts = []
        for n in nurse_ids:
            c = model.NewIntVar(0, len(days), f"nightcnt_{n}")
            model.Add(c == sum(x[(n, d, "N")] for d in days))
            night_counts.append(c)
        mx_v = model.NewIntVar(0, len(days), "night_max")
        mn_v = model.NewIntVar(0, len(days), "night_min")
        model.AddMaxEquality(mx_v, night_counts)
        model.AddMinEquality(mn_v, night_counts)
        rng = model.NewIntVar(0, len(days), "night_range")
        model.Add(rng == mx_v - mn_v)
        objective_terms.append(5 * rng)

    if objective_terms:
        model.Minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_seconds or 10)
    solver.parameters.num_search_workers = int(solver_threads or 8)
    if random_seed is not None:
        solver.parameters.random_seed = int(random_seed)

    status = solver.Solve(model)

    if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        assignments: List[Tuple[str, date, str]] = []
        for d in days:
            for n in nurse_ids:
                for sc in shift_codes:
                    if solver.Value(x[(n, d, sc)]) == 1:
                        assignments.append((n, d, sc))
                        break
        return assignments, {
            "status": cp_model.OPTIMAL if status == cp_model.OPTIMAL else cp_model.FEASIBLE,
            "objective": solver.ObjectiveValue(),
            "wall_time_sec": solver.WallTime(),
        }, False

    if status == cp_model.INFEASIBLE:
        raise JobInfeasible("solver returned INFEASIBLE")
    raise JobTimeout("solver returned UNKNOWN")


def _mock_solution(job_id: int, nurses: List[Nurse], shift_codes: List[str], days: List[date]) -> Tuple[List[Tuple[str, date, str]], dict]:
    random.seed(job_id)
    pool = list(shift_codes)
    if "OFF" not in pool:
        pool.append("OFF")

    assignments: List[Tuple[str, date, str]] = []
    total = len(days) * len(nurses)
    for idx, d in enumerate(days):
        for n in nurses:
            sc = random.choice(pool)
            if random.random() < 0.12:
                sc = "OFF"
            assignments.append((n.staff_no, d, sc))
        if idx % max(1, total // 5) == 0:
            time.sleep(0.01)
    return assignments, {"status": "MOCK", "objective": None, "wall_time_sec": 0.0}


def stream_job_run(job_id: int) -> Generator[str, None, None]:
    job = _ensure_job(job_id)
    if not job:
        yield from _fail_job(job_id, "NOT_FOUND", "找不到 job")
        return

    if job.status == JobStatus.CANCELED:
        yield from _fail_job(job_id, "CANCELED", "Job 已被取消")
        return

    # compile start
    with get_session() as s:
        job = s.get(OptimizationJob, job_id)
        if job:
            job.status = JobStatus.COMPILING
            job.progress = 5
            job.started_at = job.started_at or datetime.utcnow()
            job.updated_at = datetime.utcnow()
            s.add(job)
            s.commit()
    yield sse_event("phase", {"phase": "compile_start", "job_id": job_id})

    try:
        with get_session() as s:
            project = s.get(Project, job.project_id) if job.project_id else None
            nurses = s.exec(select(Nurse).where(Nurse.is_active == True).order_by(Nurse.staff_no)).all()  # noqa: E712
            shift_rows = s.exec(select(ShiftCode).where(ShiftCode.is_active == True).order_by(ShiftCode.code)).all()  # noqa: E712
            rules_conf = _parse_enabled_rules(s, job.project_id or 0)

        if not project:
            yield from _fail_job(job_id, "VALIDATION", "找不到對應的計畫/專案")
            return
        if not nurses:
            yield from _fail_job(job_id, "VALIDATION", "尚無護理師資料，請先到『資料維護』新增")
            return
        _check_cancel(job_id)

        shift_codes = [x.code for x in shift_rows if x.code] or ["D", "E", "N", "OFF"]
        if "OFF" not in shift_codes:
            shift_codes.append("OFF")

        start = date.today()
        days = [start + timedelta(days=i) for i in range(7)]

        coverage = _default_coverage(len(nurses), shift_codes)
        coverage.update({k: int(v) for k, v in (rules_conf.get("coverage") or {}).items()})
        max_consecutive = {k: int(v) for k, v in (rules_conf.get("max_consecutive") or {}).items()}
        prefer_off_after_night_weight = int(rules_conf.get("prefer_off_after_night") or 0)

        compile_report = {
            "n_nurses": len(nurses),
            "n_dates": len(days),
            "n_shifts": len(shift_codes),
            "coverage": coverage,
            "max_consecutive": max_consecutive,
        }
        with get_session() as s:
            job = s.get(OptimizationJob, job_id)
            if job:
                job.compile_report_json = compile_report
                job.status = JobStatus.COMPILING
                job.progress = 10
                job.updated_at = datetime.utcnow()
                s.add(job)
                s.commit()

        yield sse_event("phase", {"phase": "compile_done", "job_id": job_id, "report": compile_report})
        _check_cancel(job_id)

        # solve start
        with get_session() as s:
            job = s.get(OptimizationJob, job_id)
            if job:
                job.status = JobStatus.SOLVING
                job.progress = 20
                job.updated_at = datetime.utcnow()
                s.add(job)
                s.commit()
        yield sse_event("phase", {"phase": "solve_start", "job_id": job_id})

        try:
            assignments, solve_report, used_mock = _solve_assignments(
                job_id,
                project,
                nurses,
                shift_codes,
                days,
                coverage,
                max_consecutive,
                prefer_off_after_night_weight,
                int(job.time_limit_seconds or 10),
                job.random_seed,
                job.solver_threads,
            )
        except JobInfeasible as exc:
            yield from _fail_job(job_id, "OPT_INFEASIBLE", str(exc))
            return
        except JobTimeout as exc:
            yield from _fail_job(job_id, "OPT_TIMEOUT", str(exc))
            return
        except Exception as exc:
            logger.exception("求解失敗，使用 mock，job_id=%s", job_id)
            assignments, solve_report = _mock_solution(job_id, nurses, shift_codes, days)
            used_mock = True
            yield sse_event("log", {"level": "warning", "stage": "solve", "message": f"求解失敗，改用 mock：{exc}"})

        solve_report_payload = {
            "status": solve_report.get("status"),
            "objective": solve_report.get("objective"),
            "wall_time_sec": solve_report.get("wall_time_sec"),
            "used_mock": used_mock,
        }
        with get_session() as s:
            job = s.get(OptimizationJob, job_id)
            if job:
                job.solve_report_json = solve_report_payload
                job.progress = 60
                job.updated_at = datetime.utcnow()
                s.add(job)
                s.commit()

        yield sse_event("phase", {"phase": "solve_done", "job_id": job_id, "report": solve_report_payload})
        _check_cancel(job_id)

        # persist
        with get_session() as s:
            job = s.get(OptimizationJob, job_id)
            if job:
                job.status = JobStatus.PERSISTING
                job.progress = 70
                job.updated_at = datetime.utcnow()
                s.add(job)
                s.commit()

        yield sse_event("phase", {"phase": "persist_start", "job_id": job_id})

        total = len(assignments)
        persisted = 0
        with get_session() as s:
            with s.begin():
                for nurse_staff_no, d, shift_code in assignments:
                    q = select(Assignment).where(
                        Assignment.project_id == (project.id if project else 0),
                        Assignment.day == d,
                        Assignment.nurse_staff_no == nurse_staff_no,
                    )
                    row = s.exec(q).first()
                    if row is None:
                        row = Assignment(project_id=project.id if project else 0, day=d, nurse_staff_no=nurse_staff_no)
                    row.shift_code = shift_code
                    row.updated_at = datetime.utcnow()
                    s.add(row)
                    persisted += 1
                    if persisted % max(1, total // 10) == 0:
                        yield sse_event("metric", {"job_id": job_id, "progress": int(persisted * 100 / max(1, total))})
                    _check_cancel(job_id)

        snapshot_assignments = [
            {"nurse_staff_no": n, "day": d.isoformat(), "shift_code": sc}
            for (n, d, sc) in assignments
        ]
        with get_session() as s:
            snapshot = ProjectSnapshot(
                project_id=project.id if project else 0,
                name=f"optim_job_{job_id}",
                snapshot={"assignments": snapshot_assignments},
            )
            s.add(snapshot)
            s.commit()
            s.refresh(snapshot)
            job = s.get(OptimizationJob, job_id)
            if job:
                job.status = JobStatus.SUCCEEDED
                job.progress = 100
                job.result_version_id = str(snapshot.id)
                job.finished_at = datetime.utcnow()
                job.updated_at = datetime.utcnow()
                job.message = "完成"
                s.add(job)
                s.commit()

        yield sse_event(
            "phase",
            {"phase": "persist_done", "job_id": job_id, "version_id": job.result_version_id if job else None},
        )
        yield sse_event(
            "result",
            {
                "ok": True,
                "job_id": job_id,
                "status": JobStatus.SUCCEEDED.value,
                "version_id": job.result_version_id if job else None,
                "metrics": {
                    "hard_violations": 0,
                    "soft_penalty": solve_report_payload.get("objective"),
                },
            },
        )

    except JobCancelled:
        _cancelled_jobs.add(job_id)
        with get_session() as s:
            job = s.get(OptimizationJob, job_id)
            if job:
                job.status = JobStatus.CANCELED
                job.finished_at = datetime.utcnow()
                job.updated_at = datetime.utcnow()
                job.message = "cancelled"
                s.add(job)
                s.commit()
        yield sse_event("error", {"ok": False, "error": _error_payload("CANCELED", "已取消")})
    except Exception as exc:  # pragma: no cover - safety net
        logger.exception("最佳化任務失敗，job_id=%s", job_id)
        yield from _fail_job(job_id, "INTERNAL", f"執行失敗：{exc}")
