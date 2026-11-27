import json
from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZipFile

from sqlalchemy import select
from test_reviews_account import import_memory, token_for

from personal_ai_life_os.models import (
    GraphEntity,
    GraphEvidence,
    GraphRelation,
    Review,
    SourceConnection,
)
from personal_ai_life_os.services import graph_qa


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _seed_graph(client, token: str) -> dict:
    source_id, item_ids = import_memory(client, token)
    owner_id = client.get("/api/v1/auth/me", headers=_headers(token)).json()["id"]
    with client.app.state.session_factory() as session:
        entities: dict[str, str] = {}

        def add_entity(
            key: str,
            entity_type: str,
            name: str,
            summary: str,
            confidence: float,
            item_id: str,
            quote: str,
        ) -> None:
            entity = GraphEntity(
                owner_id=owner_id,
                entity_type=entity_type,
                name=name,
                normalized_name=name.casefold(),
                summary=summary,
                confidence=confidence,
                status="active",
                created_by="model",
            )
            session.add(entity)
            session.flush()
            entities[key] = entity.id
            session.add(
                GraphEvidence(
                    owner_id=owner_id,
                    entity_id=entity.id,
                    source_id=source_id,
                    source_item_id=item_id,
                    quote=quote,
                    locator={"section": key},
                    confidence=confidence,
                    availability="active",
                )
            )

        add_entity(
            "project",
            "project",
            "Life OS",
            "Local personal memory project.",
            0.95,
            item_ids[0],
            "Chose Postgres for structured records",
        )
        add_entity(
            "goal",
            "goal",
            "Evidence graph Q&A",
            "Answer questions from cited evidence.",
            0.9,
            item_ids[0],
            "Agreed to review the import workflow",
        )
        add_entity(
            "decision",
            "decision",
            "Use Postgres",
            "Chose Postgres for structured records.",
            0.92,
            item_ids[0],
            "Chose Postgres for structured records",
        )
        add_entity(
            "commitment",
            "commitment",
            "Review import workflow",
            "Review the workflow with a small synthetic dataset.",
            0.88,
            item_ids[0],
            "Agreed to review the import workflow with a small synthetic dataset",
        )
        add_entity(
            "skill",
            "skill",
            "Python",
            "Backend implementation skill.",
            0.8,
            item_ids[1],
            "The import preview should show filenames",
        )
        add_entity(
            "topic",
            "topic",
            "AI memory",
            "Long-term personal memory.",
            0.82,
            item_ids[1],
            "import preview",
        )
        add_entity(
            "person",
            "person",
            "Alex",
            "Collaborator on the import review.",
            0.86,
            item_ids[0],
            "Agreed to review the import workflow",
        )

        relations = [
            ("project", "goal", "has_goal"),
            ("project", "decision", "related_to"),
            ("project", "commitment", "related_to"),
            ("project", "skill", "develops_skill"),
            ("project", "topic", "related_to"),
        ]
        for from_key, to_key, relation_type in relations:
            relation = GraphRelation(
                owner_id=owner_id,
                from_entity_id=entities[from_key],
                to_entity_id=entities[to_key],
                relation_type=relation_type,
                confidence=0.85,
                status="active",
                created_by="model",
            )
            session.add(relation)
            session.flush()
            session.add(
                GraphEvidence(
                    owner_id=owner_id,
                    relation_id=relation.id,
                    source_id=source_id,
                    source_item_id=item_ids[0],
                    quote="Agreed to review the import workflow",
                    locator={"section": relation_type},
                    confidence=0.85,
                    availability="active",
                )
            )

        existing_review = session.scalar(
            select(Review.id).where(
                Review.owner_id == owner_id,
                Review.period_start == datetime(2026, 11, 16, tzinfo=UTC),
            )
        )
        if existing_review is None:
            session.add(
                Review(
                    owner_id=owner_id,
                    period_start=datetime(2026, 11, 16, tzinfo=UTC),
                    period_end=datetime(2026, 11, 21, tzinfo=UTC),
                    status="draft",
                    draft_json={},
                    final_text="Postgres review and memory notes.",
                )
            )
        session.commit()
    return {"source_id": source_id, "item_ids": item_ids, "entities": entities}


