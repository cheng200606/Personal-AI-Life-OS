import json
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

FIXTURE_MEMORY = Path(__file__).parents[1] / "fixtures" / "synthetic" / "memory.md"


def configure_synthetic_model_pricing(config) -> None:
    config.model_input_cost_per_million_usd = Decimal(1)
    config.model_output_cost_per_million_usd = Decimal(1)
    config.model_max_cost_per_call_usd = Decimal("0.10")


def token_for(client, email: str) -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct horse battery staple", "timezone": "Asia/Shanghai"},
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def import_memory(client, token: str) -> tuple[str, list[str]]:
    headers = {"Authorization": "Bearer " + token}
    source_response = client.post(
        "/api/v1/sources",
        headers=headers,
        json={"kind": "memory_markdown", "name": "synthetic notes", "selected_scope": {}},
    )
    assert source_response.status_code == 201, source_response.text
    source_id = source_response.json()["id"]
    imported = client.post(
        "/api/v1/sources/" + source_id + "/imports",
        headers=headers,
        files={"file": ("memory.md", FIXTURE_MEMORY.read_bytes(), "text/markdown")},
    )
    assert imported.status_code == 201, imported.text
    return source_id, [item["id"] for item in imported.json()["items"]]


def test_weekly_review_has_validated_citations_edit_and_export(client) -> None:
    token = token_for(client, "review@example.com")
    _, _ = import_memory(client, token)
    headers = {"Authorization": "Bearer " + token}
    response = client.post(
        "/api/v1/reviews/generate",
        headers=headers,
        json={"period_start": "2026-11-16", "period_end": "2026-11-18"},
    )
    assert response.status_code == 201, response.text
    review = response.json()
    assert review["status"] == "draft"
    assert review["source_items"]
    assert all(fact["source_ids"] for fact in review["draft"]["facts"])
    assert "[source:" in review["final_text"]

    saved = client.patch(
        "/api/v1/reviews/" + review["id"],
        headers=headers,
        json={"final_text": "A checked reflection."},
    )
    assert saved.status_code == 200
    assert saved.json()["status"] == "confirmed"
    exported = client.get("/api/v1/reviews/" + review["id"] + "/export.md", headers=headers)
    assert exported.status_code == 200
    assert "A checked reflection." in exported.text
    assert review["id"] in exported.text

    other = token_for(client, "other-review@example.com")
    assert client.get(
        "/api/v1/reviews/" + review["id"], headers={"Authorization": "Bearer " + other}
    ).status_code == 404


