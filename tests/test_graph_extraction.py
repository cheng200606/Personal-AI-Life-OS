import json
from decimal import Decimal

import httpx
from sqlalchemy import select
from test_reviews_account import (
    configure_synthetic_model_pricing,
    import_memory,
    token_for,
)

from personal_ai_life_os.models import ExtractionRun, ModelRun
from personal_ai_life_os.services import graph_extraction


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _configure(client, *, budget: str = "5.00") -> None:
    config = client.app.state.settings
    config.model_provider = "openai"
    config.openai_api_key = "synthetic-api-key"
    configure_synthetic_model_pricing(config)
    config.model_monthly_budget_usd = Decimal(budget)


def _consent(client, token: str, source_id: str) -> None:
    response = client.patch(
        "/api/v1/sources/" + source_id + "/cloud-consent",
        headers=_headers(token),
        json={
            "enabled": True,
            "consent_version": client.app.state.settings.graph_cloud_consent_version,
        },
    )
    assert response.status_code == 200, response.text


def _synthetic_graph(items, _config, _provider=None):
    return (
        {
            "entities": [
                {
                    "key": "p1",
                    "type": "project",
                    "name": "Life OS",
                    "summary": "Local personal memory project.",
                    "confidence": 0.95,
                    "evidence": [{"item_id": items[0].id, "quote": "Postgres"}],
                },
                {
                    "key": "g1",
                    "type": "goal",
                    "name": "Evidence graph Q&A",
                    "confidence": 0.6,
                    "evidence": [{"item_id": items[0].id, "quote": "import preview"}],
                },
            ],
            "relations": [
                {
                    "from_key": "p1",
                    "to_key": "g1",
                    "type": "has_goal",
                    "confidence": 0.9,
                    "evidence": [{"item_id": items[0].id, "quote": "Postgres"}],
                }
            ],
        },
        12,
        100,
        50,
    )


def test_extraction_persists_graph_and_low_confidence_review(client, monkeypatch) -> None:
    token = token_for(client, "graph-extract@example.com")
    source_id, item_ids = import_memory(client, token)
    _configure(client)
    _consent(client, token, source_id)
    monkeypatch.setattr(graph_extraction, "_call_graph_model", _synthetic_graph)

    response = client.post(
        "/api/v1/extractions",
        headers=_headers(token),
        json={"item_ids": item_ids[:2]},
    )
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["status"] == "completed"
    assert run["entity_count"] == 2
    assert run["relation_count"] == 1
    assert run["review_count"] == 1
    assert run["cost_usd"] is not None
    assert run["budget_limit_usd"] == "5.00" or Decimal(run["budget_limit_usd"]) == Decimal("5.00")

    entities = client.get(
        "/api/v1/graph/entities", headers=_headers(token)
    ).json()
    assert entities["total"] == 2
    statuses = {entity["name"]: entity["status"] for entity in entities["items"]}
    assert statuses["Life OS"] == "active"
    assert statuses["Evidence graph Q&A"] == "pending_review"
    assert any(entity["evidence"] for entity in entities["items"])
    relations = client.get(
        "/api/v1/graph/relations", headers=_headers(token)
    ).json()
    assert relations["total"] == 1
    assert relations["items"][0]["relation_type"] == "has_goal"


