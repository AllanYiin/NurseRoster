from __future__ import annotations

import logging
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.config import PROJECT_ROOT
from app.core.logging import setup_logging
from app.db.session import init_db
from app.services.seed import seed_if_empty

from app.api.masterdata import router as master_router
from app.api.calendar import router as calendar_router
from app.api.rules import router as rules_router
from app.api.schedule import router as schedule_router
from app.api.optimization import router as opt_router
from app.api.projects import router as projects_router
from app.api.dsl import router as dsl_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    setup_logging()
    try:
        init_db()
        seed_if_empty()
    except Exception:
        logger.exception("初始化失敗，請檢查資料庫與設定。")
        raise

    app = FastAPI(title="Nurse Scheduler v1", version="1.0.0")

    templates = Jinja2Templates(directory=str(PROJECT_ROOT / "src/app/templates"))

    app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "src/app/static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        return templates.TemplateResponse("index.html", {"request": request})

    # APIs

    @app.get("/api/health")
    def health():
        return {"ok": True, "data": {"status": "ok"}}

    app.include_router(projects_router)
    app.include_router(master_router)
    app.include_router(calendar_router)
    app.include_router(schedule_router)
    app.include_router(rules_router)
    app.include_router(opt_router)
    app.include_router(dsl_router)

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("未處理例外：%s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "系統發生錯誤，請稍後再試。如持續發生請提供時間點給管理員。",
                    "details": {},
                },
            },
        )

    return app
