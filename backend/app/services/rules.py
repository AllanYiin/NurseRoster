from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Generator, Iterable, List, Optional, Tuple

from sqlmodel import Session, select

from app.models.entities import Department, Nurse, Rule, RuleScopeType, RuleType, ShiftCode, ValidationStatus

logger = logging.getLogger(__name__)

DEFAULT_DSL_VERSION = "sr-dsl/1.0"
ALLOWED_DSL_VERSIONS = {DEFAULT_DSL_VERSION, "sr-dsl/1.1", "sr-dsl/1.1.3"}
WEIGHT_MIN = 1
WEIGHT_MAX = 100
SUPPORTED_OPERATORS = {
    "AND",
    "OR",
    "NOT",
    "XOR",
    "IMPLIES",
    "IFF",
    "EQ",
    "NE",
    "GT",
    "GTE",
    "LT",
    "LTE",
    "IN",
    "BETWEEN",
    "ADD",
    "SUB",
    "MUL",
    "DIV",
    "MOD",
    "ABS",
    "MIN",
    "MAX",
    "CLAMP",
    "ROUND",
    "SET",
    "UNION",
    "INTERSECT",
    "DIFF",
    "SIZE",
    "CONTAINS",
    "DISTINCT",
    "SORT",
    "IF",
    "COALESCE",
    "IS_NULL",
    "FORALL",
    "EXISTS",
    "COUNT_IF",
    "SUM",
    "MIN_OF",
    "MAX_OF",
    "CONCAT",
    "LOWER",
    "UPPER",
    "MATCH",
}
SUPPORTED_FUNCTIONS = {
    "shift_assigned",
    "assigned_shift",
    "is_work_shift",
    "is_off_shift",
    "in_dept",
    "has_rank_at_least",
    "employment_type_is",
    "nurse_is_active",
    "day_of_week",
    "is_weekend",
    "is_holiday",
    "week_of_period",
    "date_add",
    "date_diff_days",
    "count_consecutive_work_days",
    "has_sequence",
    "rest_minutes_between",
    "coverage_count",
    "required_coverage",
    "coverage_shortage",
    "count_shifts_in_period",
    "count_weekend_shifts",
    "deviation_from_mean",
    "penalty_if",
    "penalty_per_occurrence",
    "reward_if",
    "format_date",
    "format_shift",
    "lookup_nurse_name",
    "explain_expr",
}
FORBIDDEN_SOLVER_FUNCTIONS = {
    "MATCH",
    "SORT",
    "format_date",
    "format_shift",
    "lookup_nurse_name",
    "explain_expr",
    "assigned_shift",
}
SUPPORTED_DOMAIN_ITERS = {"NURSES", "DATES", "SHIFTS", "ASSIGNMENTS"}


@dataclass
class RuleConstraint:
    name: str
    category: str
    scope_type: RuleScopeType
    scope_id: Optional[int]
    priority: int
    params: dict = field(default_factory=dict)
    shift_code: Optional[str] = None
    weight: Optional[int] = None
    rule_id: Optional[int] = None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "scope_type": self.scope_type.value if isinstance(self.scope_type, RuleScopeType) else str(self.scope_type),
            "scope_id": self.scope_id,
            "priority": self.priority,
            "shift_code": self.shift_code,
            "weight": self.weight,
            "params": self.params,
            "rule_id": self.rule_id,
        }


