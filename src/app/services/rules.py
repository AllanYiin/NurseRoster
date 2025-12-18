from __future__ import annotations

import json
import logging
import os
import time
from typing import Generator, Iterable, Tuple

logger = logging.getLogger(__name__)


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
        desc = obj.get("description", "")
        cs = obj.get("constraints", [])
        parts = [f"規則描述：{desc}"]
        for c in cs:
            if not isinstance(c, dict):
                continue
            name = c.get("name")
            if name == "daily_coverage":
                parts.append(f"每天 {c.get('shift')} 班至少 {c.get('min')} 人。")
            elif name == "max_consecutive":
                parts.append(f"{c.get('shift')} 班連續不得超過 {c.get('max_days')} 天。")
            elif name == "prefer_off_after_night":
                parts.append("大夜後偏好安排休假（軟限制）。")
        return "\n".join(parts)
    except Exception:
        return "無法解析 DSL（請確認格式為 JSON）。"


def validate_dsl(dsl_text: str) -> dict:
    """v1: validator（JSON/欄位檢查）。"""
    issues = []
    try:
        obj = json.loads(dsl_text)
    except Exception as e:
        return {"ok": False, "issues": [f"JSON 解析失敗：{e}"]}
    if not isinstance(obj, dict):
        issues.append("根節點必須為 JSON object。")
    if not obj.get("constraints"):
        issues.append("constraints 不得為空。")
    # minimal checks
    cs = obj.get("constraints")
    if isinstance(cs, list):
        for i, c in enumerate(cs):
            if not isinstance(c, dict):
                issues.append(f"constraints[{i}] 必須為 object")
                continue
            if not c.get("name"):
                issues.append(f"constraints[{i}] 缺少 name")
    return {"ok": len(issues) == 0, "issues": issues}
