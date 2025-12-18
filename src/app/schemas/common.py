from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class ApiResponse(BaseModel):
    ok: bool = True
    data: Any = None
    error: Optional[str] = None


def ok(data: Any = None) -> dict:
    return ApiResponse(ok=True, data=data).model_dump()


def err(message: str, data: Any = None) -> dict:
    return ApiResponse(ok=False, data=data, error=message).model_dump()
