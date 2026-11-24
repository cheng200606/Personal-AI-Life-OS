"""Service health endpoint."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health", summary="Check API health")
def health() -> dict[str, str]:
    """Return a lightweight liveness response."""
    return {"status": "ok", "service": "personal-ai-life-os"}
