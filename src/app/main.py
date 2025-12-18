from __future__ import annotations

import traceback
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
from app.api.optimization import router as opt_router
from app.api.projects import router as projects_router


def create_app() -> FastAPI:
    setup_logging()
    init_db()
    seed_if_empty()

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
    app.include_router(rules_router)
    app.include_router(opt_router)

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        tb = traceback.format_exc()
        # 不在 response 輸出敏感資料（此專案無）
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": "發生錯誤。請複製以下訊息並發送給您的 AI 助手：",
                "traceback": tb,
                "path": str(request.url.path),
            },
        )

    return app
