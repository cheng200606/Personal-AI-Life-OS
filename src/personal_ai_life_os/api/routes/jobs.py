"""Owner-scoped status and retry controls for durable background work."""


from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import BackgroundJobResponse
from personal_ai_life_os.models import BackgroundJob, Review, SourceConnection
from personal_ai_life_os.services.jobs import retry_background_job

router = APIRouter(prefix="/jobs", tags=["background jobs"])


def _get_job(session, job_id: str, owner_id: str) -> BackgroundJob:
    job = session.scalar(
        select(BackgroundJob).where(BackgroundJob.id == job_id, BackgroundJob.owner_id == owner_id)
    )
    if job is None:
        raise HTTPException(404, detail={"code": "job_not_found", "message": "The job was not found."})
    return job


@router.get("/{job_id}", response_model=BackgroundJobResponse)
def get_job(job_id: str, user: CurrentUserDep, session: SessionDep) -> BackgroundJob:
    return _get_job(session, job_id, user.id)


@router.post("/{job_id}/retry", response_model=BackgroundJobResponse)
def retry_job(job_id: str, request: Request, user: CurrentUserDep, session: SessionDep) -> BackgroundJob:
    job = _get_job(session, job_id, user.id)
    if job.status not in {"failed", "cancelled"}:
        raise HTTPException(
            409,
            detail={"code": "job_not_retryable", "message": "Only failed or cancelled jobs can be retried."},
        )
    if job.source_id:
        source = session.scalar(
            select(SourceConnection).where(
                SourceConnection.id == job.source_id,
                SourceConnection.owner_id == user.id,
                SourceConnection.status == "active",
            )
        )
        if source is None:
            raise HTTPException(
                409,
                detail={"code": "source_not_active", "message": "Resume the source before retrying its job."},
            )
    if job.kind in {"photo_description", "weekly_review"}:
        config = request.app.state.settings
        if (
            not user.ai_consent_at
            or user.ai_consent_provider != config.model_provider
            or user.ai_consent_disclosure_version != config.model_disclosure_version
        ):
            raise HTTPException(
                409,
                detail={"code": "model_consent_required", "message": "Enable current model consent before retrying this job."},
            )
    if job.review_id:
        review = session.get(Review, job.review_id)
        if review is None or review.status == "invalidated":
            raise HTTPException(
                409,
                detail={"code": "review_unavailable", "message": "Regenerate this review after restoring available sources."},
            )
        if any(item.source.status != "active" for item in review.source_items if item.deleted_at is None):
            raise HTTPException(
                409,
                detail={"code": "source_not_active", "message": "Resume every review source before retrying its job."},
            )
    retry_background_job(session, job)
    session.commit()
    session.refresh(job)
    return job
