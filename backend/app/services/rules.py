from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Generator, Iterable, List, Optional, Tuple

import yaml
from sqlmodel import Session, select

from app.models.entities import Department, Nurse, Rule, RuleScopeType, RuleType, ShiftCode, ValidationStatus

logger = logging.getLogger(__name__)

DEFAULT_DSL_VERSION = "1.0"
WEIGHT_MIN = 0
WEIGHT_MAX = 100000
CONSTRAINT_NAMES = {
    "one_shift_per_day",
    "coverage_required",
    "max_consecutive_work_days",
    "max_consecutive_shift",
    "forbid_transition",
    "rest_after_shift",
    "max_assignments_in_window",
    "max_work_days_in_rolling_window",
    "unavailable_dates",
    "skill_coverage",
    "if_novice_present_then_senior_present",
    "max_consecutive_same_shift",
    "min_consecutive_off_days",
    "weekend_all_or_nothing",
    "min_full_weekends_off_in_window",
}
LEGACY_CONSTRAINT_NAMES = {
    "daily_coverage",
    "max_consecutive",
    "prefer_off_after_night",
    "rest_after_night",
}
OBJECTIVE_NAMES = {
    "balance_shift_count",
    "balance_weekend_shift_count",
    "penalize_transition",
    "prefer_off_on_weekends",
    "prefer_shift",
    "penalize_single_off_day",
    "penalize_consecutive_same_shift",
}
ALLOWED_WHERE_FUNCTIONS = {
    "dept",
    "job_level",
    "has_skill",
    "in_group",
    "date",
    "days_between",
    "is_weekend",
    "dow",
    "rolling_days",
}
FORBIDDEN_WHERE_FUNCTIONS = {
    "assigned",
    "assigned_any",
    "count_assigned",
    "count_work_days",
    "shift_of",
}
SUPPORTED_FOR_EACH = {"nurses", "days", "shifts"}
ALLOWED_DSL_MAJOR = "1."


@dataclass
class RuleConstraint:
    name: str
    category: str
    scope_type: RuleScopeType
    scope_id: Optional[str]
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
    dsl_text = "\n".join(
        [
            "dsl_version: \"1.0\"",
            "id: \"R_GLOBAL_001\"",
            "name: \"每日班別最低人力\"",
            "scope:",
            "  type: GLOBAL",
            "  id: null",
            "type: HARD",
            "priority: 100",
            "enabled: true",
            "tags: [\"coverage\"]",
            f"notes: \"{nl or '(空)'}\"",
            "constraints:",
            "  - id: \"C1\"",
            "    name: coverage_required",
            "    params:",
            "      shift_codes: [\"D\"]",
            "      required: 2",
            "    message: \"每日 D 班至少 2 人\"",
        ]
    )
    for chunk in dsl_text.splitlines(True):
        yield "token", {"text": chunk}
        time.sleep(0.01)
    yield "completed", {"dsl_text": dsl_text}


def _load_dsl_obj(dsl_text: str) -> tuple[dict | None, list[str]]:
    issues: list[str] = []
    try:
        obj = yaml.safe_load(dsl_text or "")
    except Exception as exc:
        return None, [f"DSL 解析失敗：{exc}"]
    if not isinstance(obj, dict):
        issues.append("根節點必須為 YAML/JSON object。")
        return None, issues
    return obj, issues


def _is_legacy_dsl(obj: dict) -> bool:
    return "dsl_version" not in obj and isinstance(obj.get("constraints"), (list, dict))


def _normalize_legacy_dsl(obj: dict, rule: Rule | None) -> dict:
    scope_type = rule.scope_type.value if rule else RuleScopeType.GLOBAL.value
    scope_id = rule.scope_id if rule else None
    rule_id = rule.id if rule and rule.id is not None else "LEGACY_RULE"
    return {
        "dsl_version": DEFAULT_DSL_VERSION,
        "id": str(obj.get("id") or rule_id),
        "name": str(obj.get("name") or obj.get("description") or "未命名規則"),
        "scope": obj.get("scope") or {"type": scope_type, "id": scope_id},
        "type": obj.get("type") or (rule.rule_type.value if rule else RuleType.HARD.value),
        "priority": obj.get("priority") if obj.get("priority") is not None else (rule.priority if rule else 0),
        "enabled": obj.get("enabled") if obj.get("enabled") is not None else (rule.is_enabled if rule else True),
        "tags": obj.get("tags") or [],
        "notes": obj.get("notes") or obj.get("description") or "",
        "constraints": obj.get("constraints") or [],
        "objectives": obj.get("objectives") or [],
    }


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


