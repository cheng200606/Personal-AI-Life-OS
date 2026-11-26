from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from test_reviews_account import (
    configure_synthetic_model_pricing,
    import_memory,
    token_for,
)

from personal_ai_life_os.models import BackgroundJob, ReviewSchedule
from personal_ai_life_os.services.scheduling import run_due_reviews_once

OCCURRENCE = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)  # Sunday 20:00 Asia/Shanghai


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _put_schedule(client, token: str, **overrides):
    payload = {
        "enabled": True,
        "weekday": 6,
        "local_hour": 20,
        "local_minute": 0,
        "timezone": "Asia/Shanghai",
        "use_external_model": False,
    }
    payload.update(overrides)
    return client.put("/api/v1/review-schedule", headers=_headers(token), json=payload)


def _user_id(client, token: str) -> str:
    return client.get("/api/v1/auth/me", headers=_headers(token)).json()["id"]


def _set_next_run(client, token: str, occurrence: datetime) -> None:
    with client.app.state.session_factory() as session:
        schedule = session.scalar(
            select(ReviewSchedule).where(
                ReviewSchedule.owner_id == _user_id(client, token)
            )
        )
        assert schedule is not None
        schedule.next_run_at = occurrence
        session.commit()


def _schedule(client, token: str) -> ReviewSchedule:
    with client.app.state.session_factory() as session:
        schedule = session.scalar(
            select(ReviewSchedule).where(
                ReviewSchedule.owner_id == _user_id(client, token)
            )
        )
        assert schedule is not None
        session.expunge(schedule)
        return schedule


def _run(client, now: datetime) -> int:
    return run_due_reviews_once(
        client.app.state.session_factory,
        client.app.state.settings,
        now=now,
    )


def test_schedule_defaults_validation_and_owner_isolation(client) -> None:
    token = token_for(client, "schedule-defaults@example.com")
    response = client.get("/api/v1/review-schedule", headers=_headers(token))
    assert response.status_code == 200
    assert response.json() == {
        "enabled": False,
        "weekday": 6,
        "local_hour": 18,
        "local_minute": 0,
        "timezone": "Asia/Shanghai",
        "use_external_model": False,
        "provider_id": "default",
        "model": None,
        "last_run_at": None,
        "next_run_at": None,
        "last_review_id": None,
    }

    saved = _put_schedule(client, token)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["enabled"] is True
    next_run = datetime.fromisoformat(body["next_run_at"])
    local = next_run.astimezone(ZoneInfo("Asia/Shanghai"))
    assert local.weekday() == 6
    assert (local.hour, local.minute) == (20, 0)

    disabled = _put_schedule(client, token, enabled=False)
    assert disabled.json()["enabled"] is False
    assert disabled.json()["next_run_at"] is None

    assert _put_schedule(client, token, weekday=7).status_code == 422
    assert _put_schedule(client, token, local_hour=24).status_code == 422
    assert _put_schedule(client, token, timezone="Mars/Base").status_code == 422

    other = token_for(client, "schedule-other@example.com")
    other_default = client.get(
        "/api/v1/review-schedule", headers=_headers(other)
    ).json()
    assert other_default["enabled"] is False
    assert other_default["last_review_id"] is None
    still_saved = client.get(
        "/api/v1/review-schedule", headers=_headers(token)
    ).json()
    assert still_saved["enabled"] is False


def test_scheduled_review_is_idempotent_and_uses_local_week(client) -> None:
    token = token_for(client, "schedule-run@example.com")
    import_memory(client, token)
    assert _put_schedule(client, token).status_code == 200
    _set_next_run(client, token, OCCURRENCE)

    assert _run(client, OCCURRENCE + timedelta(minutes=1)) == 1

    reviews = client.get("/api/v1/reviews", headers=_headers(token)).json()
    assert len(reviews) == 1
    review = reviews[0]
    assert review["status"] == "draft"
    assert review["source_items"]
    assert review["period_start"] == "2026-11-14T16:00:00Z"
    assert review["period_end"] == "2026-11-21T16:00:00Z"
    assert "Highlights" in review["final_text"]

    schedule = _schedule(client, token)
    assert schedule.last_review_id == review["id"]
    assert schedule.last_run_at == OCCURRENCE
    assert schedule.next_run_at == OCCURRENCE + timedelta(days=7)

    assert _run(client, OCCURRENCE + timedelta(minutes=1)) == 0
    assert len(client.get("/api/v1/reviews", headers=_headers(token)).json()) == 1


