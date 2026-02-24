from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ai_observer.api.routes import health_router, incident_analysis_router, incidents_router, reasoning_router
from ai_observer.core.di import build_container
from ai_observer.core.logging import setup_logging
from ai_observer.core.settings import AppSettings, load_settings
from ai_observer.incident_analysis.database import init_database


def create_app(settings: AppSettings | None = None) -> FastAPI:
    setup_logging()
    cfg = settings or load_settings()

    app = FastAPI(title="AI Observer Agent", version="3.0.0")
    app.state.container = build_container(cfg)
    init_database(cfg.database.url, cfg.database.echo_sql)

    repo_root = Path(__file__).resolve().parents[3]
    static_candidates = [
        repo_root / "app" / "static",  # local dev checkout
        repo_root / "static",          # container image layout (/app/static)
    ]
    static_dir = next((p for p in static_candidates if p.exists()), None)
    if static_dir is not None:
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/dashboard")
        def dashboard() -> FileResponse:
            return FileResponse(static_dir / "dashboard.html")

        @app.get("/history")
        def history() -> FileResponse:
            history_index = static_dir / "history" / "index.html"
            if history_index.exists():
                return FileResponse(history_index)
            return FileResponse(static_dir / "dashboard.html")

        @app.get("/incident/{incident_id}")
        def incident_detail(incident_id: str) -> FileResponse:
            history_index = static_dir / "history" / "index.html"
            if history_index.exists():
                return FileResponse(history_index)
            return FileResponse(static_dir / "dashboard.html")

    @app.middleware("http")
    async def no_cache_dashboard_assets(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path in {"/dashboard", "/history"} or path.startswith("/incident/") or path.startswith("/static/history/") or path in {
            "/static/dashboard.js",
            "/static/dashboard.css",
            "/static/dashboard.html",
        }:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    app.include_router(health_router)
    app.include_router(reasoning_router)
    app.include_router(incident_analysis_router)
    app.include_router(incidents_router)
    return app
