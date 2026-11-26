import json
from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile

from sqlalchemy import select
from test_reviews_account import configure_synthetic_model_pricing, import_memory, token_for

from personal_ai_life_os.models import GraphEntity, ReviewSchedule


def headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def configure_named_provider(config) -> str:
    config.model_provider = "openai"
    config.openai_api_key = "default-synthetic-key"
    config.model_privacy_url = "https://example.test/default-privacy"
    configure_synthetic_model_pricing(config)
    config.model_providers = json.dumps(
        {
            "research": {
                "base_url": "https://models.example.test/v1",
                "api_key": "named-synthetic-secret",
                "model": "model-b",
                "models": ["model-b", "model-b-mini"],
                "input_cost_per_million_usd": "2",
                "output_cost_per_million_usd": "3",
                "privacy_url": "https://models.example.test/privacy",
                "retention": "Synthetic provider retention policy for evaluation only.",
                "disclosure_version": "research-v1",
            },
            "local": {
                "base_url": "http://127.0.0.1:11434/v1",
                "model": "local-model",
                "models": ["local-model"],
                "input_cost_per_million_usd": "0.01",
                "output_cost_per_million_usd": "0.01",
                "local": True,
                "retention": "Local loopback provider keeps generated content on this machine.",
                "disclosure_version": "local-v1",
            },
        }
    )
    return "research-v1"


def test_provider_registry_hides_secrets_and_requires_per_provider_consent(client) -> None:
    token = token_for(client, "m9-provider@example.test")
    disclosure_version = configure_named_provider(client.app.state.settings)
    providers = client.get("/api/v1/model-providers", headers=headers(token)).json()
    assert [entry["id"] for entry in providers] == ["default", "research", "local"]
    serialized = json.dumps(providers)
    assert "named-synthetic-secret" not in serialized
    assert "default-synthetic-key" not in serialized
    assert "base_url" not in serialized
    assert next(entry for entry in providers if entry["id"] == "local")["available"] is True

    assert client.put(
        "/api/v1/auth/ai-consent",
        headers=headers(token),
        json={"enabled": True, "disclosure_version": client.app.state.settings.model_disclosure_version},
    ).status_code == 200
    import_memory(client, token)
    denied = client.post(
        "/api/v1/reviews/generate",
        headers=headers(token),
        json={
            "period_start": "2026-11-16",
            "period_end": "2026-11-18",
            "use_external_model": True,
            "provider_id": "research",
            "model": "model-b-mini",
        },
    )
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "model_consent_required"

    granted = client.put(
        "/api/v1/model-providers/consent",
        headers=headers(token),
        json={"enabled": True, "provider_id": "research", "disclosure_version": disclosure_version},
    )
    assert granted.status_code == 200, granted.text
    providers = client.get("/api/v1/model-providers", headers=headers(token)).json()
    research = next(entry for entry in providers if entry["id"] == "research")
    assert research["consent"]["consented"] is True
    assert next(entry for entry in providers if entry["id"] == "default")["consent"]["consented"] is True

    revoked = client.put(
        "/api/v1/model-providers/consent",
        headers=headers(token),
        json={"enabled": False, "provider_id": "research"},
    )
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"] is not None


