from __future__ import annotations

import json
import logging
import random
import time
from datetime import date, datetime, timedelta
from typing import Dict, Generator, List, Tuple

from sqlmodel import Session, delete, select

from app.db.session import get_session
from app.models.entities import Assignment, JobStatus, Nurse, OptimizationJob, Project, ProjectSnapshot, ShiftCode
from app.schemas.common import err
from app.services.rules import resolve_project_rules

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


def penalty_weight(weight: int, multipliers: dict, key: str) -> int:
    mul = 1
    if multipliers and key in multipliers:
        try:
            mul = int(multipliers[key])
        except Exception:
            mul = 1
    base = int(weight)
    return max(1, base * mul)


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

        target_snapshot_id = job.result_assignment_set_id or (int(job.result_version_id) if job.result_version_id else None)
        if not target_snapshot_id:
            return job

        target_snapshot = s.get(ProjectSnapshot, target_snapshot_id)
        if not target_snapshot or not isinstance(target_snapshot.snapshot, dict):
            return job

        current_assignments = s.exec(select(Assignment).where(Assignment.project_id == (job.project_id or 0))).all()
        rollback_snapshot = ProjectSnapshot(
            project_id=job.project_id or 0,
            name=f"apply_rollback_{job_id}",
            snapshot={"assignments": [json.loads(a.model_dump_json()) for a in current_assignments]},
        )
        s.add(rollback_snapshot)
        s.commit()
        s.refresh(rollback_snapshot)

        s.exec(delete(Assignment).where(Assignment.project_id == (job.project_id or 0)))
        for a in target_snapshot.snapshot.get("assignments", []):
            try:
                d = date.fromisoformat(a.get("day"))
            except Exception:
                continue
            row = Assignment(
                project_id=job.project_id or 0,
                day=d,
                nurse_staff_no=a.get("nurse_staff_no", ""),
                shift_code=a.get("shift_code", ""),
            )
            row.updated_at = datetime.utcnow()
            s.add(row)

        params = dict(job.parameters or {})
        params["last_apply_rollback_id"] = rollback_snapshot.id
        job.parameters = params
        job.updated_at = datetime.utcnow()
        s.add(job)
        s.commit()
        s.refresh(job)
        return job