def sse_event(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _mock_nl_to_dsl_events(nl_text: str) -> Iterable[Tuple[str, dict]]:
    nl = (nl_text or "").strip()
    yield "status", {"message": "開始轉譯（mock）"}
    time.sleep(0.2)
    dsl = {
        "rule_id": "R1",
        "description": nl or "(空)",
        "scope": {"department": "ER", "month": "*"},
        "constraints": [
            {"type": "hard", "name": "daily_coverage", "shift": "D", "min": 2},
            {"type": "hard", "name": "max_consecutive", "shift": "N", "max_days": 2},
            {"type": "soft", "name": "prefer_off_after_night", "weight": 3},
        ],
    }
    dsl_text = json.dumps(dsl, ensure_ascii=False, indent=2)
    for chunk in dsl_text.splitlines(True):
        yield "token", {"text": chunk}
        time.sleep(0.01)
    yield "completed", {"dsl_text": dsl_text}


def _available_shift_codes(session: Session | None) -> set[str]:
    codes: set[str] = set()
    if session:
        try:
            rows = session.exec(select(ShiftCode.code).where(ShiftCode.is_active == True)).all()  # noqa: E712
            codes.update({c for c in rows if c})
        except Exception:  # pragma: no cover - defensive
            logger.exception("取得班別代碼失敗，改以空集合繼續")
        if codes:
            codes.update({"OFF"})
    return codes


def _parse_scope(obj: dict, rule: Rule | None) -> tuple[RuleScopeType, Optional[int], list[str]]:
    warnings: list[str] = []
    scope_obj = obj.get("scope") if isinstance(obj.get("scope"), dict) else {}
    raw_scope = scope_obj.get("scope_type") or scope_obj.get("type") or (rule.scope_type.value if rule else None) or RuleScopeType.GLOBAL.value
    try:
        scope_type = RuleScopeType(str(raw_scope).upper())
    except Exception:
        warnings.append(f"未知的 scope_type：{raw_scope}，已套用 GLOBAL")
        scope_type = RuleScopeType.GLOBAL

    scope_id = scope_obj.get("scope_id") or scope_obj.get("dept_id") or scope_obj.get("nurse_id") or (rule.scope_id if rule else None)
    try:
        scope_id = int(scope_id) if scope_id is not None else None
    except Exception:
        warnings.append(f"scope_id 必須為數字，取得到 {scope_id}")
        scope_id = None
    return scope_type, scope_id, warnings


def _validate_expr(expr: object, path: str, issues: list[str], warnings: list[str]) -> None:
    if expr is None:
        warnings.append(f"{path} 為 None，已忽略。")
        return
    if isinstance(expr, (bool, int, float, str)):
        return
    if isinstance(expr, list):
        for idx, item in enumerate(expr):
            _validate_expr(item, f"{path}[{idx}]", issues, warnings)
        return
    if not isinstance(expr, dict):
        issues.append(f"{path} 必須為表達式（物件），取得 {type(expr).__name__}。")
        return

    if "op" in expr:
        op = str(expr.get("op", "")).upper()
        if not op:
            issues.append(f"{path}.op 不得為空。")
        elif op not in SUPPORTED_OPERATORS:
            issues.append(f"{path} 未支援的 operator：{op}。")
        args = expr.get("args")
        if args is None:
            issues.append(f"{path}.args 缺少運算元。")
        elif not isinstance(args, list):
            issues.append(f"{path}.args 必須為陣列。")
        else:
            for idx, arg in enumerate(args):
                _validate_expr(arg, f"{path}.args[{idx}]", issues, warnings)
        return

    if "fn" in expr:
        fn = str(expr.get("fn", "")).lower()
        if not fn:
            issues.append(f"{path}.fn 不得為空。")
        elif fn not in SUPPORTED_FUNCTIONS:
            issues.append(f"{path} 未支援的 function：{fn}。")
        if fn in FORBIDDEN_SOLVER_FUNCTIONS:
            warnings.append(f"{path} 使用 {fn} 僅供解釋/UI，不建議進 solver。")
        args = expr.get("args")
        if args is not None and not isinstance(args, dict):
            issues.append(f"{path}.args 必須為物件。")
        elif isinstance(args, dict):
            for key, val in args.items():
                _validate_expr(val, f"{path}.args.{key}", issues, warnings)
        return

    if "iter" in expr:
        iter_val = str(expr.get("iter", "")).upper()
        if iter_val not in SUPPORTED_DOMAIN_ITERS:
            issues.append(f"{path}.iter 未支援的 iterator：{iter_val}。")
        where_expr = expr.get("where")
        if where_expr is not None:
            _validate_expr(where_expr, f"{path}.where", issues, warnings)
        return

    if "lambda" in expr:
        body_expr = expr.get("body")
        _validate_expr(body_expr, f"{path}.body", issues, warnings)
        return

    # 未知物件型態
    warnings.append(f"{path} 為未識別的表達式物件，請確認 DSL 規格。")


def _validate_body(obj: dict, category: str, issues: list[str], warnings: list[str]) -> None:
    body = obj.get("body")
    if body is None:
        return
    if not isinstance(body, dict):
        issues.append("body 必須為 object。")
        return

    body_type = str(body.get("type") or "").lower()
    if not body_type:
        warnings.append("body 缺少 type，預期為 constraint 或 objective。")
    elif body_type not in {"constraint", "objective"}:
        issues.append(f"body.type 僅支援 constraint|objective，取得 {body_type}。")

    when_expr = body.get("when")
    if when_expr is not None:
        _validate_expr(when_expr, "body.when", issues, warnings)

    assert_expr = body.get("assert")
    if body_type == "constraint":
        if assert_expr is None:
            issues.append("body.type=constraint 必須提供 assert。")
        else:
            _validate_expr(assert_expr, "body.assert", issues, warnings)

    penalty_expr = body.get("penalty")
    reward_expr = body.get("reward")
    if body_type == "objective":
        if penalty_expr is None and reward_expr is None:
            issues.append("body.type=objective 必須提供 penalty 或 reward。")
        if penalty_expr is not None:
            _validate_expr(penalty_expr, "body.penalty", issues, warnings)
        if reward_expr is not None:
            _validate_expr(reward_expr, "body.reward", issues, warnings)

    weight_val = body.get("weight")
    if category in ("soft", "preference") and weight_val is None:
        warnings.append("軟性/偏好規則建議設定 weight，用於 penalty/reward 加權。")
    if weight_val is not None and not isinstance(weight_val, (int, float)):
        issues.append(f"body.weight 必須為數字，取得 {weight_val}。")
def _extract_constraints_from_obj(
    obj: dict,
    *,
    fallback_category: str,
    scope_type: RuleScopeType,
    scope_id: Optional[int],
    priority: int,
    rule_id: Optional[int],
) -> tuple[list[RuleConstraint], list[str], list[str]]:
    constraints: list[RuleConstraint] = []
    issues: list[str] = []
    warnings: list[str] = []

    raw_constraints = obj.get("constraints") or obj.get("constraint") or []
    if isinstance(raw_constraints, dict):
        raw_constraints = [raw_constraints]

    if not raw_constraints and "body" not in obj:
        issues.append("constraints 不得為空。")
        return constraints, issues, warnings

    for idx, raw in enumerate(raw_constraints):
        if not isinstance(raw, dict):
            issues.append(f"constraints[{idx}] 必須為 object")
            continue
        params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
        name = (raw.get("name") or raw.get("constraint") or raw.get("type") or params.get("name") or "").strip()
        if not name:
            issues.append(f"constraints[{idx}] 缺少 name")
            continue
        category = str(raw.get("category") or fallback_category or "hard").lower()
        shift_code = (raw.get("shift") or raw.get("shift_code") or params.get("shift") or "").strip() or None
        merged_params = {k: v for k, v in raw.items() if k not in {"name", "category", "type", "constraint", "weight"}}
        merged_params.update(params)
        weight_val = raw.get("weight")
        if weight_val is None and category in ("soft", "preference"):
            warnings.append(f"constraints[{idx}] ({name}) 未指定 weight，已套用預設 1。")
            weight_val = 1
        if weight_val is not None:
            try:
                weight_val = int(weight_val)
                if weight_val < WEIGHT_MIN or weight_val > WEIGHT_MAX:
                    issues.append(
                        f"constraints[{idx}] ({name}) weight 應介於 {WEIGHT_MIN}-{WEIGHT_MAX}，取得 {weight_val}。"
                    )
            except Exception:
                issues.append(f"constraints[{idx}] ({name}) weight 必須為數字。")
                weight_val = None

        if name == "max_consecutive":
            max_days = merged_params.get("max_days") or merged_params.get("max")
            try:
                max_days_int = int(max_days)
                merged_params["max_days"] = max_days_int
                if max_days_int <= 0:
                    issues.append(f"constraints[{idx}] ({name}) max_days 必須大於 0。")
            except Exception:
                issues.append(f"constraints[{idx}] ({name}) 缺少有效的 max_days。")
        elif name == "daily_coverage":
            min_count = merged_params.get("min")
            try:
                min_int = int(min_count)
                merged_params["min"] = min_int
                if min_int <= 0:
                    issues.append(f"constraints[{idx}] ({name}) min 必須大於 0。")
            except Exception:
                issues.append(f"constraints[{idx}] ({name}) 缺少有效的 min。")
        elif name == "min_full_weekends_off_in_window":
            try:
                window_days = int(merged_params.get("window_days"))
                min_full = int(merged_params.get("min_full_weekends_off"))
                merged_params["window_days"] = window_days
                merged_params["min_full_weekends_off"] = min_full
                if window_days <= 0 or min_full <= 0:
                    issues.append(f"constraints[{idx}] ({name}) window_days/min_full_weekends_off 必須大於 0。")
            except Exception:
                issues.append(f"constraints[{idx}] ({name}) 缺少有效的 window_days/min_full_weekends_off。")
        elif name == "min_consecutive_off_days":
            try:
                min_days = int(merged_params.get("min_days"))
                merged_params["min_days"] = min_days
                if min_days <= 1:
                    issues.append(f"constraints[{idx}] ({name}) min_days 必須大於 1。")
            except Exception:
                issues.append(f"constraints[{idx}] ({name}) 缺少有效的 min_days。")
        elif name == "max_work_days_in_rolling_window":
            try:
                window_days = int(merged_params.get("window_days"))
                max_days = int(merged_params.get("max_work_days"))
                merged_params["window_days"] = window_days
                merged_params["max_work_days"] = max_days
                if window_days <= 0 or max_days <= 0:
                    issues.append(f"constraints[{idx}] ({name}) window_days/max_work_days 必須大於 0。")
            except Exception:
                issues.append(f"constraints[{idx}] ({name}) 缺少有效的 window_days/max_work_days。")
        elif name == "max_consecutive_same_shift":
            try:
                max_days = int(merged_params.get("max_days"))
                merged_params["max_days"] = max_days
                if max_days <= 0:
                    issues.append(f"constraints[{idx}] ({name}) max_days 必須大於 0。")
            except Exception:
                issues.append(f"constraints[{idx}] ({name}) 缺少有效的 max_days。")
        elif name == "if_novice_present_then_senior_present":
            try:
                min_senior = int(merged_params.get("min_senior") or 1)
                trigger = int(merged_params.get("trigger_if_novice_count_ge") or 1)
                merged_params["min_senior"] = min_senior
                merged_params["trigger_if_novice_count_ge"] = trigger
                if min_senior <= 0 or trigger <= 0:
                    issues.append(f"constraints[{idx}] ({name}) min_senior/trigger 必須大於 0。")
            except Exception:
                issues.append(f"constraints[{idx}] ({name}) 缺少有效的 min_senior/trigger。")

        constraints.append(
            RuleConstraint(
                name=name,
                category=category,
                scope_type=scope_type,
                scope_id=scope_id,
                priority=priority,
                shift_code=shift_code,
                weight=weight_val,
                params=merged_params,
                rule_id=rule_id,
            )
        )

    return constraints, issues, warnings


def _merge_constraints(constraints: List[RuleConstraint]) -> tuple[List[RuleConstraint], List[dict]]:
    selected: dict[tuple[str, Optional[str]], RuleConstraint] = {}
    conflicts: list[dict] = []

    for c in sorted(constraints, key=lambda x: (_scope_rank(x.scope_type), -int(x.priority or 0))):
        key = (c.name, c.shift_code)
        existing = selected.get(key)

        if existing and _scope_rank(existing.scope_type) == _scope_rank(c.scope_type) and int(c.priority or 0) < int(existing.priority or 0):
            continue

        if c.category == "hard":
            if c.name == "daily_coverage":
                min_required = int(c.params.get("min") or 0)
                if min_required <= 0:
                    continue
                if existing:
                    prev_min = int(existing.params.get("min") or 0)
                    if min_required < prev_min:
                        conflicts.append(
                            {
                                "rule_id": c.rule_id,
                                "name": c.name,
                                "message": f"覆寫較寬鬆（{min_required} < {prev_min}），已保留較嚴格需求",
                            }
                        )
                        continue
                selected[key] = c
            elif c.name == "max_consecutive":
                max_days = int(c.params.get("max_days") or 0)
                if max_days <= 0:
                    continue
                if existing:
                    prev_max = int(existing.params.get("max_days") or 0)
                    if max_days > prev_max > 0:
                        conflicts.append(
                            {
                                "rule_id": c.rule_id,
                                "name": c.name,
                                "message": f"覆寫較寬鬆（{max_days} > {prev_max}），已保留較嚴格上限",
                            }
                        )
                        continue
                selected[key] = c
            else:
                selected[key] = c
        else:
            if existing:
                chosen = existing
                if _scope_rank(c.scope_type) > _scope_rank(existing.scope_type):
                    chosen = c
                elif _scope_rank(c.scope_type) == _scope_rank(existing.scope_type) and int(c.priority or 0) >= int(existing.priority or 0):
                    chosen = c
                weight_candidate = max(int(existing.weight or 0), int(c.weight or 0))
                chosen.weight = weight_candidate if weight_candidate > 0 else chosen.weight
                selected[key] = chosen
            else:
                selected[key] = c

    return list(selected.values()), conflicts


def _scope_rank(scope_type: RuleScopeType | str | None) -> int:
    try:
        st = RuleScopeType(scope_type) if isinstance(scope_type, str) else scope_type
    except Exception:
        st = None
    order = {
        RuleScopeType.GLOBAL: 0,
        RuleScopeType.HOSPITAL: 1,
        RuleScopeType.DEPARTMENT: 2,
        RuleScopeType.NURSE: 3,
    }
    return order.get(st, 0)


def stream_nl_to_dsl_events(nl_text: str) -> Generator[Tuple[str, dict], None, None]:
    """NL→DSL streaming events（後續由 SSE 或 WebSocket 包裝）。

    v1 策略：
    - 若有 OPENAI_API_KEY：使用 OpenAI Responses（streaming）
    - 否則：使用 mock

    注意：本專案預設不要求使用者設定環境變數；若未設定，系統仍可用（mock）。
    """

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_RESPONSES_MODEL", "gpt-4.1")

    if not api_key:
        yield from _mock_nl_to_dsl_events(nl_text)
        return

    # OpenAI streaming
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)

        system = (
            "你是護理排班規則的 DSL 轉譯器。\n"
            "請將使用者的自然語言規則，轉成『JSON 格式』的 DSL。\n"
            "要求：\n"
            "- 根節點為 object\n"
            "- 必須包含 description, constraints(list)\n"
            "- constraints 元素格式：{type: hard|soft|preference, name:..., params...} 或保持與既有樣式相容\n"
            "- 僅輸出 JSON，不要加上多餘說明文字。"
        )

        yield "status", {"message": "開始轉譯（OpenAI）"}

        stream = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": (nl_text or "").strip()},
            ],
            stream=True,
        )

        buf = ""
        for ev in stream:
            # SDK 事件型別可能隨版本略有不同；這裡採最保守取值方式。
            et = getattr(ev, "type", "")
            if et in ("response.output_text.delta", "response.output_text"):
                delta = getattr(ev, "delta", None) or getattr(ev, "text", None) or ""
                if delta:
                    buf += delta
                    yield "token", {"text": delta}
            if et == "response.completed":
                break

        # try normalize
        final = buf.strip()
        if not final:
            yield from _mock_nl_to_dsl_events(nl_text)
            return
        yield "completed", {"dsl_text": final}

    except Exception:
        # 任何例外直接降級，不讓 UI 卡死
        logger.exception("NL→DSL 轉譯失敗，改用 mock。")
        yield from _mock_nl_to_dsl_events(nl_text)


