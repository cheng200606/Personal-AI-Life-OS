from decimal import Decimal

from sqlalchemy import func, select
from test_reviews_account import (
    configure_synthetic_model_pricing,
    import_memory,
    token_for,
)

from personal_ai_life_os.models import EntityAlias, GraphEvidence
from personal_ai_life_os.services import graph_extraction


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _configure(client) -> None:
    config = client.app.state.settings
    config.model_provider = "openai"
    config.openai_api_key = "synthetic-api-key"
    configure_synthetic_model_pricing(config)
    config.model_monthly_budget_usd = Decimal("5.00")


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


def _review_graph(items, _config=None, _provider=None, _custom_types=None):
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
                {
                    "key": "p2",
                    "type": "project",
                    "name": "Maybe project",
                    "confidence": 0.55,
                    "evidence": [{"item_id": items[0].id, "quote": "review notes"}],
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


def _merge_graph(items, _config=None, _provider=None, _custom_types=None):
    return (
        {
            "entities": [
                {
                    "key": "p1",
                    "type": "project",
                    "name": "Life OS",
                    "confidence": 0.95,
                    "evidence": [{"item_id": items[0].id, "quote": "Postgres"}],
                },
                {
                    "key": "p2",
                    "type": "project",
                    "name": "Life OS Duplicate",
                    "confidence": 0.9,
                    "evidence": [{"item_id": items[0].id, "quote": "Markdown"}],
                },
            ],
            "relations": [
                {
                    "from_key": "p1",
                    "to_key": "p2",
                    "type": "related_to",
                    "confidence": 0.9,
                    "evidence": [{"item_id": items[0].id, "quote": "Postgres"}],
                }
            ],
        },
        12,
        100,
        50,
    )


def _prepare(client, monkeypatch, email: str, graph=_review_graph):
    token = token_for(client, email)
    source_id, item_ids = import_memory(client, token)
    _configure(client)
    _consent(client, token, source_id)
    monkeypatch.setattr(graph_extraction, "_call_graph_model", graph)
    response = client.post(
        "/api/v1/extractions", headers=_headers(token), json={"item_ids": item_ids[:2]}
    )
    assert response.status_code == 201, response.text
    return token, item_ids, response.json()


def _pending(client, token: str) -> list[dict]:
    response = client.get("/api/v1/graph/review?status=pending", headers=_headers(token))
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_low_confidence_review_supports_edit_approve_and_reject(client, monkeypatch) -> None:
    token, _items, run = _prepare(client, monkeypatch, "review-queue@example.com")
    assert run["review_count"] == 2
    pending = _pending(client, token)
    assert len(pending) == 2
    assert {item["kind"] for item in pending} == {"entity"}

    target = next(item for item in pending if item["payload"]["name"] == "Evidence graph Q&A")
    edited = client.patch(
        "/api/v1/graph/review/" + target["id"],
        headers=_headers(token),
        json={"name": "Evidence graph QA reviewed", "confidence": 0.8},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["payload"]["name"] == "Evidence graph QA reviewed"

    approved = client.post(
        "/api/v1/graph/review/" + target["id"] + "/decision",
        headers=_headers(token),
        json={"action": "approve"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    entities = client.get("/api/v1/graph/entities", headers=_headers(token)).json()
    reviewed = next(
        entity for entity in entities["items"] if entity["id"] == target["payload"]["entity_id"]
    )
    assert reviewed["name"] == "Evidence graph QA reviewed"
    assert reviewed["status"] == "active"

    other = next(item for item in pending if item["payload"]["name"] == "Maybe project")
    rejected = client.post(
        "/api/v1/graph/review/" + other["id"] + "/decision",
        headers=_headers(token),
        json={"action": "reject"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    entities = client.get("/api/v1/graph/entities", headers=_headers(token)).json()
    assert all(item["id"] != other["payload"]["entity_id"] for item in entities["items"])

    repeat = client.post(
        "/api/v1/graph/review/" + other["id"] + "/decision",
        headers=_headers(token),
        json={"action": "approve"},
    )
    assert repeat.status_code == 409
    assert repeat.json()["error"]["code"] == "review_item_resolved"

    stranger = token_for(client, "review-stranger@example.com")
    assert _pending(client, stranger) == []
    hidden = client.post(
        "/api/v1/graph/review/" + other["id"] + "/decision",
        headers=_headers(stranger),
        json={"action": "approve"},
    )
    assert hidden.status_code == 404


def test_review_bulk_resolution_and_ontology_governance(client, monkeypatch) -> None:
    token, _items, run = _prepare(client, monkeypatch, "review-bulk@example.com")
    pending = _pending(client, token)
    bulk = client.post(
        "/api/v1/graph/review/bulk",
        headers=_headers(token),
        json={"item_ids": [item["id"] for item in pending], "action": "approve"},
    )
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()["total"] == 2
    assert all(item["status"] == "approved" for item in bulk.json()["items"])
    assert _pending(client, token) == []
    assert run["status"] == "completed"

    created = client.post(
        "/api/v1/ontology/types",
        headers=_headers(token),
        json={"kind": "entity", "name": "habit", "description": "Recurring personal habit."},
    )
    assert created.status_code == 201, created.text
    habit = created.json()
    assert habit["status"] == "proposed"
    assert habit["source"] == "user"
    assert habit["created_by"] == "user"
    assert habit["version"] == 1

    approved = client.post(
        "/api/v1/ontology/types/" + habit["id"] + "/decision",
        headers=_headers(token),
        json={"status": "approved"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["version"] == 2

    approved_list = client.get(
        "/api/v1/ontology/types?status=approved", headers=_headers(token)
    ).json()
    assert any(entry["name"] == "habit" for entry in approved_list["items"])

    duplicate = client.post(
        "/api/v1/ontology/types",
        headers=_headers(token),
        json={"kind": "entity", "name": "habit"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "ontology_type_exists"

    invalid = client.post(
        "/api/v1/ontology/types",
        headers=_headers(token),
        json={"kind": "entity", "name": "Bad Name"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_ontology_name"


def test_model_proposed_type_is_rejected_without_repeating(client, monkeypatch) -> None:
    token = token_for(client, "ontology-model@example.com")
    source_id, item_ids = import_memory(client, token)
    _configure(client)
    _consent(client, token, source_id)

    def fake(items, config=None, provider=None, custom_types=None):
        return (
            {
                "entities": [
                    {
                        "key": "m1",
                        "type": "metric",
                        "name": "Weekly focus minutes",
                        "confidence": 0.95,
                        "evidence": [{"item_id": items[0].id, "quote": "Postgres"}],
                    }
                ],
                "relations": [],
            },
            10,
            80,
            20,
        )

    monkeypatch.setattr(graph_extraction, "_call_graph_model", fake)
    first = client.post(
        "/api/v1/extractions", headers=_headers(token), json={"item_ids": item_ids[:1]}
    )
    assert first.status_code == 201, first.text
    assert first.json()["review_count"] == 1
    proposed = client.get(
        "/api/v1/ontology/types?status=proposed", headers=_headers(token)
    ).json()
    metric = next(entry for entry in proposed["items"] if entry["name"] == "metric")
    assert metric["source"] == "model"

    rejected = client.post(
        "/api/v1/ontology/types/" + metric["id"] + "/decision",
        headers=_headers(token),
        json={"status": "rejected"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"

    second = client.post(
        "/api/v1/extractions", headers=_headers(token), json={"item_ids": item_ids[1:2]}
    )
    assert second.status_code == 201, second.text
    types = client.get("/api/v1/ontology/types", headers=_headers(token)).json()
    assert len([entry for entry in types["items"] if entry["name"] == "metric"]) == 1
    assert all(
        entry["status"] != "proposed"
        for entry in types["items"]
        if entry["name"] == "metric"
    )


def test_merge_undo_restores_entities_evidence_and_relations(client, monkeypatch) -> None:
    token, _items, _run = _prepare(
        client, monkeypatch, "merge-undo@example.com", graph=_merge_graph
    )
    entities = client.get("/api/v1/graph/entities", headers=_headers(token)).json()
    assert entities["total"] == 2
    source = next(item for item in entities["items"] if item["name"] == "Life OS")
    target = next(item for item in entities["items"] if item["name"] == "Life OS Duplicate")
    relations = client.get("/api/v1/graph/relations", headers=_headers(token)).json()
    assert relations["total"] == 1

    merged = client.post(
        "/api/v1/graph/entities/" + source["id"] + "/merge",
        headers=_headers(token),
        json={"target_entity_id": target["id"]},
    )
    assert merged.status_code == 201, merged.text
    log = merged.json()
    assert log["status"] == "active"
    assert log["evidence_count"] == 1
    assert log["relation_count"] == 1

    remaining = client.get("/api/v1/graph/entities", headers=_headers(token)).json()
    assert remaining["total"] == 1
    assert remaining["items"][0]["id"] == target["id"]
    assert {citation["quote"] for citation in remaining["items"][0]["evidence"]} >= {
        "Postgres",
        "Markdown",
    }
    with client.app.state.session_factory() as session:
        alias = session.scalar(
            select(EntityAlias).where(
                EntityAlias.entity_id == target["id"],
                EntityAlias.normalized_alias == "life os",
            )
        )
        assert alias is not None

    undone = client.post(
        "/api/v1/graph/merges/" + log["id"] + "/undo",
        headers=_headers(token),
    )
    assert undone.status_code == 200, undone.text
    assert undone.json()["status"] == "undone"

    restored = client.get("/api/v1/graph/entities", headers=_headers(token)).json()
    assert {item["name"] for item in restored["items"]} == {"Life OS", "Life OS Duplicate"}
    restored_relations = client.get("/api/v1/graph/relations", headers=_headers(token)).json()
    assert restored_relations["total"] == 1
    relation = restored_relations["items"][0]
    assert relation["status"] == "active"
    assert relation["from_entity_id"] == source["id"]
    assert relation["to_entity_id"] == target["id"]
    with client.app.state.session_factory() as session:
        alias = session.scalar(
            select(EntityAlias).where(
                EntityAlias.entity_id == target["id"],
                EntityAlias.normalized_alias == "life os",
            )
        )
        assert alias is None
        source_evidence = session.scalar(
            select(func.count())
            .select_from(GraphEvidence)
            .where(GraphEvidence.entity_id == source["id"])
        )
        target_evidence = session.scalar(
            select(func.count())
            .select_from(GraphEvidence)
            .where(GraphEvidence.entity_id == target["id"])
        )
        assert source_evidence == 1
        assert target_evidence == 1

    again = client.post(
        "/api/v1/graph/merges/" + log["id"] + "/undo",
        headers=_headers(token),
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "merge_already_undone"

    stranger = token_for(client, "merge-stranger@example.com")
    hidden = client.post(
        "/api/v1/graph/merges/" + log["id"] + "/undo",
        headers=_headers(stranger),
    )
    assert hidden.status_code == 404


def test_merge_rejects_same_entity_and_foreign_owner(client, monkeypatch) -> None:
    token, _items, _run = _prepare(
        client, monkeypatch, "merge-guard@example.com", graph=_merge_graph
    )
    entities = client.get("/api/v1/graph/entities", headers=_headers(token)).json()
    source = next(item for item in entities["items"] if item["name"] == "Life OS")
    target = next(item for item in entities["items"] if item["name"] == "Life OS Duplicate")

    same = client.post(
        "/api/v1/graph/entities/" + source["id"] + "/merge",
        headers=_headers(token),
        json={"target_entity_id": source["id"]},
    )
    assert same.status_code == 422
    assert same.json()["error"]["code"] == "merge_requires_two_entities"

    stranger = token_for(client, "merge-foreign@example.com")
    hidden = client.post(
        "/api/v1/graph/entities/" + source["id"] + "/merge",
        headers=_headers(stranger),
        json={"target_entity_id": target["id"]},
    )
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "graph_entity_not_found"


def test_approved_custom_type_is_sent_to_extraction_prompt(client, monkeypatch) -> None:
    token, _items, _run = _prepare(client, monkeypatch, "ontology-prompt@example.com")
    created = client.post(
        "/api/v1/ontology/types",
        headers=_headers(token),
        json={"kind": "entity", "name": "habit"},
    )
    assert created.status_code == 201, created.text
    approved = client.post(
        "/api/v1/ontology/types/" + created.json()["id"] + "/decision",
        headers=_headers(token),
        json={"status": "approved"},
    )
    assert approved.status_code == 200, approved.text

    captured: dict = {}

    def fake(items, config=None, provider=None, custom_types=None):
        captured["types"] = custom_types
        return ({"entities": [], "relations": []}, 3, 20, 10)

    monkeypatch.setattr(graph_extraction, "_call_graph_model", fake)
    response = client.post(
        "/api/v1/extractions", headers=_headers(token), json={"item_ids": _items[1:2]}
    )
    assert response.status_code == 201, response.text
    assert captured["types"] == {"entity": ["habit"], "relation": []}


def test_alias_match_reuses_merged_target(client, monkeypatch) -> None:
    token, item_ids, _run = _prepare(
        client, monkeypatch, "merge-alias@example.com", graph=_merge_graph
    )
    entities = client.get("/api/v1/graph/entities", headers=_headers(token)).json()
    source = next(item for item in entities["items"] if item["name"] == "Life OS")
    target = next(item for item in entities["items"] if item["name"] == "Life OS Duplicate")
    merged = client.post(
        "/api/v1/graph/entities/" + source["id"] + "/merge",
        headers=_headers(token),
        json={"target_entity_id": target["id"]},
    )
    assert merged.status_code == 201, merged.text

    def fake(items, config=None, provider=None, custom_types=None):
        return (
            {
                "entities": [
                    {
                        "key": "p",
                        "type": "project",
                        "name": "Life OS",
                        "confidence": 0.95,
                        "evidence": [{"item_id": items[0].id, "quote": "Markdown"}],
                    }
                ],
                "relations": [],
            },
            9,
            60,
            30,
        )

    monkeypatch.setattr(graph_extraction, "_call_graph_model", fake)
    response = client.post(
        "/api/v1/extractions", headers=_headers(token), json={"item_ids": item_ids[1:2]}
    )
    assert response.status_code == 201, response.text
    assert response.json()["entity_count"] == 0
    after = client.get("/api/v1/graph/entities", headers=_headers(token)).json()
    assert after["total"] == 1
    assert after["items"][0]["id"] == target["id"]
    assert after["items"][0]["name"] == "Life OS Duplicate"