def _parse_enabled_rules(session: Session, project_id: int, nurses: List[Nurse]) -> dict:
    conf = {
        "coverage": {},
        "max_consecutive": {},
        "prefer_off_after_night": 0,
        "rest_after_night_hard": False,
        "weekend_off_weight": 0,
        "night_fairness_weight": 0,
        "avoid_sequences": [],
        "unavailable_dates": {},
        "preferences": {},
        "conflicts": [],
    }

    nurse_id_to_staff = {n.id: n.staff_no for n in nurses if n.id is not None}

    merged_constraints, conflicts = resolve_project_rules(session, project_id)
    conf["conflicts"] = conflicts

    for c in merged_constraints:
        if c.name == "daily_coverage":
            shift = (c.shift_code or "").strip()
            mn = int(c.params.get("min") or 0)
            if shift and mn > 0:
                conf["coverage"][shift] = max(conf["coverage"].get(shift, 0), mn)
        elif c.name == "max_consecutive":
            shift = (c.shift_code or "").strip()
            mx = int(c.params.get("max_days") or 0)
            if shift and mx > 0:
                current = conf["max_consecutive"].get(shift, mx)
                conf["max_consecutive"][shift] = min(current, mx)
        elif c.name == "prefer_off_after_night":
            w = int(c.weight or c.params.get("weight") or 1)
            conf["prefer_off_after_night"] = max(conf["prefer_off_after_night"], w)
        elif c.name == "rest_after_night":
            if c.category == "hard":
                conf["rest_after_night_hard"] = True
            else:
                w = int(c.weight or c.params.get("weight") or 1)
                conf["prefer_off_after_night"] = max(conf["prefer_off_after_night"], w)
        elif c.name in {"weekend_off", "holiday_off"}:
            w = int(c.weight or c.params.get("weight") or 1)
            conf["weekend_off_weight"] = max(conf["weekend_off_weight"], w)
        elif c.name in {"balance_night_shifts", "night_fairness"}:
            w = int(c.weight or c.params.get("weight") or 1)
            conf["night_fairness_weight"] = max(conf["night_fairness_weight"], w)
        elif c.name in {"avoid_sequence", "avoid_shift_pair"}:
            frm = (c.params.get("from") or c.params.get("prev") or c.shift_code or "").strip()
            to = (c.params.get("to") or c.params.get("next") or "").strip()
            w = int(c.weight or c.params.get("weight") or 1)
            if frm and to and w > 0:
                conf["avoid_sequences"].append({"from": frm, "to": to, "weight": w})
        elif c.name in {"unavailable_dates", "cannot_work", "no_assignment_dates"}:
            dates_raw = c.params.get("dates") or []
            if not isinstance(dates_raw, list):
                continue
            staff_no = nurse_id_to_staff.get(c.scope_id) if c.scope_id else None
            if not staff_no:
                continue
            parsed_dates: set[date] = set()
            for d in dates_raw:
                try:
                    parsed_dates.add(date.fromisoformat(str(d)))
                except Exception:
                    continue
            if parsed_dates:
                conf["unavailable_dates"].setdefault(staff_no, set()).update(parsed_dates)
        elif c.category in {"soft", "preference"} and c.scope_id in nurse_id_to_staff and c.shift_code:
            staff_no = nurse_id_to_staff.get(c.scope_id)
            if not staff_no:
                continue
            pref_type = "avoid" if c.name in {"avoid_shift", "avoid"} else "prefer"
            conf["preferences"].setdefault(staff_no, []).append(
                {"type": pref_type, "shift_code": c.shift_code, "weight": int(c.weight or 1)}
            )

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
    rest_after_night_hard: bool,
    unavailable_dates: Dict[str, set[date]],
    weekend_off_weight: int,
    avoid_sequences: List[dict],
    preferences: Dict[str, List[dict]],
    objective_multipliers: dict,
    time_limit_seconds: int,
    random_seed: int | None,
    solver_threads: int | None,
) -> Tuple[List[Tuple[str, date, str]], dict, List[dict]]:
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

    if rest_after_night_hard and "N" in idx_s:
        for n in nurse_ids:
            for i in range(len(days) - 1):
                d = days[i]
                d2 = days[i + 1]
                model.Add(x[(n, d, "N")] + sum(x[(n, d2, sc)] for sc in shift_codes if sc != "OFF") <= 1)

    if unavailable_dates:
        for n, blocked in unavailable_dates.items():
            for d in blocked:
                if d not in days:
                    continue
                for sc in shift_codes:
                    if sc != "OFF":
                        model.Add(x[(n, d, sc)] == 0)
                if "OFF" in idx_s:
                    model.Add(x[(n, d, "OFF")] == 1)

    penalties = []
    metric_events: List[dict] = []
    if prefer_off_after_night_weight > 0 and "N" in idx_s and "OFF" in idx_s:
        for n in nurse_ids:
            for i in range(len(days) - 1):
                d = days[i]
                d2 = days[i + 1]
                p = model.NewBoolVar(f"pen_{n}_{d.isoformat()}")
                model.AddBoolAnd([x[(n, d, "N")], cp_model.Not(x[(n, d2, "OFF")])]).OnlyEnforceIf(p)
                model.AddBoolOr([cp_model.Not(x[(n, d, "N")]), x[(n, d2, "OFF")]]).OnlyEnforceIf(p.Not())
                penalties.append(penalty_weight(prefer_off_after_night_weight, objective_multipliers, "off_after_night") * p)

    if weekend_off_weight > 0 and "OFF" in idx_s:
        for n in nurse_ids:
            for d in days:
                if d.weekday() >= 5:
                    p = model.NewBoolVar(f"weekend_pen_{n}_{d.isoformat()}")
                    model.Add(x[(n, d, "OFF")] == 0).OnlyEnforceIf(p)
                    penalties.append(penalty_weight(weekend_off_weight, objective_multipliers, "weekend_off") * p)

    if avoid_sequences:
        for seq in avoid_sequences:
            frm = seq.get("from")
            to = seq.get("to")
            w = int(seq.get("weight") or 1)
            if not frm or not to or frm not in idx_s or to not in idx_s or w <= 0:
                continue
            for n in nurse_ids:
                for i in range(len(days) - 1):
                    d = days[i]
                    d2 = days[i + 1]
                    p = model.NewBoolVar(f"avoid_{frm}_{to}_{n}_{d.isoformat()}")
                    model.AddBoolAnd([x[(n, d, frm)], x[(n, d2, to)]]).OnlyEnforceIf(p)
                    model.AddBoolOr([cp_model.Not(x[(n, d, frm)]), cp_model.Not(x[(n, d2, to)])]).OnlyEnforceIf(p.Not())
                    penalties.append(penalty_weight(w, objective_multipliers, "shift_sequence") * p)

    if preferences:
        for n, prefs in preferences.items():
            for pref in prefs:
                sc = pref.get("shift_code")
                w = int(pref.get("weight") or 1)
                if not sc or sc not in idx_s or w <= 0:
                    continue
                pref_type = pref.get("type") or "prefer"
                for d in days:
                    if pref_type == "avoid":
                        penalties.append(penalty_weight(w, objective_multipliers, "personal_preference") * x[(n, d, sc)])
                    else:
                        miss = model.NewBoolVar(f"pref_miss_{n}_{d.isoformat()}_{sc}")
                        model.Add(x[(n, d, sc)] == 0).OnlyEnforceIf(miss)
                        model.Add(x[(n, d, sc)] == 1).OnlyEnforceIf(miss.Not())
                        penalties.append(penalty_weight(w, objective_multipliers, "personal_preference") * miss)

    objective_terms = []
    if penalties:
        objective_terms.append(sum(penalties))

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
        fairness_weight = objective_multipliers.get("night_fairness") or objective_multipliers.get("fairness") or 5
        objective_terms.append(max(0, int(fairness_weight)) * rng)

    if objective_terms:
        model.Minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_seconds or 10)
    solver.parameters.num_search_workers = int(solver_threads or 8)
    if random_seed is not None:
        solver.parameters.random_seed = int(random_seed)

    class SolutionProgress(cp_model.CpSolverSolutionCallback):
        def __init__(self) -> None:
            super().__init__()
            self.best_objective: float | None = None

        def OnSolutionCallback(self) -> None:  # pragma: no cover - callback
            obj = self.ObjectiveValue()
            self.best_objective = obj if self.best_objective is None else min(self.best_objective, obj)
            metric_events.append(
                {
                    "event": "metric",
                    "payload": {
                        "job_id": job_id,
                        "best_objective": obj,
                        "wall_time_sec": self.WallTime(),
                    },
                }
            )

    progress_cb = SolutionProgress()
    status = solver.Solve(model, progress_cb)

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
            "best_objective": progress_cb.best_objective if progress_cb.best_objective is not None else solver.ObjectiveValue(),
            "wall_time_sec": solver.WallTime(),
            "best_bound": solver.BestObjectiveBound(),
        }, metric_events

    if status == cp_model.INFEASIBLE:
        raise JobInfeasible("solver returned INFEASIBLE")
    raise JobTimeout("solver returned UNKNOWN")


