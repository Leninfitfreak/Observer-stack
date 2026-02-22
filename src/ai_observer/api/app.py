from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ai_observer.api.routes import health_router, reasoning_router
from ai_observer.core.di import build_container
from ai_observer.core.logging import setup_logging
from ai_observer.core.settings import AppSettings, load_settings


def create_app(settings: AppSettings | None = None) -> FastAPI:
    setup_logging()
    cfg = settings or load_settings()

    app = FastAPI(title="AI Observer Agent", version="3.0.0")
    app.state.container = build_container(cfg)

    repo_root = Path(__file__).resolve().parents[3]
    static_dir = repo_root / "app" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/dashboard")
        def dashboard() -> FileResponse:
            return FileResponse(static_dir / "dashboard.html")

    @app.middleware("http")
    async def no_cache_dashboard_assets(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/dashboard" or path in {"/static/dashboard.js", "/static/dashboard.css", "/static/dashboard.html"}:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    app.include_router(health_router)
    app.include_router(reasoning_router)
    return app