def _parse_scope(obj: dict, rule: Rule | None) -> tuple[RuleScopeType, Optional[str], list[str]]:
    warnings: list[str] = []
    scope_obj = obj.get("scope") if isinstance(obj.get("scope"), dict) else {}
    raw_scope = scope_obj.get("type") or (rule.scope_type.value if rule else None) or RuleScopeType.GLOBAL.value
    try:
        scope_type = RuleScopeType(str(raw_scope).upper())
    except Exception:
        warnings.append(f"未知的 scope_type：{raw_scope}，已套用 GLOBAL")
        scope_type = RuleScopeType.GLOBAL

    scope_id = scope_obj.get("id") or (rule.scope_id if rule else None)
    if scope_id is not None:
        scope_id = str(scope_id)
    return scope_type, scope_id, warnings
def _validate_where_expression(expr: object, path: str, issues: list[str], warnings: list[str]) -> None:
    if expr is None:
        return
    if not isinstance(expr, str):
        issues.append(f"{path} 必須為字串（Expression）。")
        return
    expr_text = expr.strip()
    if not expr_text:
        warnings.append(f"{path} 為空字串，已忽略。")
        return

    lowered = expr_text.lower()
    for fn in FORBIDDEN_WHERE_FUNCTIONS:
        if re.search(rf"\b{re.escape(fn)}\s*\(", lowered):
            issues.append(f"{path} 不允許使用 {fn}（依賴解或不可編譯）。")
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", expr_text):
        fn_name = match.group(1)
        if fn_name.lower() not in ALLOWED_WHERE_FUNCTIONS:
            warnings.append(f"{path} 出現未知函數：{fn_name}，請確認是否為可用函數。")