def test_scheduled_review_reuses_an_existing_period(client) -> None:
    token = token_for(client, "schedule-existing@example.com")
    import_memory(client, token)
    manual = client.post(
        "/api/v1/reviews/generate",
        headers=_headers(token),
        json={"period_start": "2026-11-15", "period_end": "2026-11-22"},
    )
    assert manual.status_code == 201, manual.text
    manual_id = manual.json()["id"]
    assert _put_schedule(client, token).status_code == 200
    _set_next_run(client, token, OCCURRENCE)

    assert _run(client, OCCURRENCE + timedelta(minutes=1)) == 1
    reviews = client.get("/api/v1/reviews", headers=_headers(token)).json()
    assert [review["id"] for review in reviews] == [manual_id]
    assert _schedule(client, token).last_review_id == manual_id


def test_scheduled_review_skips_disabled_and_paused_sources(client) -> None:
    token = token_for(client, "schedule-paused@example.com")
    source_id, _ = import_memory(client, token)
    assert _put_schedule(client, token, enabled=False).status_code == 200
    _set_next_run(client, token, OCCURRENCE)
    assert _run(client, OCCURRENCE + timedelta(minutes=1)) == 0
    assert client.get("/api/v1/reviews", headers=_headers(token)).json() == []

    assert _put_schedule(client, token).status_code == 200
    paused = client.patch(
        "/api/v1/sources/" + source_id + "/status",
        headers=_headers(token),
        json={"status": "paused"},
    )
    assert paused.status_code == 200
    _set_next_run(client, token, OCCURRENCE + timedelta(days=7))

    assert _run(client, OCCURRENCE + timedelta(days=7, minutes=1)) == 1
    assert client.get("/api/v1/reviews", headers=_headers(token)).json() == []
    schedule = _schedule(client, token)
    assert schedule.last_review_id is None
    assert schedule.next_run_at == OCCURRENCE + timedelta(days=14)


def test_scheduled_external_review_falls_back_without_consent(client) -> None:
    token = token_for(client, "schedule-consent@example.com")
    import_memory(client, token)
    config = client.app.state.settings
    config.model_provider = "openai"
    config.openai_api_key = "synthetic-api-key"
    configure_synthetic_model_pricing(config)
    assert _put_schedule(client, token, use_external_model=True).status_code == 200
    _set_next_run(client, token, OCCURRENCE)

    assert _run(client, OCCURRENCE + timedelta(minutes=1)) == 1
    review = client.get("/api/v1/reviews", headers=_headers(token)).json()[0]
    assert review["status"] == "draft"
    assert review["draft"]["model"]["status"] == "consent_withdrawn"
    with client.app.state.session_factory() as session:
        jobs = list(session.scalars(select(BackgroundJob)))
    assert jobs == []


def test_scheduled_external_review_budget_fallback(client) -> None:
    token = token_for(client, "schedule-budget@example.com")
    import_memory(client, token)
    config = client.app.state.settings
    config.model_provider = "openai"
    config.openai_api_key = "synthetic-api-key"
    configure_synthetic_model_pricing(config)
    config.model_max_cost_per_call_usd = Decimal("0.0000001")
    consent = client.put(
        "/api/v1/auth/ai-consent",
        headers=_headers(token),
        json={"enabled": True, "disclosure_version": config.model_disclosure_version},
    )
    assert consent.status_code == 200
    assert _put_schedule(client, token, use_external_model=True).status_code == 200
    _set_next_run(client, token, OCCURRENCE)

    assert _run(client, OCCURRENCE + timedelta(minutes=1)) == 1
    review = client.get("/api/v1/reviews", headers=_headers(token)).json()[0]
    assert review["status"] == "draft"
    assert review["draft"]["model"]["status"] == "budget_fallback"


def test_scheduled_external_review_enqueues_worker_job(client) -> None:
    token = token_for(client, "schedule-worker@example.com")
    import_memory(client, token)
    config = client.app.state.settings
    config.model_provider = "openai"
    config.openai_api_key = "synthetic-api-key"
    config.processing_mode = "worker"
    configure_synthetic_model_pricing(config)
    consent = client.put(
        "/api/v1/auth/ai-consent",
        headers=_headers(token),
        json={"enabled": True, "disclosure_version": config.model_disclosure_version},
    )
    assert consent.status_code == 200
    assert _put_schedule(client, token, use_external_model=True).status_code == 200
    _set_next_run(client, token, OCCURRENCE)

    assert _run(client, OCCURRENCE + timedelta(minutes=1)) == 1
    review = client.get("/api/v1/reviews", headers=_headers(token)).json()[0]
    assert review["status"] == "processing"
    assert review["draft"]["model"]["status"] == "processing"
    assert review["draft"]["model"]["job_id"]
    with client.app.state.session_factory() as session:
        job = session.scalar(
            select(BackgroundJob).where(BackgroundJob.review_id == review["id"])
        )
    assert job is not None
    assert job.kind == "weekly_review"
    assert job.status == "queued"
