from .health import router as health_router
from ai_observer.backend.api import incidents_router
from ai_observer.incident_analysis.routes import router as incident_analysis_router
from .reasoning import router as reasoning_router

__all__ = ["health_router", "reasoning_router", "incident_analysis_router", "incidents_router"]
