"""Owner-scoped weekly review schedule settings."""

from fastapi import APIRouter
from sqlalchemy import select

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import (
    ReviewScheduleResponse,
    ReviewScheduleUpdateRequest,
)
from personal_ai_life_os.models import ReviewSchedule, utcnow
from personal_ai_life_os.services.scheduling import compute_next_run

router = APIRouter(prefix="/review-schedule", tags=["reviews"])


def _response(schedule: ReviewSchedule) -> ReviewScheduleResponse:
    return ReviewScheduleResponse(
        enabled=schedule.enabled,
        weekday=schedule.weekday,
        local_hour=schedule.local_hour,
        local_minute=schedule.local_minute,
        timezone=schedule.timezone,
        use_external_model=schedule.use_external_model,
        last_run_at=schedule.last_run_at,
        next_run_at=schedule.next_run_at,
        last_review_id=schedule.last_review_id,
    )


def _default(user_timezone: str) -> ReviewScheduleResponse:
    return ReviewScheduleResponse(
        enabled=False,
        weekday=6,
        local_hour=18,
        local_minute=0,
        timezone=user_timezone,
        use_external_model=False,
        last_run_at=None,
        next_run_at=None,
        last_review_id=None,
    )


@router.get("", response_model=ReviewScheduleResponse)
def get_review_schedule(user: CurrentUserDep, session: SessionDep) -> ReviewScheduleResponse:
    schedule = session.scalar(
        select(ReviewSchedule).where(ReviewSchedule.owner_id == user.id)
    )
    return _response(schedule) if schedule is not None else _default(user.timezone)


@router.put("", response_model=ReviewScheduleResponse)
def update_review_schedule(
    payload: ReviewScheduleUpdateRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> ReviewScheduleResponse:
    schedule = session.scalar(
        select(ReviewSchedule).where(ReviewSchedule.owner_id == user.id)
    )
    if schedule is None:
        schedule = ReviewSchedule(owner_id=user.id)
        session.add(schedule)
    schedule.enabled = payload.enabled
    schedule.weekday = payload.weekday
    schedule.local_hour = payload.local_hour
    schedule.local_minute = payload.local_minute
    schedule.timezone = payload.timezone
    schedule.use_external_model = payload.use_external_model
    schedule.next_run_at = (
        compute_next_run(
            utcnow(),
            weekday=payload.weekday,
            local_hour=payload.local_hour,
            local_minute=payload.local_minute,
            timezone_name=payload.timezone,
        )
        if payload.enabled
        else None
    )
    session.commit()
    session.refresh(schedule)
    return _response(schedule)