def stream_nl_to_dsl(nl_text: str) -> Generator[str, None, None]:
    """SSE 包裝。"""
    for event, payload in stream_nl_to_dsl_events(nl_text):
        yield sse_event(event, payload)


def dsl_to_nl(dsl_text: str) -> str:
    """v1: DSL→NL（簡化）。"""
    try:
        obj = json.loads(dsl_text)
        scope_type, scope_id, _ = _parse_scope(obj if isinstance(obj, dict) else {}, None)
        fallback_category = str(obj.get("category") or "hard") if isinstance(obj, dict) else "hard"
        priority = int(obj.get("priority") or 0) if isinstance(obj, dict) else 0
        constraints, _, _ = _extract_constraints_from_obj(
            obj if isinstance(obj, dict) else {},
            fallback_category=fallback_category,
            scope_type=scope_type,
            scope_id=scope_id,
            priority=priority,
            rule_id=None,
        )
        desc = obj.get("description", "") if isinstance(obj, dict) else ""
        parts = [f"規則描述：{desc}"] if desc else []
        for c in constraints:
            if c.name == "daily_coverage":
                parts.append(f"每天 {c.shift_code or ''} 班至少 {c.params.get('min')} 人。")
            elif c.name == "max_consecutive":
                parts.append(f"{c.shift_code or ''} 班連續不得超過 {c.params.get('max_days')} 天。")
            elif c.name == "prefer_off_after_night":
                parts.append("大夜後偏好安排休假（軟限制）。")
        return "\n".join(parts) or "無法解析 DSL（請確認格式為 JSON）。"
    except Exception:
        return "無法解析 DSL（請確認格式為 JSON）。"


