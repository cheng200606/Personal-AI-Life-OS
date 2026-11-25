from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
from os import getenv
from subprocess import run as run_process
from sys import executable
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from personal_ai_life_os.main import create_app
from personal_ai_life_os.models import BackgroundJob, ModelRun
from personal_ai_life_os.services import jobs


@pytest.fixture
def worker_client(app):
    config = app.state.settings
    # The optional PostgreSQL URL must point to a disposable integration database.
    database_url = getenv("LIFEOS_WORKER_TEST_DATABASE_URL")
    if not database_url:
        with TestClient(app) as client:
            yield client
        return
    schema = "worker_test_" + uuid4().hex
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        scoped_url = make_url(database_url).update_query_dict({"options": "-csearch_path=" + schema})
        config.database_url = scoped_url.render_as_string(hide_password=False)
        app = create_app(config)
        with TestClient(app) as client:
            yield client
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


@pytest.fixture
def queued_photo(worker_client):
    client = worker_client
    token = client.post(
        "/api/v1/auth/register",
        json={"email": f"{uuid4().hex}@example.test", "password": "synthetic-worker-password"},
    ).json()["access_token"]
    headers = {"Authorization": "Bearer " + token}
    source = client.post(
        "/api/v1/sources", headers=headers, json={"kind": "photo", "name": "Synthetic OCR"}
    ).json()
    client.app.state.settings.processing_mode = "worker"
    image = BytesIO()
    Image.new("RGB", (40, 40), "white").save(image, "PNG")
    imported = client.post(
        f"/api/v1/sources/{source['id']}/imports",
        headers=headers,
        files={"file": ("worker.png", image.getvalue(), "image/png")},
    )
    assert imported.status_code == 201, imported.text
    item = imported.json()["items"][0]
    return source["id"], item["id"], item["metadata"]["ocr_job_id"], headers


