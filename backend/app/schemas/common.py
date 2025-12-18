from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ApiError(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ApiResponse(BaseModel):
    ok: bool = True
    data: Any = None
    error: Optional[ApiError] = None


def ok(data: Any = None) -> dict:
    return ApiResponse(ok=True, data=data).model_dump()


def err(code: str, message: str, details: Optional[dict] = None) -> dict:
    return ApiResponse(ok=False, error=ApiError(code=code, message=message, details=details or {})).model_dump()