def _validate_for_each(value: object, path: str, issues: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        issues.append(f"{path} 必須為字串（iterator）。")
        return
    lowered = value.strip().lower()
    if lowered in SUPPORTED_FOR_EACH:
        return
    if lowered.startswith("rolling_days(") and lowered.endswith(")"):
        return
    issues.append(f"{path} 未支援的 iterator：{value}。請使用 nurses/days/shifts/rolling_days(...)")


def _extract_constraints_from_obj(
    obj: dict,
    *,
    rule_type: RuleType,
    scope_type: RuleScopeType,
    scope_id: Optional[str],
    priority: int,
    rule_id: Optional[int],
    legacy_mode: bool = False,
) -> tuple[list[RuleConstraint], list[str], list[str]]:
    constraints: list[RuleConstraint] = []
    issues: list[str] = []
    warnings: list[str] = []

    raw_constraints = obj.get("constraints") or []
    raw_objectives = obj.get("objectives") or []

    if isinstance(raw_constraints, dict):
        raw_constraints = [raw_constraints]
    if isinstance(raw_objectives, dict):
        raw_objectives = [raw_objectives]

    if not legacy_mode:
        if rule_type == RuleType.HARD and not raw_constraints:
            issues.append("type=HARD 時 constraints 不得為空。")
        if rule_type in (RuleType.SOFT, RuleType.PREFERENCE) and not raw_objectives:
            issues.append("type=SOFT/PREFERENCE 時 objectives 不得為空。")
        if rule_type == RuleType.HARD and raw_objectives:
            warnings.append("type=HARD 時仍提供 objectives，已忽略。")
        if rule_type in (RuleType.SOFT, RuleType.PREFERENCE) and raw_constraints:
            warnings.append("type=SOFT/PREFERENCE 時仍提供 constraints，已忽略。")

    items: list[tuple[str, dict, int]] = []
    if legacy_mode and raw_constraints:
        items = [("constraints", item, idx) for idx, item in enumerate(raw_constraints)]
    elif rule_type == RuleType.HARD:
        items = [("constraints", item, idx) for idx, item in enumerate(raw_constraints)]
    else:
        items = [("objectives", item, idx) for idx, item in enumerate(raw_objectives)]

    for prefix, raw, idx in items:
        if not isinstance(raw, dict):
            issues.append(f"{prefix}[{idx}] 必須為 object。")
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            issues.append(f"{prefix}[{idx}] 缺少 name。")
            continue
        if prefix == "constraints" and name not in (CONSTRAINT_NAMES | LEGACY_CONSTRAINT_NAMES):
            issues.append(f"{prefix}[{idx}] 未支援的 constraint name：{name}。")
        if prefix == "objectives" and name not in OBJECTIVE_NAMES:
            issues.append(f"{prefix}[{idx}] 未支援的 objective name：{name}。")

        params = raw.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            issues.append(f"{prefix}[{idx}].params 必須為 object。")
            params = {}

        for_each = raw.get("for_each")
        _validate_for_each(for_each, f"{prefix}[{idx}].for_each", issues)

        where_expr = raw.get("where")
        _validate_where_expression(where_expr, f"{prefix}[{idx}].where", issues, warnings)

        weight_val = raw.get("weight")
        if prefix == "objectives":
            if weight_val is None:
                issues.append(f"{prefix}[{idx}] 必須提供 weight。")
            else:
                try:
                    weight_val = int(weight_val)
                    if weight_val < WEIGHT_MIN or weight_val > WEIGHT_MAX:
                        issues.append(
                            f"{prefix}[{idx}] weight 應介於 {WEIGHT_MIN}-{WEIGHT_MAX}，取得 {weight_val}。"
                        )
                except Exception:
                    issues.append(f"{prefix}[{idx}] weight 必須為數字。")
                    weight_val = None

        legacy_param_keys = {
            "shift",
            "shift_code",
            "shift_codes",
            "min",
            "max",
            "max_days",
            "required",
            "off_code",
            "weight",
        }
        if legacy_mode:
            for key in legacy_param_keys:
                if key in raw and key not in params:
                    params[key] = raw.get(key)

        merged_params = {
            **params,
            "for_each": for_each,
            "where": where_expr,
            "message": raw.get("message"),
        }
        shift_code = (
            merged_params.get("shift_code")
            or merged_params.get("shift")
            or (merged_params.get("shift_codes") or [None])[0]
        )
        if isinstance(shift_code, str):
            shift_code = shift_code.strip() or None
        else:
            shift_code = None

        constraints.append(
            RuleConstraint(
                name=name,
                category=rule_type.value.lower(),
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
            if c.name == "coverage_required":
                min_required = int(c.params.get("required") or 0)
                if min_required <= 0:
                    continue
                if existing:
                    prev_min = int(existing.params.get("required") or 0)
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
            elif c.name in {"max_consecutive_work_days", "max_consecutive_shift", "max_consecutive_same_shift"}:
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
            "請將使用者的自然語言規則，轉成『YAML 格式』的 DSL。\n"
            "要求：\n"
            "- 根節點為 object\n"
            "- 必須包含 dsl_version, id, name, scope, type, priority, enabled\n"
            "- HARD 使用 constraints；SOFT/PREFERENCE 使用 objectives\n"
            "- where 僅用於展開過濾，不得使用依賴解的函數\n"
            "- 僅輸出 YAML，不要加上多餘說明文字。"
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
    obj, issues = _load_dsl_obj(dsl_text)
    if issues or not obj:
        return "無法解析 DSL（請確認格式為 YAML）。"

    legacy_mode = _is_legacy_dsl(obj)
    if legacy_mode:
        obj = _normalize_legacy_dsl(obj, None)

    scope_type, scope_id, _ = _parse_scope(obj, None)
    raw_type = str(obj.get("type") or RuleType.HARD.value).upper()
    try:
        rule_type = RuleType(raw_type)
    except Exception:
        rule_type = RuleType.HARD

    priority = int(obj.get("priority") or 0)
    constraints, _, _ = _extract_constraints_from_obj(
        obj,
        rule_type=rule_type,
        scope_type=scope_type,
        scope_id=scope_id,
        priority=priority,
        rule_id=None,
        legacy_mode=legacy_mode,
    )

    parts: list[str] = []
    header = f"{rule_type.value} / {scope_type.value}"
    if scope_id:
        header += f" ({scope_id})"
    parts.append(header)

    name_map = {
        "coverage_required": "每日班別需求",
        "max_consecutive_work_days": "最大連續上班天數",
        "max_consecutive_shift": "最大連續特定班別",
        "forbid_transition": "禁止班別銜接",
        "rest_after_shift": "指定班別後休息",
        "unavailable_dates": "不可排班日期",
        "skill_coverage": "技能覆蓋",
        "if_novice_present_then_senior_present": "新手在場需資深在場",
        "balance_shift_count": "班別數量平衡",
        "balance_weekend_shift_count": "週末班別數量平衡",
        "penalize_transition": "懲罰班別銜接",
        "prefer_off_on_weekends": "偏好週末休假",
        "prefer_shift": "偏好班別",
        "penalize_single_off_day": "懲罰單日休",
        "penalize_consecutive_same_shift": "懲罰連續相同班別",
    }

    for c in constraints:
        label = name_map.get(c.name, c.name)
        params = c.params or {}
        summary = f"{label}（params={params}）"
        if c.weight is not None:
            summary = f"{summary}，weight={c.weight}"
        parts.append(summary)

    return "\n".join(parts)


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
    obj, parse_issues = _load_dsl_obj(dsl_text)
    if parse_issues or not obj:
        return {"ok": False, "issues": parse_issues, "warnings": []}

    legacy_mode = _is_legacy_dsl(obj)
    if legacy_mode:
        obj = _normalize_legacy_dsl(obj, rule)

    dsl_version = obj.get("dsl_version")
    if not dsl_version:
        issues.append("缺少 dsl_version。")
        dsl_version = DEFAULT_DSL_VERSION
    if not isinstance(dsl_version, str):
        issues.append("dsl_version 必須為字串。")
        dsl_version = str(dsl_version)
    elif not dsl_version.startswith(ALLOWED_DSL_MAJOR):
        issues.append(f"dsl_version 不相容：{dsl_version}")
    elif dsl_version != DEFAULT_DSL_VERSION:
        warnings.append(f"dsl_version {dsl_version} 尚未驗證相容性，建議使用 {DEFAULT_DSL_VERSION}。")

    rule_id = obj.get("id")
    if not rule_id or not isinstance(rule_id, str):
        issues.append("id 必須為字串。")
    name = obj.get("name")
    if not name or not isinstance(name, str):
        issues.append("name 必須為字串。")

    raw_type = obj.get("type") or (rule.rule_type.value if isinstance(rule, Rule) else RuleType.HARD.value)
    try:
        rule_type = RuleType(str(raw_type).upper())
    except Exception:
        issues.append(f"type 不支援：{raw_type}。")
        rule_type = RuleType.HARD

    priority_val = obj.get("priority")
    if priority_val is None:
        issues.append("priority 必填。")
        priority = 0
    else:
        try:
            priority = int(priority_val)
            if priority < 0:
                issues.append("priority 必須為非負整數。")
        except Exception:
            issues.append("priority 必須為整數。")
            priority = 0

    enabled_val = obj.get("enabled")
    if enabled_val is None:
        issues.append("enabled 必填。")
    elif not isinstance(enabled_val, bool):
        issues.append("enabled 必須為布林值。")

    tags_val = obj.get("tags")
    if tags_val is not None and not (isinstance(tags_val, list) and all(isinstance(t, str) for t in tags_val)):
        issues.append("tags 必須為字串陣列。")

    notes_val = obj.get("notes")
    if notes_val is not None and not isinstance(notes_val, str):
        issues.append("notes 必須為字串。")

    scope_type, scope_id, scope_warnings = _parse_scope(obj, rule)
    warnings.extend(scope_warnings)

    constraints, constraint_issues, constraint_warnings = _extract_constraints_from_obj(
        obj,
        rule_type=rule_type,
        scope_type=scope_type,
        scope_id=scope_id,
        priority=priority,
        rule_id=rule.id if isinstance(rule, Rule) else None,
        legacy_mode=legacy_mode,
    )
    issues.extend(constraint_issues)
    warnings.extend(constraint_warnings)

    # referential integrity checks
    shift_codes = _available_shift_codes(session)
    if shift_codes:
        for c in constraints:
            if c.shift_code and c.shift_code not in shift_codes:
                issues.append(f"{c.name} 參照未知班別：{c.shift_code}")
            params = c.params or {}
            shift_list = params.get("shift_codes")
            if isinstance(shift_list, list):
                for code in shift_list:
                    if isinstance(code, str) and code and code not in shift_codes:
                        issues.append(f"{c.name} 參照未知班別：{code}")
            off_code = params.get("off_code")
            if isinstance(off_code, str) and off_code and off_code not in shift_codes:
                issues.append(f"{c.name} 參照未知班別：{off_code}")

    if session and scope_type == RuleScopeType.DEPARTMENT and scope_id:
        dept = session.exec(select(Department).where(Department.code == scope_id)).first()
        if not dept and scope_id.isdigit():
            dept = session.get(Department, int(scope_id))
        if not dept:
            issues.append(f"scope.id={scope_id} 的科別不存在。")
    if session and scope_type == RuleScopeType.NURSE and scope_id:
        nurse = session.exec(select(Nurse).where(Nurse.staff_no == scope_id)).first()
        if not nurse and scope_id.isdigit():
            nurse = session.get(Nurse, int(scope_id))
        if nurse is None:
            issues.append(f"scope.id={scope_id} 的護理師不存在。")

    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "dsl_version": dsl_version,
        "scope": {"type": scope_type.value, "id": scope_id},
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
    return load_rule_constraints_from_dsl(rule.dsl_text or "{}", rule, session=session)


def load_rule_constraints_from_dsl(dsl_text: str, rule: Rule | None, session: Session | None = None) -> tuple[list[RuleConstraint], dict]:
    validation = validate_dsl(dsl_text or "{}", session=session, rule=rule)
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