def test_repeated_extraction_is_idempotent(client, monkeypatch) -> None:
    token = token_for(client, "graph-idempotent@example.com")
    source_id, item_ids = import_memory(client, token)
    _configure(client)
    _consent(client, token, source_id)
    calls = 0

    def fake(items, config, provider):
        nonlocal calls
        calls += 1
        return _synthetic_graph(items, config, provider)

    monkeypatch.setattr(graph_extraction, "_call_graph_model", fake)
    first = client.post(
        "/api/v1/extractions", headers=_headers(token), json={"item_ids": item_ids[:2]}
    )
    second = client.post(
        "/api/v1/extractions", headers=_headers(token), json={"item_ids": item_ids[:2]}
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert calls == 1
    assert client.get("/api/v1/graph/entities", headers=_headers(token)).json()["total"] == 2
    assert client.get("/api/v1/graph/relations", headers=_headers(token)).json()["total"] == 1
    with client.app.state.session_factory() as session:
        runs = list(session.scalars(select(ModelRun).where(ModelRun.purpose == "graph_extraction")))
        assert len(runs) == 1


def test_extraction_requires_consent_and_owner_scope(client, monkeypatch) -> None:
    token = token_for(client, "graph-no-consent@example.com")
    source_id, item_ids = import_memory(client, token)
    _configure(client)
    monkeypatch.setattr(graph_extraction, "_call_graph_model", _synthetic_graph)

    denied = client.post(
        "/api/v1/extractions", headers=_headers(token), json={"item_ids": item_ids[:1]}
    )
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "source_cloud_consent_required"

    _consent(client, token, source_id)
    other = token_for(client, "graph-other-owner@example.com")
    not_found = client.post(
        "/api/v1/extractions", headers=_headers(other), json={"item_ids": item_ids[:1]}
    )
    assert not_found.status_code == 404
    assert not_found.json()["error"]["code"] == "source_item_not_found"


def test_extraction_monthly_budget_blocks_call(client, monkeypatch) -> None:
    token = token_for(client, "graph-budget@example.com")
    source_id, item_ids = import_memory(client, token)
    _configure(client, budget="0.0000001")
    _consent(client, token, source_id)
    monkeypatch.setattr(graph_extraction, "_call_graph_model", _synthetic_graph)

    response = client.post(
        "/api/v1/extractions", headers=_headers(token), json={"item_ids": item_ids[:1]}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "model_budget_exceeded"


def test_extraction_warns_at_eighty_percent(client, monkeypatch) -> None:
    token = token_for(client, "graph-warning@example.com")
    source_id, item_ids = import_memory(client, token)
    _configure(client, budget="1.00")
    _consent(client, token, source_id)
    monkeypatch.setattr(graph_extraction, "_call_graph_model", _synthetic_graph)
    owner_id = client.get("/api/v1/auth/me", headers=_headers(token)).json()["id"]
    with client.app.state.session_factory() as session:
        session.add(
            ModelRun(
                owner_id=owner_id,
                provider="openai",
                model="synthetic-model",
                purpose="weekly_review",
                status="succeeded",
                prompt_version="test",
                latency_ms=1,
                input_tokens=1,
                output_tokens=1,
                cost_usd=Decimal("0.80"),
            )
        )
        session.commit()

    response = client.post(
        "/api/v1/extractions", headers=_headers(token), json={"item_ids": item_ids[:1]}
    )
    assert response.status_code == 201, response.text
    assert response.json()["budget_warning"] is True


def test_extraction_uses_requested_provider(client, monkeypatch) -> None:
    token = token_for(client, "graph-provider@example.com")
    source_id, item_ids = import_memory(client, token)
    _configure(client)
    client.app.state.settings.graph_model_providers = json.dumps(
        {
            "cheap": {
                "base_url": "https://example.invalid/v1",
                "api_key": "synthetic-provider-key",
                "model": "cheap-model",
                "input_cost_per_million_usd": "1",
                "output_cost_per_million_usd": "1",
            }
        }
    )
    _consent(client, token, source_id)
    captured: dict[str, str] = {}

    def fake(items, config, provider):
        captured["provider"] = provider.name
        captured["model"] = provider.model
        return _synthetic_graph(items, config, provider)

    monkeypatch.setattr(graph_extraction, "_call_graph_model", fake)
    response = client.post(
        "/api/v1/extractions",
        headers=_headers(token),
        json={"item_ids": item_ids[:1], "provider": "cheap"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["provider"] == "cheap"
    assert response.json()["model"] == "cheap-model"
    assert captured == {"provider": "cheap", "model": "cheap-model"}


def test_extraction_failure_is_recorded(client, monkeypatch) -> None:
    token = token_for(client, "graph-failure@example.com")
    source_id, item_ids = import_memory(client, token)
    _configure(client)
    _consent(client, token, source_id)

    def fail(_items, _config, _provider):
        raise httpx.TimeoutException("synthetic timeout")

    monkeypatch.setattr(graph_extraction, "_call_graph_model", fail)
    response = client.post(
        "/api/v1/extractions", headers=_headers(token), json={"item_ids": item_ids[:1]}
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "graph_extraction_failed"
    with client.app.state.session_factory() as session:
        run = session.scalar(select(ExtractionRun))
        assert run is not None
        assert run.status == "failed"
        model_run = session.scalar(select(ModelRun))
        assert model_run is not None
        assert model_run.status == "failed"


def test_extraction_rejects_oversized_batch(client, monkeypatch) -> None:
    token = token_for(client, "graph-batch@example.com")
    source_id, item_ids = import_memory(client, token)
    _configure(client)
    _consent(client, token, source_id)
    client.app.state.settings.graph_extraction_max_items = 1
    monkeypatch.setattr(graph_extraction, "_call_graph_model", _synthetic_graph)

    response = client.post(
        "/api/v1/extractions",
        headers=_headers(token),
        json={"item_ids": item_ids[:2]},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "extraction_batch_too_large"