def dsl_to_nl_with_prompt(dsl_text: str, system_prompt: str | None = None) -> dict:
    """支援自訂 System Prompt 的反向翻譯，若無 LLM 則回退內建摘要。"""
    base_text = dsl_to_nl(dsl_text)
    prompt = (system_prompt or "").strip()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_RESPONSES_MODEL", "gpt-4.1")

    if not prompt:
        return {
            "text": base_text,
            "source": "local",
            "prompt_applied": False,
            "warnings": ["未提供 System Prompt，已使用內建摘要。"],
        }
    if not api_key:
        return {
            "text": base_text,
            "source": "local",
            "prompt_applied": False,
            "warnings": ["未設定 OPENAI_API_KEY，自訂 System Prompt 未套用，已使用內建摘要。"],
        }

    from openai import OpenAI

    try:
        client = OpenAI(api_key=api_key)
        system = prompt + "\n請將輸入的 DSL 轉成清晰的繁體中文規則描述。只輸出轉譯結果，不要補充其他說明。"
        stream = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"請轉寫以下 DSL：\n{dsl_text}"},
            ],
            stream=True,
        )
        buf = ""
        for ev in stream:
            et = getattr(ev, "type", "")
            if et in ("response.output_text.delta", "response.output_text"):
                delta = getattr(ev, "delta", None) or getattr(ev, "text", None) or ""
                buf += delta
            if et == "response.completed":
                break
        final_text = buf.strip() or base_text
        return {
            "text": final_text,
            "source": "llm",
            "prompt_applied": True,
            "warnings": [],
        }
    except Exception:
        logger.exception("DSL→NL (custom prompt) 失敗，已回退內建摘要。")
        return {
            "text": base_text,
            "source": "local",
            "prompt_applied": False,
            "warnings": ["LLM 轉譯失敗，已回退內建摘要。"],
        }


