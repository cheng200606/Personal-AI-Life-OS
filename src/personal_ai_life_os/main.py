"""FastAPI application entry point."""

from fastapi import FastAPI

from personal_ai_life_os.api.routes.health import router as health_router

app = FastAPI(
    title="Personal AI Life OS",
    description="A user-controlled system for capturing and reviewing personal context.",
    version="0.1.0",
)
app.include_router(health_router, prefix="/api/v1")