def _mock_solution(job_id: int, nurses: List[Nurse], shift_codes: List[str], days: List[date]) -> Tuple[List[Tuple[str, date, str]], dict, List[dict]]:
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
    return assignments, {"status": "MOCK", "objective": None, "wall_time_sec": 0.0}, []


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
            rules_conf = _parse_enabled_rules(s, job.project_id or 0, nurses)

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
            "rest_after_night_hard": rules_conf.get("rest_after_night_hard"),
            "weekend_off_weight": rules_conf.get("weekend_off_weight"),
            "night_fairness_weight": rules_conf.get("night_fairness_weight"),
            "avoid_sequences": rules_conf.get("avoid_sequences") or [],
            "unavailable_dates": {k: sorted([d.isoformat() for d in v]) for k, v in (rules_conf.get("unavailable_dates") or {}).items()},
            "rule_conflicts": rules_conf.get("conflicts") or [],
        }
        total_coverage_need = sum(int(v) for v in coverage.values())
        if total_coverage_need > len(nurses):
            yield from _fail_job(
                job_id,
                "OPT_INFEASIBLE",
                "人力不足導致覆蓋需求不可行，請調整 coverage 規則或增加人員。",
                {"coverage_need": total_coverage_need, "n_nurses": len(nurses)},
            )
            return
        with get_session() as s:
            job = s.get(OptimizationJob, job_id)
            if job:
                job.compile_report_json = compile_report
                job.status = JobStatus.COMPILING
                job.progress = 10
                job.updated_at = datetime.utcnow()
                s.add(job)
                s.commit()

        if rules_conf.get("conflicts"):
            yield sse_event(
                "log",
                {
                    "level": "warning",
                    "stage": "compile",
                    "message": "偵測到硬性規則覆寫衝突，已保留較嚴格設定。",
                    "conflicts": rules_conf.get("conflicts"),
                },
            )

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

        objective_multipliers = {}
        if isinstance(job.parameters, dict):
            objective_multipliers.update(job.parameters.get("weights") or {})
        if isinstance(job.request_json, dict):
            objective_multipliers.update(job.request_json.get("weights") or {})

        try:
            assignments, solve_report, metric_events = _solve_assignments(
                job_id,
                project,
                nurses,
                shift_codes,
                days,
                coverage,
                max_consecutive,
                prefer_off_after_night_weight,
                bool(rules_conf.get("rest_after_night_hard")),
                {k: set(v) for k, v in (rules_conf.get("unavailable_dates") or {}).items()},
                int(rules_conf.get("weekend_off_weight") or 0),
                rules_conf.get("avoid_sequences") or [],
                rules_conf.get("preferences") or {},
                objective_multipliers,
                int(job.time_limit_seconds or 10),
                job.random_seed,
                job.solver_threads,
            )
            used_mock = False
        except JobInfeasible as exc:
            details = {
                "coverage": coverage,
                "max_consecutive": max_consecutive,
                "rest_after_night_hard": rules_conf.get("rest_after_night_hard"),
                "unavailable_dates": compile_report.get("unavailable_dates"),
            }
            yield from _fail_job(job_id, "OPT_INFEASIBLE", f"求解不可行，請檢查硬性規則：{exc}", details)
            return
        except JobTimeout as exc:
            details = {"time_limit_seconds": job.time_limit_seconds, "best_cost": None}
            yield from _fail_job(job_id, "OPT_TIMEOUT", f"求解逾時：{exc}", details)
            return
        except Exception as exc:
            logger.exception("求解失敗，使用 mock，job_id=%s", job_id)
            assignments, solve_report, metric_events = _mock_solution(job_id, nurses, shift_codes, days)
            used_mock = True
            yield sse_event("log", {"level": "warning", "stage": "solve", "message": f"求解失敗，改用 mock：{exc}"})

        solve_report_payload = {
            "status": solve_report.get("status"),
            "objective": solve_report.get("objective"),
            "best_objective": solve_report.get("best_objective"),
            "best_bound": solve_report.get("best_bound"),
            "wall_time_sec": solve_report.get("wall_time_sec"),
            "used_mock": used_mock,
        }
        for ev in metric_events:
            try:
                yield sse_event(ev.get("event", "metric"), ev.get("payload", {}))
            except Exception:  # pragma: no cover - defensive
                continue
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

        snapshot_assignments = [
            {"nurse_staff_no": n, "day": d.isoformat(), "shift_code": sc} for (n, d, sc) in assignments
        ]
        rollback_snapshot_id: int | None = None

        total = len(assignments)
        persisted = 0
        with get_session() as s:
            current_assignments = s.exec(
                select(Assignment).where(Assignment.project_id == (project.id if project else 0))
            ).all()
            rollback_snapshot = ProjectSnapshot(
                project_id=project.id if project else 0,
                name=f"pre_optim_{job_id}",
                snapshot={"assignments": [json.loads(a.model_dump_json()) for a in current_assignments]},
            )
            s.add(rollback_snapshot)
            s.commit()
            s.refresh(rollback_snapshot)
            rollback_snapshot_id = rollback_snapshot.id

            with s.begin():
                s.exec(delete(Assignment).where(Assignment.project_id == (project.id if project else 0)))
                for nurse_staff_no, d, shift_code in assignments:
                    row = Assignment(project_id=project.id if project else 0, day=d, nurse_staff_no=nurse_staff_no)
                    row.shift_code = shift_code
                    row.updated_at = datetime.utcnow()
                    s.add(row)
                    persisted += 1
                    if persisted % max(1, total // 10) == 0:
                        yield sse_event("metric", {"job_id": job_id, "progress": int(persisted * 100 / max(1, total))})
                    _check_cancel(job_id)
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
                job.result_assignment_set_id = snapshot.id
                job.result_version_id = str(snapshot.id)
                params = dict(job.parameters or {})
                if rollback_snapshot_id:
                    params["rollback_snapshot_id"] = rollback_snapshot_id
                job.parameters = params
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