def validate_dsl(dsl_text: str, *, session: Session | None = None, rule: Rule | None = None) -> dict:
    """進階 validator：schema/邏輯/參照完整性/dsl_version 相容性。"""
    issues: list[str] = []
    warnings: list[str] = []
    try:
        obj = json.loads(dsl_text)
    except Exception as e:
        return {"ok": False, "issues": [f"JSON 解析失敗：{e}"], "warnings": []}

    if not isinstance(obj, dict):
        issues.append("根節點必須為 JSON object。")
        return {"ok": False, "issues": issues, "warnings": warnings}

    dsl_version = obj.get("dsl_version")
    if not dsl_version:
        warnings.append(f"缺少 dsl_version，已套用預設 {DEFAULT_DSL_VERSION}。")
        dsl_version = DEFAULT_DSL_VERSION
    if not isinstance(dsl_version, str):
        issues.append("dsl_version 必須為字串。")
        dsl_version = str(dsl_version)
    elif dsl_version not in ALLOWED_DSL_VERSIONS:
        if str(dsl_version).startswith("sr-dsl/"):
            warnings.append(f"dsl_version {dsl_version} 尚未驗證相容性，建議使用 {DEFAULT_DSL_VERSION}。")
        else:
            issues.append(f"dsl_version 不相容：{dsl_version}")

    scope_type, scope_id, scope_warnings = _parse_scope(obj, rule)
    warnings.extend(scope_warnings)

    fallback_category = str(obj.get("category") or (rule.rule_type.value if isinstance(rule, Rule) else RuleType.HARD.value)).lower()
    priority = int(obj.get("priority") or (rule.priority if rule else 0) or 0)
    constraints, constraint_issues, constraint_warnings = _extract_constraints_from_obj(
        obj,
        fallback_category=fallback_category,
        scope_type=scope_type,
        scope_id=scope_id,
        priority=priority,
        rule_id=rule.id if isinstance(rule, Rule) else None,
    )
    issues.extend(constraint_issues)
    warnings.extend(constraint_warnings)

    _validate_body(obj, fallback_category, issues, warnings)

    # referential integrity checks
    shift_codes = _available_shift_codes(session)
    if shift_codes:
        for c in constraints:
            if c.shift_code and c.shift_code not in shift_codes:
                issues.append(f"{c.name} 參照未知班別：{c.shift_code}")
            if c.name == "prefer_off_after_night":
                off_code = str(c.params.get("off_code") or "").strip()
                if off_code and off_code not in shift_codes:
                    issues.append(f"prefer_off_after_night 參照未知班別：{off_code}")

    if session and scope_type == RuleScopeType.DEPARTMENT and scope_id:
        if not session.get(Department, scope_id):
            issues.append(f"scope_id={scope_id} 的科別不存在。")
    if session and scope_type == RuleScopeType.NURSE and scope_id:
        nurse = session.get(Nurse, scope_id) if isinstance(scope_id, int) else None
        if nurse is None:
            issues.append(f"scope_id={scope_id} 的護理師不存在。")

    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "dsl_version": dsl_version,
        "scope": {"scope_type": scope_type.value, "scope_id": scope_id},
        "normalized_constraints": [c.as_dict() for c in constraints],
    }