def test_selected_provider_is_used_and_usage_archive_matches(client, monkeypatch) -> None:
    import personal_ai_life_os.api.routes.reviews as review_routes

    token = token_for(client, "m9-selected@example.test")
    disclosure_version = configure_named_provider(client.app.state.settings)
    _, item_ids = import_memory(client, token)
    assert client.put(
        "/api/v1/model-providers/consent",
        headers=headers(token),
        json={"enabled": True, "provider_id": "research", "disclosure_version": disclosure_version},
    ).status_code == 200

    def model_result(items, provider):
        assert provider.id == "research"
        assert provider.model == "model-b-mini"
        return (
            {"facts": [{"text": items[0].content_text, "source_ids": [items[0].id]}], "suggestions": []},
            15,
            100,
            20,
        )

    monkeypatch.setattr(review_routes, "_call_openai", model_result)
    response = client.post(
        "/api/v1/reviews/generate",
        headers=headers(token),
        json={
            "period_start": "2026-11-16",
            "period_end": "2026-11-18",
            "use_external_model": True,
            "provider_id": "research",
            "model": "model-b-mini",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["draft"]["model"]["provider"] == "research"
    assert body["draft"]["model"]["model"] == "model-b-mini"
    assert body["draft"]["facts"][0]["source_ids"][0] in item_ids

    budget = client.get("/api/v1/budget", headers=headers(token), params={"period": "week"}).json()
    assert budget["period"] == "week"
    assert budget["by_provider"][0]["provider"] == "research"
    assert budget["by_provider"][0]["input_tokens"] == 100
    assert budget["by_provider"][0]["output_tokens"] == 20
    with ZipFile(BytesIO(client.get("/api/v1/account/archive", headers=headers(token)).content)) as archive:
        usage = json.loads(archive.read("model-usage.json"))
        consents = json.loads(archive.read("model-consents.json"))
        versions = json.loads(archive.read("review-versions.json"))
    assert usage[0]["provider"] == "research"
    assert usage[0]["model"] == "model-b-mini"
    assert consents[0]["provider_id"] == "research"
    assert versions[0]["review_id"] == body["id"]


def test_review_insights_are_source_linked_and_versions_are_readable(client) -> None:
    token = token_for(client, "m9-insights@example.test")
    source = client.post(
        "/api/v1/sources",
        headers=headers(token),
        json={"kind": "memory_markdown", "name": "insight notes", "selected_scope": {}},
    )
    assert source.status_code == 201, source.text
    source_id = source.json()["id"]
    imported = client.post(
        f"/api/v1/sources/{source_id}/imports",
        headers=headers(token),
        files={
            "file": (
                "insight.md",
                "# 2026-11-16 Release plan\n\n承诺在 2026-11-21 前完成发布，目标是毕业项目。".encode(),
                "text/markdown",
            )
        },
    )
    assert imported.status_code == 201, imported.text
    item_ids = [item["id"] for item in imported.json()["items"]]
    owner_id = client.get("/api/v1/auth/me", headers=headers(token)).json()["id"]
    with client.app.state.session_factory() as session:
        session.add(
            GraphEntity(
                owner_id=owner_id,
                entity_type="goal",
                name="毕业项目",
                normalized_name="毕业项目",
                status="active",
                confidence=0.95,
            )
        )
        session.commit()

    generated = client.post(
        "/api/v1/reviews/generate",
        headers=headers(token),
        json={"period_start": "2026-11-15", "period_end": "2026-11-17"},
    )
    assert generated.status_code == 201, generated.text
    review = generated.json()
    assert review["version_number"] == 1
    assert review["insights"]["commitments"][0]["due_date"] == "2026-11-21"
    assert review["insights"]["commitments"][0]["source_ids"] == item_ids
    assert review["insights"]["goals"][0]["name"] == "毕业项目"
    assert review["insights"]["goals"][0]["source_ids"] == item_ids
    assert "Commitments and due dates" in review["final_text"]
    assert "Goal links" in review["final_text"]

    saved = client.patch(
        f"/api/v1/reviews/{review['id']}",
        headers=headers(token),
        json={"final_text": "Verified review version two."},
    )
    assert saved.status_code == 200
    assert saved.json()["version_number"] == 2
    versions = client.get(f"/api/v1/reviews/{review['id']}/versions", headers=headers(token)).json()
    assert [entry["version_number"] for entry in versions] == [1, 2]
    assert versions[0]["final_text"] != versions[1]["final_text"]
    assert versions[1]["reason"] == "confirmed"

    follow_up = client.post(
        f"/api/v1/sources/{source_id}/imports",
        headers=headers(token),
        files={
            "file": (
                "follow-up.md",
                "# 2026-11-18 Release follow-up\n\n继续推进毕业项目并检查发布承诺。".encode(),
                "text/markdown",
            )
        },
    )
    assert follow_up.status_code == 201, follow_up.text
    next_review = client.post(
        "/api/v1/reviews/generate",
        headers=headers(token),
        json={"period_start": "2026-11-17", "period_end": "2026-11-19"},
    )
    assert next_review.status_code == 201, next_review.text
    assert next_review.json()["insights"]["trends"]
    assert any(
        trend["previous_count"] > 0
        for trend in next_review.json()["insights"]["trends"]
    )


def test_schedule_persists_provider_and_budget_fallback_is_recorded(client) -> None:
    token = token_for(client, "m9-schedule@example.test")
    disclosure_version = configure_named_provider(client.app.state.settings)
    assert client.put(
        "/api/v1/model-providers/consent",
        headers=headers(token),
        json={"enabled": True, "provider_id": "research", "disclosure_version": disclosure_version},
    ).status_code == 200
    schedule = client.put(
        "/api/v1/review-schedule",
        headers=headers(token),
        json={
            "enabled": True,
            "weekday": 6,
            "local_hour": 20,
            "local_minute": 0,
            "timezone": "Asia/Shanghai",
            "use_external_model": True,
            "provider_id": "research",
            "model": "model-b-mini",
        },
    )
    assert schedule.status_code == 200, schedule.text
    assert schedule.json()["provider_id"] == "research"
    assert schedule.json()["model"] == "model-b-mini"
    owner_id = client.get("/api/v1/auth/me", headers=headers(token)).json()["id"]
    with client.app.state.session_factory() as session:
        stored = session.scalar(select(ReviewSchedule).where(ReviewSchedule.owner_id == owner_id))
        assert stored is not None
        assert stored.provider_id == "research"
        assert stored.model == "model-b-mini"

    import_memory(client, token)
    client.app.state.settings.model_monthly_budget_usd = Decimal("0.000001")
    generated = client.post(
        "/api/v1/reviews/generate",
        headers=headers(token),
        json={
            "period_start": "2026-11-16",
            "period_end": "2026-11-18",
            "use_external_model": True,
            "provider_id": "research",
            "model": "model-b-mini",
        },
    )
    assert generated.status_code == 201, generated.text
    assert generated.json()["draft"]["model"]["status"] == "budget_fallback"
    budget = client.get("/api/v1/budget", headers=headers(token)).json()
    assert budget["over_budget"] is False


def test_revoking_one_provider_cancels_only_its_model_jobs(client) -> None:
    token = token_for(client, "m9-provider-jobs@example.test")
    disclosure_version = configure_named_provider(client.app.state.settings)
    client.app.state.settings.processing_mode = "worker"
    import_memory(client, token)
    assert client.put(
        "/api/v1/auth/ai-consent",
        headers=headers(token),
        json={"enabled": True, "disclosure_version": client.app.state.settings.model_disclosure_version},
    ).status_code == 200
    assert client.put(
        "/api/v1/model-providers/consent",
        headers=headers(token),
        json={"enabled": True, "provider_id": "research", "disclosure_version": disclosure_version},
    ).status_code == 200
    default_review = client.post(
        "/api/v1/reviews/generate",
        headers=headers(token),
        json={"period_start": "2026-11-16", "period_end": "2026-11-18", "use_external_model": True},
    )
    named_review = client.post(
        "/api/v1/reviews/generate",
        headers=headers(token),
        json={
            "period_start": "2026-11-17",
            "period_end": "2026-11-19",
            "use_external_model": True,
            "provider_id": "research",
        },
    )
    assert default_review.status_code == 201, default_review.text
    assert named_review.status_code == 201, named_review.text
    default_job = default_review.json()["draft"]["model"]["job_id"]
    named_job = named_review.json()["draft"]["model"]["job_id"]
    assert client.put(
        "/api/v1/model-providers/consent",
        headers=headers(token),
        json={"enabled": False, "provider_id": "research"},
    ).status_code == 200
    assert client.get(f"/api/v1/jobs/{named_job}", headers=headers(token)).json()["status"] == "cancelled"
    assert client.get(f"/api/v1/jobs/{default_job}", headers=headers(token)).json()["status"] == "queued"