def test_reclaimed_ocr_job_ignores_late_worker(worker_client, queued_photo, monkeypatch) -> None:
    client = worker_client
    _, item_id, job_id, headers = queued_photo
    state = client.app.state
    old_worker_read_image = Event()
    release_old_worker = Event()

    def ocr(_image):
        if not old_worker_read_image.is_set():
            old_worker_read_image.set()
            assert release_old_worker.wait(10)
            return "stale result", "completed"
        return "recovered result", "completed"

    monkeypatch.setattr(jobs, "extract_photo_text_bytes", ocr)

    def run(worker_id):
        return jobs.run_background_job_once(
            state.session_factory, state.object_store, state.settings, worker_id=worker_id
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        old_worker = pool.submit(run, "original")
        try:
            assert old_worker_read_image.wait(10)
            assert not run("competing")
            with state.session_factory() as session:
                job = session.get(BackgroundJob, job_id)
                job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
                session.commit()

            def recovering_ocr(_image):
                # The expired attempt returns while the replacement owns the running job.
                release_old_worker.set()
                assert old_worker.result(timeout=10)
                return "recovered result", "completed"

            monkeypatch.setattr(jobs, "extract_photo_text_bytes", recovering_ocr)
            assert run("replacement")
        finally:
            release_old_worker.set()

    result = client.get("/api/v1/jobs/" + job_id, headers=headers).json()
    assert result["status"] == "completed"
    assert result["attempt_count"] == 2
    assert (
        client.get("/api/v1/items/" + item_id, headers=headers).json()["content_text"]
        == "recovered result"
    )


@pytest.mark.parametrize("action", ["pause", "revoke", "delete"])
def test_source_changes_discard_inflight_ocr(
    worker_client, queued_photo, monkeypatch, action
) -> None:
    client = worker_client
    source_id, item_id, job_id, headers = queued_photo
    source_path = "/api/v1/sources/" + source_id
    state = client.app.state

    def ocr(_image):
        if action == "pause":
            response = client.patch(
                source_path + "/status", headers=headers, json={"status": "paused"}
            )
        elif action == "revoke":
            response = client.post(source_path + "/revoke", headers=headers)
        else:
            response = client.delete(source_path, headers=headers)
        assert response.is_success, response.text
        return "late OCR text", "extracted"

    monkeypatch.setattr(jobs, "extract_photo_text_bytes", ocr)
    assert jobs.run_background_job_once(state.session_factory, state.object_store, state.settings)
    item = client.get("/api/v1/items/" + item_id, headers=headers)
    result = client.get("/api/v1/jobs/" + job_id, headers=headers)
    if action == "delete":
        assert item.status_code == 404
        assert result.status_code == 404 or result.json()["status"] == "cancelled"
    else:
        assert result.json()["status"] == "cancelled"
        assert item.json()["content_text"] != "late OCR text"


def test_new_process_recovers_interrupted_ocr(worker_client, queued_photo) -> None:
    client = worker_client
    _, item_id, job_id, headers = queued_photo
    settings = client.app.state.settings.model_dump_json()
    setup = """import sys
from personal_ai_life_os.config import Settings
from personal_ai_life_os.main import create_app
from personal_ai_life_os.services import jobs
app = create_app(Settings.model_validate_json(sys.stdin.read()))
"""
    run_process(
        [
            executable,
            "-c",
            setup
            + "assert jobs._claim(app.state.session_factory, 'interrupted', app.state.settings)",
        ],
        input=settings,
        text=True,
        check=True,
        timeout=30,
    )
    path = "/api/v1/jobs/" + job_id
    assert client.get(path, headers=headers).json()["status"] == "running"
    with client.app.state.session_factory() as session:
        session.get(BackgroundJob, job_id).lease_expires_at = datetime.now(UTC) - timedelta(
            seconds=1
        )
        session.commit()
    run_process(
        [
            executable,
            "-c",
            setup
            + """jobs.extract_photo_text_bytes = lambda _: ("Recovered after process exit", "extracted")
assert jobs.run_background_job_once(app.state.session_factory, app.state.object_store, app.state.settings)
""",
        ],
        input=settings,
        text=True,
        check=True,
        timeout=30,
    )
    result = client.get(path, headers=headers).json()
    assert (result["status"], result["attempt_count"]) == ("completed", 2)
    assert (
        client.get("/api/v1/items/" + item_id, headers=headers).json()["content_text"]
        == "Recovered after process exit"
    )


def test_expired_model_attempt_records_cost_once(worker_client, monkeypatch) -> None:
    from test_reviews_account import configure_synthetic_model_pricing, import_memory, token_for

    from personal_ai_life_os.api.routes import reviews

    client = worker_client
    token = token_for(client, f"{uuid4().hex}@example.test")
    import_memory(client, token)
    state = client.app.state
    config = state.settings
    config.processing_mode = "worker"
    config.model_provider = "openai"
    config.openai_api_key = "synthetic-api-key"
    configure_synthetic_model_pricing(config)
    headers = {"Authorization": "Bearer " + token}
    assert client.put(
        "/api/v1/auth/ai-consent",
        headers=headers,
        json={"enabled": True, "disclosure_version": config.model_disclosure_version},
    ).is_success
    response = client.post(
        "/api/v1/reviews/generate",
        headers=headers,
        json={"period_start": "2026-11-16", "period_end": "2026-11-18", "use_external_model": True},
    )
    assert response.status_code == 201, response.text
    review = response.json()
    job_id = review["draft"]["model"]["job_id"]
    calls = 0

    def model(items, _config):
        nonlocal calls
        calls += 1
        with state.session_factory() as session:
            session.get(BackgroundJob, job_id).lease_expires_at = datetime.now(UTC) - timedelta(
                seconds=1
            )
            session.commit()
        assert not jobs.run_background_job_once(
            state.session_factory, state.object_store, config, worker_id="replacement"
        )
        return reviews._template(items), 1, 10, 10

    monkeypatch.setattr(reviews, "_call_openai", model)
    assert jobs.run_background_job_once(state.session_factory, state.object_store, config)
    assert calls == 1
    assert client.get("/api/v1/jobs/" + job_id, headers=headers).json()["status"] == "failed"
    saved = client.get("/api/v1/reviews/" + review["id"], headers=headers).json()
    assert saved["draft"]["model"]["status"] == "fallback"
    with state.session_factory() as session:
        job = session.get(BackgroundJob, job_id)
        runs = session.scalars(select(ModelRun).where(ModelRun.owner_id == job.owner_id)).all()
        assert len(runs) == 1
        assert runs[0].status == "failed"
        assert runs[0].cost_usd > 0