def test_external_review_requires_explicit_current_consent(client) -> None:
    token = token_for(client, "no-consent@example.com")
    import_memory(client, token)
    response = client.post(
        "/api/v1/reviews/generate",
        headers={"Authorization": "Bearer " + token},
        json={"period_start": "2026-11-16", "period_end": "2026-11-18", "use_external_model": True},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "model_consent_required"


def test_model_consent_can_be_revoked_without_reacknowledging(client) -> None:
    token = token_for(client, "consent-revoke@example.com")
    config = client.app.state.settings
    config.model_provider = "openai"
    config.openai_api_key = "synthetic-api-key"
    configure_synthetic_model_pricing(config)
    disclosure = client.get("/api/v1/auth/model-disclosure")
    assert disclosure.json()["input_cost_per_million_usd"] == "1"
    assert disclosure.json()["max_cost_per_call_usd"] == "0.10"
    headers = {"Authorization": "Bearer " + token}
    enabled = client.put(
        "/api/v1/auth/ai-consent",
        headers=headers,
        json={"enabled": True, "disclosure_version": config.model_disclosure_version},
    )
    assert enabled.status_code == 200, enabled.text

    revoked = client.put("/api/v1/auth/ai-consent", headers=headers, json={"enabled": False})

    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["ai_consent_at"] is None


def test_worker_external_review_completes_with_ready_status(client, monkeypatch) -> None:
    from personal_ai_life_os.api.routes import reviews
    from personal_ai_life_os.services.jobs import run_background_job_once

    token = token_for(client, "worker-ready@example.com")
    import_memory(client, token)
    state = client.app.state
    state.settings.processing_mode = "worker"
    state.settings.model_provider = "openai"
    state.settings.openai_api_key = "synthetic-api-key"
    configure_synthetic_model_pricing(state.settings)
    headers = {"Authorization": "Bearer " + token}
    consent = {"enabled": True, "disclosure_version": state.settings.model_disclosure_version}
    assert client.put("/api/v1/auth/ai-consent", headers=headers, json=consent).status_code == 200
    generation = client.post(
        "/api/v1/reviews/generate",
        headers=headers,
        json={"period_start": "2026-11-16", "period_end": "2026-11-18", "use_external_model": True},
    )
    assert generation.status_code == 201, generation.text
    review = generation.json()
    assert review["status"] == "processing"

    def ready_model(items, _config):
        return (
            {"facts": [{"text": "Synthetic model fact", "source_ids": [items[0].id]}], "suggestions": []},
            12,
            100,
            20,
        )

    monkeypatch.setattr(reviews, "_call_openai", ready_model)
    assert run_background_job_once(state.session_factory, state.object_store, state.settings)
    completed = client.get("/api/v1/reviews/" + review["id"], headers=headers).json()
    assert completed["status"] == "draft"
    assert completed["draft"]["model"]["status"] == "ready"
    assert completed["draft"]["facts"][0]["text"] == "Synthetic model fact"


def test_queued_review_cannot_overwrite_a_user_confirmation(client, monkeypatch) -> None:
    import httpx

    from personal_ai_life_os.api.routes import reviews
    from personal_ai_life_os.services.jobs import run_background_job_once

    token = token_for(client, "queued-review@example.com")
    import_memory(client, token)
    state = client.app.state
    state.settings.processing_mode = "worker"
    state.settings.model_provider = "openai"
    state.settings.openai_api_key = "synthetic-api-key"
    configure_synthetic_model_pricing(state.settings)
    headers = {"Authorization": "Bearer " + token}
    consent = {"enabled": True, "disclosure_version": state.settings.model_disclosure_version}
    assert client.put("/api/v1/auth/ai-consent", headers=headers, json=consent).status_code == 200
    period = {"period_start": "2026-11-16", "period_end": "2026-11-18"}
    generation = client.post(
        "/api/v1/reviews/generate", headers=headers, json={**period, "use_external_model": True}
    )
    assert generation.status_code == 201, generation.text
    review = generation.json()
    assert review["status"] == "processing"
    review_path = "/api/v1/reviews/" + review["id"]
    job_id = review["draft"]["model"]["job_id"]
    assert client.get(review_path, headers=headers).json()["draft"]["model"]["job_id"] == job_id
    retry_path = "/api/v1/jobs/" + job_id + "/retry"
    edit = {"final_text": "My verified edit."}
    for response in (
        client.patch(review_path, headers=headers, json=edit),
        client.post("/api/v1/reviews/generate", headers=headers, json=period),
    ):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "review_processing"

    assert client.put("/api/v1/auth/ai-consent", headers=headers, json={"enabled": False}).status_code == 200
    assert client.put("/api/v1/auth/ai-consent", headers=headers, json=consent).status_code == 200
    assert client.post(retry_path, headers=headers).status_code == 200
    assert client.get(review_path, headers=headers).json()["status"] == "processing"

    def provider_unavailable(*_args):
        raise httpx.ConnectError("Synthetic provider failure")

    monkeypatch.setattr(reviews, "_call_openai", provider_unavailable)
    assert run_background_job_once(state.session_factory, state.object_store, state.settings)
    assert client.get(review_path, headers=headers).json()["status"] == "draft"
    saved = client.patch(review_path, headers=headers, json=edit)
    assert saved.status_code == 200
    assert saved.json()["status"] == "confirmed"
    assert saved.json()["final_text"] == edit["final_text"]


def test_model_suggestion_can_be_saved_as_source_linked_reminder(client, monkeypatch) -> None:
    import personal_ai_life_os.api.routes.reviews as review_routes

    token = token_for(client, "suggestion-reminder@example.com")
    _, item_ids = import_memory(client, token)
    config = client.app.state.settings
    config.model_provider = "openai"
    config.openai_api_key = "synthetic-api-key"
    configure_synthetic_model_pricing(config)
    headers = {"Authorization": "Bearer " + token}
    consent = client.put(
        "/api/v1/auth/ai-consent",
        headers=headers,
        json={"enabled": True, "disclosure_version": config.model_disclosure_version},
    )
    assert consent.status_code == 200, consent.text

    def suggest(items, _config):
        return (
            {
                "facts": [],
                "suggestions": [{"text": "Review the selected synthetic import flow.", "source_ids": [items[0].id]}],
            },
            1,
            12,
            5,
        )

    monkeypatch.setattr(review_routes, "_call_openai", suggest)
    response = client.post(
        "/api/v1/reviews/generate",
        headers=headers,
        json={"period_start": "2026-11-16", "period_end": "2026-11-18", "use_external_model": True},
    )
    assert response.status_code == 201, response.text
    suggestion = response.json()["draft"]["suggestions"][0]
    assert suggestion["source_ids"]

    reminder = client.post(
        "/api/v1/reminders",
        headers=headers,
        json={"title": suggestion["text"], "source_item_ids": suggestion["source_ids"]},
    )
    assert reminder.status_code == 201, reminder.text
    with ZipFile(BytesIO(client.get("/api/v1/account/archive", headers=headers).content)) as archive:
        saved = json.loads(archive.read("reminders.json"))
        model_usage = json.loads(archive.read("model-usage.json"))
    assert saved[0]["source_ids"] == suggestion["source_ids"]
    assert set(suggestion["source_ids"]).issubset(item_ids)
    assert model_usage[0]["cost_usd"] is not None


def test_review_suggestions_can_be_edited_dismissed_and_restored(client, monkeypatch) -> None:
    import personal_ai_life_os.api.routes.reviews as review_routes

    token = token_for(client, "suggestion-edit@example.com")
    _, item_ids = import_memory(client, token)
    config = client.app.state.settings
    config.model_provider = "openai"
    config.openai_api_key = "synthetic-api-key"
    configure_synthetic_model_pricing(config)
    headers = {"Authorization": "Bearer " + token}
    consent = client.put(
        "/api/v1/auth/ai-consent",
        headers=headers,
        json={"enabled": True, "disclosure_version": config.model_disclosure_version},
    )
    assert consent.status_code == 200, consent.text

    def suggest(items, _config):
        return (
            {
                "facts": [],
                "suggestions": [
                    {"text": "Review the import flow.", "source_ids": [items[0].id]},
                    {"text": "Annotate the first item.", "source_ids": [items[0].id]},
                ],
            },
            1,
            12,
            5,
        )

    monkeypatch.setattr(review_routes, "_call_openai", suggest)
    response = client.post(
        "/api/v1/reviews/generate",
        headers=headers,
        json={"period_start": "2026-11-16", "period_end": "2026-11-18", "use_external_model": True},
    )
    assert response.status_code == 201, response.text
    review = response.json()
    first = review["draft"]["suggestions"][0]
    assert first["status"] == "pending"
    assert set(first["source_ids"]).issubset(item_ids)
    assert "Review the import flow." in review["final_text"]

    edited = client.patch(
        "/api/v1/reviews/" + review["id"] + "/suggestions/0",
        headers=headers,
        json={"text": "  Review the edited import flow.  "},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["draft"]["suggestions"][0]["text"] == "Review the edited import flow."
    assert edited.json()["draft"]["suggestions"][0]["source_ids"] == first["source_ids"]
    assert "Review the edited import flow." in edited.json()["final_text"]
    assert "Review the import flow." not in edited.json()["final_text"]

    dismissed = client.patch(
        "/api/v1/reviews/" + review["id"] + "/suggestions/0",
        headers=headers,
        json={"status": "dismissed"},
    )
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["draft"]["suggestions"][0]["status"] == "dismissed"
    assert "Review the edited import flow." not in dismissed.json()["final_text"]
    assert "Annotate the first item." in dismissed.json()["final_text"]

    restored = client.patch(
        "/api/v1/reviews/" + review["id"] + "/suggestions/0",
        headers=headers,
        json={"status": "pending", "text": "Restored follow-up."},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["draft"]["suggestions"][0]["status"] == "pending"
    assert "Restored follow-up." in restored.json()["final_text"]

    missing = client.patch(
        "/api/v1/reviews/" + review["id"] + "/suggestions/9",
        headers=headers,
        json={"status": "dismissed"},
    )
    assert missing.status_code == 404
    other = token_for(client, "other-suggestion@example.com")
    assert (
        client.patch(
            "/api/v1/reviews/" + review["id"] + "/suggestions/0",
            headers={"Authorization": "Bearer " + other},
            json={"status": "dismissed"},
        ).status_code
        == 404
    )

    confirmed = client.patch(
        "/api/v1/reviews/" + review["id"], headers=headers, json={"final_text": "A checked reflection."}
    )
    assert confirmed.status_code == 200
    assert (
        client.patch(
            "/api/v1/reviews/" + review["id"] + "/suggestions/1",
            headers=headers,
            json={"status": "dismissed"},
        ).status_code
        == 409
    )


def test_external_review_failure_falls_back_to_cited_template(client, monkeypatch) -> None:
    import httpx

    import personal_ai_life_os.api.routes.reviews as review_routes

    token = token_for(client, "model-fallback@example.com")
    import_memory(client, token)
    config = client.app.state.settings
    config.model_provider = "openai"
    config.openai_api_key = "synthetic-api-key"
    configure_synthetic_model_pricing(config)
    headers = {"Authorization": "Bearer " + token}
    consent = client.put(
        "/api/v1/auth/ai-consent",
        headers=headers,
        json={"enabled": True, "disclosure_version": config.model_disclosure_version},
    )
    assert consent.status_code == 200, consent.text

    def fail_model(*_args, **_kwargs):
        raise httpx.TimeoutException("synthetic provider failure")

    monkeypatch.setattr(review_routes, "_call_openai", fail_model)
    response = client.post(
        "/api/v1/reviews/generate",
        headers=headers,
        json={"period_start": "2026-11-16", "period_end": "2026-11-18", "use_external_model": True},
    )

    assert response.status_code == 201, response.text
    review = response.json()
    assert review["draft"]["model"]["status"] == "fallback"
    assert review["draft"]["facts"]
    assert all(fact["source_ids"] for fact in review["draft"]["facts"])
    archive = client.get("/api/v1/account/archive", headers=headers)
    with ZipFile(BytesIO(archive.content)) as bundle:
        model_run = json.loads(bundle.read("model-usage.json"))[0]
    assert model_run["cost_usd"] is not None
    assert model_run["input_tokens"] > 0


def test_external_review_budget_uses_template_without_sending_when_reserve_is_too_high(client, monkeypatch) -> None:
    import personal_ai_life_os.api.routes.reviews as review_routes

    token = token_for(client, "model-budget@example.com")
    import_memory(client, token)
    config = client.app.state.settings
    config.model_provider = "openai"
    config.openai_api_key = "synthetic-api-key"
    config.model_input_cost_per_million_usd = Decimal(500)
    config.model_output_cost_per_million_usd = Decimal(500)
    config.model_max_cost_per_call_usd = Decimal("0.10")
    headers = {"Authorization": "Bearer " + token}
    consent = client.put(
        "/api/v1/auth/ai-consent",
        headers=headers,
        json={"enabled": True, "disclosure_version": config.model_disclosure_version},
    )
    assert consent.status_code == 200, consent.text

    def model_must_not_be_called(*_args, **_kwargs):
        raise AssertionError("The model request should be stopped by the configured budget.")

    monkeypatch.setattr(review_routes, "_call_openai", model_must_not_be_called)
    response = client.post(
        "/api/v1/reviews/generate",
        headers=headers,
        json={"period_start": "2026-11-16", "period_end": "2026-11-18", "use_external_model": True},
    )

    assert response.status_code == 201, response.text
    assert response.json()["draft"]["model"]["status"] == "budget_fallback"
    assert response.json()["draft"]["facts"]


def test_source_deletion_invalidates_derived_review_and_clears_evidence(client) -> None:
    token = token_for(client, "delete-source@example.com")
    source_id, _ = import_memory(client, token)
    headers = {"Authorization": "Bearer " + token}
    review_response = client.post(
        "/api/v1/reviews/generate",
        headers=headers,
        json={"period_start": "2026-11-16", "period_end": "2026-11-18"},
    )
    review_id = review_response.json()["id"]
    assert client.delete("/api/v1/sources/" + source_id, headers=headers).status_code == 204
    review = client.get("/api/v1/reviews/" + review_id, headers=headers)
    assert review.status_code == 200
    assert review.json()["status"] == "invalidated"
    assert review.json()["final_text"] is None
    assert review.json()["source_items"] == []
    assert client.get("/api/v1/reviews/" + review_id + "/export.md", headers=headers).status_code == 410
    source_tombstones = [
        json.loads(payload)
        for _, payload in client.app.state.object_store.list_deletion_tombstones()
        if json.loads(payload).get("source_id") == source_id
    ]
    assert source_tombstones and source_tombstones[0].get("completed_at")


def test_reminders_are_owner_scoped_and_have_explicit_transitions(client) -> None:
    token = token_for(client, "reminder@example.com")
    _, item_ids = import_memory(client, token)
    headers = {"Authorization": "Bearer " + token}
    reminder = client.post(
        "/api/v1/reminders",
        headers=headers,
        json={"title": "Follow up on the review", "source_item_ids": item_ids[:1]},
    )
    assert reminder.status_code == 201, reminder.text
    reminder_id = reminder.json()["id"]
    snoozed = client.patch(
        "/api/v1/reminders/" + reminder_id + "/status", headers=headers, json={"status": "snoozed"}
    )
    assert snoozed.status_code == 200
    assert snoozed.json()["status"] == "snoozed"
    other = token_for(client, "other-reminder@example.com")
    assert client.patch(
        "/api/v1/reminders/" + reminder_id + "/status",
        headers={"Authorization": "Bearer " + other},
        json={"status": "completed"},
    ).status_code == 404


def test_account_archive_and_delete_remove_all_access(client) -> None:
    token = token_for(client, "archive@example.com")
    import_memory(client, token)
    headers = {"Authorization": "Bearer " + token}
    response = client.get("/api/v1/account/archive", headers=headers)
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert {
            "account.json",
            "sources.json",
            "timeline.json",
            "sync-runs.json",
            "reviews.json",
            "reminders.json",
            "model-usage.json",
        } <= names
        assert any(name.startswith("originals/") for name in names)
        assert b"synthetic notes" in archive.read("sources.json")

    deleted = client.delete("/api/v1/account", headers=headers)
    assert deleted.status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    tombstones = client.app.state.object_store.list_deletion_tombstones()
    assert len(tombstones) == 1
    assert json.loads(tombstones[0][1])["completed_at"]


def test_single_item_delete_removes_shared_source_and_raw_object(client) -> None:
    token = token_for(client, "single-delete@example.com")
    source_id, item_ids = import_memory(client, token)
    headers = {"Authorization": "Bearer " + token}
    deleted = client.delete("/api/v1/items/" + item_ids[0], headers=headers)
    assert deleted.status_code == 204
    assert client.get("/api/v1/sources/" + source_id, headers=headers).status_code == 404
    assert client.get("/api/v1/items/" + item_ids[1], headers=headers).status_code == 404
    assert client.get("/api/v1/items/" + item_ids[0] + "/raw", headers=headers).status_code == 404


def test_restore_replays_erasure_tombstones_before_serving_account(client) -> None:
    from personal_ai_life_os.services.deletion import replay_deletion_tombstones

    token = token_for(client, "restore-delete@example.com")
    source_id, _ = import_memory(client, token)
    headers = {"Authorization": "Bearer " + token}
    owner_id = client.get("/api/v1/auth/me", headers=headers).json()["id"]
    store = client.app.state.object_store
    store.write_deletion_tombstone(owner_id, json.dumps({"owner_id": owner_id, "requested_at": "2026-11-25T00:00:00+00:00"}).encode())

    assert replay_deletion_tombstones(client.app.state.session_factory, store) == 1
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert client.get("/api/v1/sources/" + source_id, headers=headers).status_code == 401


def test_restore_replays_source_deletion_tombstones_and_scrubs_reviews(client) -> None:
    from personal_ai_life_os.services.deletion import replay_deletion_tombstones

    token = token_for(client, "restore-source-delete@example.com")
    source_id, _ = import_memory(client, token)
    headers = {"Authorization": "Bearer " + token}
    review = client.post(
        "/api/v1/reviews/generate", headers=headers,
        json={"period_start": "2026-11-16", "period_end": "2026-11-18"},
    ).json()
    owner_id = client.get("/api/v1/auth/me", headers=headers).json()["id"]
    store = client.app.state.object_store
    store.write_source_deletion_tombstone(
        owner_id,
        source_id,
        json.dumps({"owner_id": owner_id, "source_id": source_id, "requested_at": "2026-11-25T00:00:00+00:00"}).encode(),
    )

    assert replay_deletion_tombstones(client.app.state.session_factory, store) == 1
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    assert client.get("/api/v1/sources/" + source_id, headers=headers).status_code == 404
    saved_review = client.get("/api/v1/reviews/" + review["id"], headers=headers)
    assert saved_review.json()["status"] == "invalidated"
    assert saved_review.json()["final_text"] is None


def test_metrics_are_restricted_and_report_only_aggregate_counts(client) -> None:
    metric_secret = "synthetic-metrics-secret-with-more-than-32-characters"
    client.app.state.settings.metrics_token = metric_secret
    assert client.get("/api/v1/metrics").status_code == 401
    response = client.get("/api/v1/metrics", headers={"Authorization": "Bearer " + metric_secret})
    assert response.status_code == 200
    body = response.json()
    assert "request_latency_p95_ms" in body
    assert "deletions_pending" in body
    assert "external_review_input_tokens" in body
    assert "external_model_estimated_cost_usd" in body
    assert "email" not in body
    assert "user_id" not in body


def test_photo_upload_is_reencoded_and_searchable_metadata_is_recorded(client, monkeypatch) -> None:
    import personal_ai_life_os.parsers.photo as photo_parser

    monkeypatch.setattr(photo_parser.shutil, "which", lambda _: "/usr/bin/tesseract")
    monkeypatch.setattr(photo_parser.pytesseract, "image_to_string", lambda *args, **kwargs: "OCR text from photo")
    token = token_for(client, "photo@example.com")
    headers = {"Authorization": "Bearer " + token}
    source = client.post(
        "/api/v1/sources",
        headers=headers,
        json={"kind": "photo", "name": "selected photo", "selected_scope": {}},
    )
    image = Image.new("RGB", (24, 16), "white")
    exif = image.getexif()
    exif[305] = "private metadata"
    original = BytesIO()
    image.save(original, format="JPEG", exif=exif)
    imported = client.post(
        "/api/v1/sources/" + source.json()["id"] + "/imports",
        headers=headers,
        files={"file": ("photo.jpg", original.getvalue(), "image/jpeg")},
        data={"captured_at": "2026-11-20T10:00:00+08:00", "captured_timezone": "Asia/Shanghai"},
    )
    assert imported.status_code == 201, imported.text
    item = imported.json()["items"][0]
    assert item["content_text"] == "OCR text from photo"
    assert item["metadata"]["location_metadata_removed"] is True
    assert item["metadata"]["ocr_status"] == "extracted"
    assert item["source_timezone"] == "Asia/Shanghai"
    raw = client.get("/api/v1/items/" + item["id"] + "/raw", headers=headers)
    with Image.open(BytesIO(raw.content)) as safe_image:
        assert safe_image.getexif().get(305) is None
        assert safe_image.getexif().get(34853) is None


def test_photo_description_requires_consent_and_is_only_searchable_after_confirmation(client, monkeypatch) -> None:
    import personal_ai_life_os.api.routes.items as item_routes

    token = token_for(client, "photo-description@example.com")
    headers = {"Authorization": "Bearer " + token}
    source = client.post(
        "/api/v1/sources", headers=headers,
        json={"kind": "photo", "name": "selected photo", "selected_scope": {}},
    )
    image = Image.new("RGB", (12, 12), "blue")
    payload = BytesIO()
    image.save(payload, format="JPEG")
    imported = client.post(
        "/api/v1/sources/" + source.json()["id"] + "/imports",
        headers=headers,
        files={"file": ("blue.jpg", payload.getvalue(), "image/jpeg")},
    )
    item_id = imported.json()["items"][0]["id"]
    assert client.post("/api/v1/items/" + item_id + "/describe", headers=headers).status_code == 409

    config = client.app.state.settings
    config.model_provider = "openai"
    config.openai_api_key = "synthetic-api-key"
    configure_synthetic_model_pricing(config)
    consent = client.put(
        "/api/v1/auth/ai-consent", headers=headers,
        json={"enabled": True, "disclosure_version": config.model_disclosure_version},
    )
    assert consent.status_code == 200, consent.text

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": "A blue square on a plain background."}}],
                "usage": {"prompt_tokens": 80, "completion_tokens": 12},
            }

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def __init__(self, *args, **kwargs):
            pass

        def post(self, url, *, headers, json):
            assert "base64," in json["messages"][1]["content"][1]["image_url"]["url"]
            assert "untrusted data" in json["messages"][0]["content"]
            return Response()

    monkeypatch.setattr(item_routes.httpx, "Client", Client)
    draft = client.post("/api/v1/items/" + item_id + "/describe", headers=headers)
    assert draft.status_code == 200, draft.text
    assert draft.json()["requires_confirmation"] is True
    assert client.get("/api/v1/timeline", headers=headers, params={"q": "blue square"}).json()["total"] == 0

    saved = client.post(
        "/api/v1/items/" + item_id + "/description",
        headers=headers,
        json={"description": draft.json()["description"]},
    )
    assert saved.status_code == 200, saved.text
    matches = client.get("/api/v1/timeline", headers=headers, params={"q": "blue square"})
    assert matches.json()["total"] == 1
    assert "Photo description (user-confirmed)" in matches.json()["items"][0]["content_text"]
