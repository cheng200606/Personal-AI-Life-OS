"""Idempotent scheduled weekly review generation."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from personal_ai_life_os.config import Settings
from personal_ai_life_os.models import (
    Review,
    ReviewSchedule,
    SourceConnection,
    SourceItem,
    User,
    utcnow,
)
from personal_ai_life_os.services.graph_extraction import monthly_spend
from personal_ai_life_os.services.jobs import enqueue_background_job
from personal_ai_life_os.services.model_consent import desktop_source_authorized, has_consent
from personal_ai_life_os.services.model_providers import (
    ModelProviderError,
    provider_cost,
    resolve_model_provider,
)

logger = logging.getLogger(__name__)
SCHEDULE_POLL_INTERVAL_SECONDS = 30.0
MAX_DUE_SCHEDULES_PER_RUN = 20


def compute_next_run(
    after: datetime,
    *,
    weekday: int,
    local_hour: int,
    local_minute: int,
    timezone_name: str,
) -> datetime:
    """Return the next UTC occurrence strictly after ``after`` for a local wall-clock schedule."""
    zone = ZoneInfo(timezone_name)
    local = after.astimezone(zone)
    candidate = local.replace(
        hour=local_hour, minute=local_minute, second=0, microsecond=0
    )
    candidate += timedelta(days=(weekday - local.weekday()) % 7)
    if candidate <= local:
        candidate += timedelta(days=7)
    return candidate.astimezone(UTC)


def _period_bounds(occurrence: datetime, timezone_name: str) -> tuple[datetime, datetime]:
    from personal_ai_life_os.api.routes.reviews import _local_bounds

    local_date = occurrence.astimezone(ZoneInfo(timezone_name)).date()
    start = local_date - timedelta(days=7)
    return _local_bounds(start, local_date, timezone_name)


def _active_items(
    session: Session, owner_id: str, start_at: datetime, end_at: datetime
) -> list[SourceItem]:
    return list(
        session.scalars(
            select(SourceItem)
            .join(SourceConnection, SourceConnection.id == SourceItem.source_id)
            .where(
                SourceItem.owner_id == owner_id,
                SourceItem.is_current.is_(True),
                SourceItem.deleted_at.is_(None),
                SourceItem.occurred_at >= start_at,
                SourceItem.occurred_at < end_at,
                SourceConnection.status == "active",
            )
            .order_by(SourceItem.occurred_at, SourceItem.id)
            .limit(501)
        )
    )


def _create_scheduled_review(
    session: Session,
    schedule: ReviewSchedule,
    user: User,
    config: Settings,
    occurrence: datetime,
) -> str | None:
    from personal_ai_life_os.api.routes.reviews import (
        PROMPT_VERSION,
        _estimate_openai_input_tokens,
        _render_markdown,
        _snapshot_review,
        _template,
    )
    from personal_ai_life_os.services.review_insights import build_review_insights

    start_at, end_at = _period_bounds(occurrence, schedule.timezone)
    items = _active_items(session, user.id, start_at, end_at)
    if not items:
        return None
    if len(items) > 500:
        logger.warning("Scheduled review truncated to 500 items.")
        items = items[:500]

    existing = session.scalar(
        select(Review).where(
            Review.owner_id == user.id,
            Review.period_start == start_at,
            Review.period_end == end_at,
        )
    )
    if existing is not None:
        return existing.id

    draft = _template(items)
    if schedule.use_external_model:
        try:
            provider = resolve_model_provider(config, schedule.provider_id, schedule.model)
        except ModelProviderError:
            provider = None
        consented = (
            provider is not None and has_consent(session, user, provider)
            and all(desktop_source_authorized(item.source, config) for item in items)
        )
        rates_ready = bool(provider and provider.rates_configured and provider.disclosure_ready)
        reserved_cost = (
            provider_cost(
                provider,
                _estimate_openai_input_tokens(items),
                provider.max_output_tokens,
            )
            if rates_ready and provider is not None
            else None
        )
        monthly = monthly_spend(session, user.id)
        remaining = (
            config.model_monthly_budget_usd - monthly
            if config.model_monthly_budget_usd > 0 or config.app_env == "desktop"
            else (reserved_cost or 0)
        )
        if (
            provider is not None
            and consented
            and reserved_cost is not None
            and reserved_cost <= config.model_max_cost_per_call_usd
            and reserved_cost <= remaining
            and config.processing_mode == "worker"
        ):
            draft["model"] = {
                "provider": provider.id,
                "status": "processing",
                "model": provider.model,
                "prompt_version": PROMPT_VERSION,
                "latency_ms": 0,
                "input_tokens": 0,
                "output_tokens": 0,
            }
            review = Review(
                owner_id=user.id,
                period_start=start_at,
                period_end=end_at,
                status="processing",
                draft_json=draft,
                final_text=None,
                source_items=items,
            )
            session.add(review)
            session.flush()
            draft["insights"] = build_review_insights(session, review)
            review.draft_json = draft
            review.final_text = _render_markdown(draft, items)
            job = enqueue_background_job(
                session,
                owner_id=user.id,
                review_id=review.id,
                kind="weekly_review",
                dedupe_key=f"weekly-review:{review.id}",
                payload={
                    "review_id": review.id,
                    "prompt_version": PROMPT_VERSION,
                    "provider": provider.id,
                    "model": provider.model,
                    "reserved_cost_usd": str(reserved_cost),
                },
                max_attempts=1,
            )
            review.draft_json = {
                **draft,
                "model": {**draft["model"], "job_id": job.id},
            }
            _snapshot_review(session, review, "generated")
            return review.id

        if provider is None:
            model_status = "provider_unconfigured"
        elif not consented:
            model_status = "consent_withdrawn"
        elif reserved_cost is None or reserved_cost > config.model_max_cost_per_call_usd or reserved_cost > remaining:
            model_status = "budget_fallback"
        else:
            model_status = "worker_required"
        draft["model"] = {
            "provider": schedule.provider_id,
            "status": model_status,
            "model": schedule.model,
            "prompt_version": PROMPT_VERSION,
            "latency_ms": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }

    review = Review(
        owner_id=user.id,
        period_start=start_at,
        period_end=end_at,
        status="draft",
        draft_json=draft,
        final_text=None,
        source_items=items,
    )
    session.add(review)
    session.flush()
    draft["insights"] = build_review_insights(session, review)
    review.draft_json = draft
    review.final_text = _render_markdown(draft, items)
    _snapshot_review(session, review, "generated")
    return review.id


def run_due_reviews_once(
    session_factory: sessionmaker,
    config: Settings,
    *,
    now: datetime | None = None,
) -> int:
    """Claim and generate due schedules. Returns the number of schedules processed."""
    current = now or utcnow()
    processed = 0
    attempted: set[str] = set()
    while processed < MAX_DUE_SCHEDULES_PER_RUN:
        with session_factory() as session:
            query = select(ReviewSchedule).where(
                ReviewSchedule.enabled.is_(True),
                ReviewSchedule.next_run_at.is_not(None),
                ReviewSchedule.next_run_at <= current,
            )
            if attempted:
                query = query.where(~ReviewSchedule.id.in_(attempted))
            schedule = session.scalar(
                query.order_by(ReviewSchedule.next_run_at, ReviewSchedule.id).limit(1)
            )
            if schedule is None:
                break
            attempted.add(schedule.id)
            occurrence = schedule.next_run_at
            assert occurrence is not None
            try:
                next_occurrence = compute_next_run(
                    occurrence + timedelta(seconds=1),
                    weekday=schedule.weekday,
                    local_hour=schedule.local_hour,
                    local_minute=schedule.local_minute,
                    timezone_name=schedule.timezone,
                )
            except Exception:  # noqa: BLE001 - an invalid stored zone cannot block other schedules.
                logger.warning("Scheduled review disabled because its timezone is invalid.")
                schedule.enabled = False
                schedule.next_run_at = None
                session.commit()
                processed += 1
                continue

            claim = session.execute(
                update(ReviewSchedule)
                .where(
                    ReviewSchedule.id == schedule.id,
                    ReviewSchedule.enabled.is_(True),
                    ReviewSchedule.next_run_at == occurrence,
                )
                .values(next_run_at=next_occurrence, last_run_at=occurrence)
            )
            if claim.rowcount != 1:
                session.rollback()
                processed += 1
                continue

            user = session.get(User, schedule.owner_id)
            if user is None or user.deletion_requested_at is not None:
                schedule.enabled = False
                schedule.next_run_at = None
                session.commit()
                processed += 1
                continue

            try:
                review_id = _create_scheduled_review(
                    session, schedule, user, config, occurrence
                )
                schedule.last_review_id = review_id
                session.commit()
            except Exception:  # noqa: BLE001 - roll back the claim and retry on the next poll.
                session.rollback()
                logger.warning("Scheduled review generation failed; it will retry.")
            processed += 1
    return processed


def schedule_loop(
    session_factory: sessionmaker,
    config: Settings,
    stop: threading.Event,
) -> None:
    logger.info("Scheduled review worker started.")
    while not stop.is_set():
        try:
            run_due_reviews_once(session_factory, config)
        except Exception:  # noqa: BLE001 - keep the poller alive through transient database errors.
            logger.error("Scheduled review poll failed.")
        stop.wait(SCHEDULE_POLL_INTERVAL_SECONDS)
    logger.info("Scheduled review worker stopped.")
