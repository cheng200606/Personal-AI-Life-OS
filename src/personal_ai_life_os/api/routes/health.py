"""Service health endpoint."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from personal_ai_life_os.api.deps import SessionDep

router = APIRouter(tags=["health"])


@router.get("/health", summary="Check API health")
def health() -> dict[str, str]:
    """Return a lightweight liveness response."""
    return {"status": "ok", "service": "personal-ai-life-os"}


@router.get("/ready", summary="Check API and database readiness")
def ready(session: SessionDep) -> dict[str, str]:
    """Return readiness without exposing database details."""
    try:
        session.execute(text("SELECT 1"))
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "database_unavailable", "message": "The database is not ready."},
        ) from error
    return {"status": "ready", "service": "personal-ai-life-os"}