def _ask(client, token: str, thread_id: str, question: str, scope: dict | None = None):
    body: dict = {"question": question}
    if scope is not None:
        body["scope"] = scope
    return client.post(
        "/api/v1/qa/threads/" + thread_id + "/messages",
        headers=_headers(token),
        json=body,
    )


def _thread(client, token: str, scope: dict | None = None) -> str:
    response = client.post(
        "/api/v1/qa/threads",
        headers=_headers(token),
        json={"title": "Synthetic questions", "scope": scope or {}},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_four_question_types_return_facts_and_citations(client, monkeypatch) -> None:
    monkeypatch.setattr(graph_qa, "utcnow", lambda: datetime(2026, 11, 22, tzinfo=UTC))
    token = token_for(client, "qa-four@example.com")
    seeded = _seed_graph(client, token)
    thread_id = _thread(client, token)

    cases = {
        "decision": "What did I decide about Postgres?",
        "project": "What is the status of the Life OS project?",
        "growth": "What skills am I learning?",
        "timeline": "What happened last week?",
    }
    for intent, question in cases.items():
        response = _ask(client, token, thread_id, question)
        assert response.status_code == 200, response.text
        thread = response.json()
        answer = thread["messages"][-1]["answer"]
        assert answer["status"] == "answered", (intent, answer)
        assert answer["facts"], intent
        assert answer["citations"], intent
        assert all(fact["basis"] in ("fact", "inference", "uncertain") for fact in answer["facts"])
        assert 0 <= answer["confidence"] <= 1
        assert all(citation["source_item_id"] in seeded["item_ids"] for citation in answer["citations"])
        assert answer["version"] == "graph-qa-v1"

    last_answer = client.get(
        "/api/v1/qa/threads/" + thread_id, headers=_headers(token)
    ).json()["messages"][-1]["answer"]
    assert last_answer["timeline_matches"]


def test_scope_memory_history_export_and_delete(client) -> None:
    token = token_for(client, "qa-history@example.com")
    seeded = _seed_graph(client, token)
    thread_id = _thread(client, token, {"source_ids": [seeded["source_id"]], "start": "2026-11-01"})

    threads = client.get("/api/v1/qa/threads", headers=_headers(token)).json()
    assert threads["total"] == 1
    assert threads["items"][0]["scope"]["source_ids"] == [seeded["source_id"]]

    scope = client.get("/api/v1/qa/scope", headers=_headers(token)).json()
    assert scope["thread_id"] == thread_id
    assert scope["scope"]["start"].startswith("2026-11-01")

    answered = _ask(client, token, thread_id, "What did I decide about Postgres?")
    assert answered.status_code == 200, answered.text
    answer = answered.json()["messages"][-1]["answer"]
    assert answer["scope"]["source_ids"] == [seeded["source_id"]]

    cleared = _ask(
        client,
        token,
        thread_id,
        "What is the Life OS project status?",
        {"source_ids": [], "entity_ids": [], "start": None, "end": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["messages"][-1]["answer"]["scope"]["source_ids"] == []

    exported = client.get(
        "/api/v1/qa/threads/" + thread_id + "/export?format=json",
        headers=_headers(token),
    )
    assert exported.status_code == 200
    document = json.loads(exported.text)
    assert len(document["messages"]) == 4
    markdown = client.get(
        "/api/v1/qa/threads/" + thread_id + "/export?format=markdown",
        headers=_headers(token),
    )
    assert markdown.status_code == 200
    assert "## 问：" in markdown.text
    assert "#### 引用" in markdown.text

    archive = client.get("/api/v1/account/archive", headers=_headers(token))
    assert archive.status_code == 200
    with ZipFile(BytesIO(archive.content)) as bundle:
        names = set(bundle.namelist())
        assert {
            "graph-entities.json",
            "graph-relations.json",
            "graph-evidence.json",
            "qa-threads.json",
            "agent-actions.json",
            "plugin-manifests.json",
        } <= names
        evidence = json.loads(bundle.read("graph-evidence.json"))
        assert evidence and evidence[0]["quote"]
        archived_threads = json.loads(bundle.read("qa-threads.json"))
        assert archived_threads and archived_threads[0]["messages"]

    deleted = client.delete("/api/v1/qa/threads/" + thread_id, headers=_headers(token))
    assert deleted.status_code == 204
    assert client.get("/api/v1/qa/threads/" + thread_id, headers=_headers(token)).status_code == 404
    assert client.get("/api/v1/qa/scope", headers=_headers(token)).json()["thread_id"] is None


def test_revoked_and_deleted_sources_are_excluded(client) -> None:
    token = token_for(client, "qa-sources@example.com")
    first = _seed_graph(client, token)
    second = _seed_graph(client, token)
    thread_id = _thread(client, token)

    response = _ask(client, token, thread_id, "What did I decide about Postgres?")
    assert response.status_code == 200, response.text
    assert response.json()["messages"][-1]["answer"]["status"] == "answered"

    revoked = client.post(
        "/api/v1/sources/" + first["source_id"] + "/revoke", headers=_headers(token)
    )
    assert revoked.status_code == 200, revoked.text
    scoped = _ask(
        client,
        token,
        thread_id,
        "What did I decide about Postgres?",
        {"source_ids": [first["source_id"]]},
    )
    revoked_answer = scoped.json()["messages"][-1]["answer"]
    assert revoked_answer["status"] == "insufficient_evidence"
    assert revoked_answer["citations"] == []
    assert "没有找到可靠证据" in revoked_answer["summary"]

    unscoped = _ask(
        client,
        token,
        thread_id,
        "What did I decide about Postgres?",
        {"source_ids": [], "entity_ids": []},
    )
    assert unscoped.json()["messages"][-1]["answer"]["status"] == "answered"

    deleted = client.delete(
        "/api/v1/sources/" + second["source_id"], headers=_headers(token)
    )
    assert deleted.status_code == 204
    after_delete = _ask(
        client,
        token,
        thread_id,
        "What did I decide about Postgres?",
        {"source_ids": [second["source_id"]]},
    )
    assert after_delete.json()["messages"][-1]["answer"]["status"] == "insufficient_evidence"
    with client.app.state.session_factory() as session:
        remaining_sources = set(
            session.scalars(
                select(SourceConnection.id).where(SourceConnection.owner_id == seeded_owner_id(client, token))
            )
        )
    assert second["source_id"] not in remaining_sources


def seeded_owner_id(client, token: str) -> str:
    return client.get("/api/v1/auth/me", headers=_headers(token)).json()["id"]


def test_entity_scope_limits_answers(client) -> None:
    token = token_for(client, "qa-entity-scope@example.com")
    seeded = _seed_graph(client, token)
    thread_id = _thread(
        client,
        token,
        {"entity_ids": [seeded["entities"]["project"]]},
    )
    response = _ask(client, token, thread_id, "What is the status of the Life OS project?")
    assert response.status_code == 200, response.text
    answer = response.json()["messages"][-1]["answer"]
    assert answer["status"] == "answered"
    entity_ids = {fact["entity_id"] for fact in answer["facts"] if fact["entity_id"]}
    assert seeded["entities"]["skill"] not in entity_ids
    assert seeded["entities"]["project"] in entity_ids


def test_no_evidence_refuses_to_fabricate_and_history_is_owner_scoped(client) -> None:
    token = token_for(client, "qa-empty@example.com")
    thread_id = _thread(client, token)
    response = _ask(client, token, thread_id, "What did I decide about Postgres?")
    assert response.status_code == 200, response.text
    answer = response.json()["messages"][-1]["answer"]
    assert answer["status"] == "insufficient_evidence"
    assert answer["facts"] == []
    assert answer["citations"] == []
    assert "没有找到可靠证据" in answer["summary"]
    assert answer["missing_info"]

    blank = _ask(client, token, thread_id, "   ")
    assert blank.status_code == 422
    assert blank.json()["error"]["code"] == "question_required"

    stranger = token_for(client, "qa-stranger@example.com")
    assert client.get(
        "/api/v1/qa/threads/" + thread_id, headers=_headers(stranger)
    ).status_code == 404
    assert client.delete(
        "/api/v1/qa/threads/" + thread_id, headers=_headers(stranger)
    ).status_code == 404
