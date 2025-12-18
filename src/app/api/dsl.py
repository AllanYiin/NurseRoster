from __future__ import annotations

from fastapi import APIRouter

from app.schemas.common import ok
from app.services.rules import dsl_to_nl

router = APIRouter(prefix="/api/dsl", tags=["dsl"])


@router.get("/reverse_translate")
def reverse_translate(dsl_text: str):
    return ok({"text": dsl_to_nl(dsl_text)})