def _dict_to_constraint(data: dict) -> RuleConstraint:
    scope_raw = data.get("scope_type") or RuleScopeType.GLOBAL.value
    try:
        scope_type = RuleScopeType(scope_raw)
    except Exception:
        scope_type = RuleScopeType.GLOBAL
    return RuleConstraint(
        name=data.get("name", ""),
        category=str(data.get("category") or "hard"),
        scope_type=scope_type,
        scope_id=data.get("scope_id"),
        priority=int(data.get("priority") or 0),
        params=data.get("params") or {},
        shift_code=data.get("shift_code"),
        weight=data.get("weight"),
        rule_id=data.get("rule_id"),
    )


def load_rule_constraints(rule: Rule, session: Session | None = None) -> tuple[list[RuleConstraint], dict]:
    validation = validate_dsl(rule.dsl_text or "{}", session=session, rule=rule)
    constraints = [_dict_to_constraint(d) for d in validation.get("normalized_constraints", [])]
    return constraints, validation


def resolve_project_rules(session: Session, project_id: int) -> tuple[list[RuleConstraint], list[dict]]:
    rules = session.exec(select(Rule).where(Rule.project_id == project_id, Rule.is_enabled == True)).all()  # noqa: E712
    all_constraints: list[RuleConstraint] = []
    for r in rules:
        try:
            constraints, validation = load_rule_constraints(r, session=session)
            if not validation.get("ok"):
                logger.warning("規則驗證失敗 (rule_id=%s)：%s", getattr(r, "id", None), validation.get("issues"))
                continue
            all_constraints.extend(constraints)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("規則解析失敗，已忽略（rule_id=%s）：%s", getattr(r, "id", None), exc)
            continue

    merged, conflicts = _merge_constraints(all_constraints)
    return merged, conflicts
