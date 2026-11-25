from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from test_reviews_account import import_memory, token_for

from personal_ai_life_os.models import (
    EntityAlias,
    EntityMergeLog,
    ExtractionRun,
    GraphEntity,
    GraphEvidence,
    GraphRelation,
    GraphReviewItem,
    OntologyType,
)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _user_id(client, token: str) -> str:
    return client.get("/api/v1/auth/me", headers=_headers(token)).json()["id"]


def test_graph_records_link_entities_relations_and_evidence(client) -> None:
    token = token_for(client, "graph-model@example.com")
    source_id, item_ids = import_memory(client, token)
    owner_id = _user_id(client, token)

    with client.app.state.session_factory() as session:
        project = GraphEntity(
            owner_id=owner_id,
            entity_type="project",
            name="Personal AI Life OS",
            normalized_name="personal ai life os",
            summary="Local-first personal memory project.",
            confidence=0.95,
            created_by="model",
        )
        goal = GraphEntity(
            owner_id=owner_id,
            entity_type="goal",
            name="Evidence graph Q&A",
            normalized_name="evidence graph q&a",
            confidence=0.91,
            created_by="model",
        )
        session.add_all([project, goal])
        session.flush()
        relation = GraphRelation(
            owner_id=owner_id,
            from_entity_id=project.id,
            to_entity_id=goal.id,
            relation_type="has_goal",
            confidence=0.88,
            created_by="model",
        )
        session.add(relation)
        session.flush()
        evidence = GraphEvidence(
            owner_id=owner_id,
            relation_id=relation.id,
            source_id=source_id,
            source_item_id=item_ids[0],
            quote="Agreed to review the import workflow with a small synthetic dataset.",
            locator={"line_start": 5, "line_end": 7},
            confidence=0.9,
        )
        alias = EntityAlias(
            owner_id=owner_id,
            entity_id=project.id,
            alias="Life OS",
            normalized_alias="life os",
        )
        merge_log = EntityMergeLog(
            owner_id=owner_id,
            source_entity_id=goal.id,
            target_entity_id=project.id,
            status="active",
            snapshot={"source_name": goal.name},
        )
        ontology = OntologyType(
            owner_id=owner_id,
            kind="relation",
            name="supports_growth",
            description="A project supports a growth area.",
            status="approved",
            source="model",
        )
        run = ExtractionRun(
            owner_id=owner_id,
            status="completed",
            provider="synthetic",
            model="synthetic-model",
            prompt_version="graph-extraction-v1",
            requested_hash="synthetic-hash",
            requested_item_ids=item_ids[:1],
            item_count=1,
            entity_count=2,
            relation_count=1,
            review_count=0,
            input_tokens=100,
            output_tokens=50,
            cost_usd=Decimal("0.000100"),
            latency_ms=12,
        )
        session.add_all([evidence, alias, merge_log, ontology, run])
        session.flush()
        review = GraphReviewItem(
            owner_id=owner_id,
            extraction_run_id=run.id,
            kind="relation",
            payload={"relation_type": "supports_growth"},
            confidence=0.42,
            status="pending",
            reason="low_confidence",
        )
        session.add(review)
        session.commit()
        project_id = project.id

    with client.app.state.session_factory() as session:
        stored_project = session.get(GraphEntity, project_id)
        assert stored_project is not None
        assert stored_project.owner_id == owner_id
        assert session.scalar(select(GraphEntity).where(GraphEntity.owner_id == owner_id))
        relations = list(session.scalars(select(GraphRelation)))
        assert relations[0].relation_type == "has_goal"
        evidence = session.scalar(select(GraphEvidence))
        assert evidence is not None
        assert evidence.availability == "active"
        assert evidence.source_item_id == item_ids[0]
        assert session.scalar(select(EntityAlias)).normalized_alias == "life os"
        assert session.scalar(select(EntityMergeLog)).status == "active"
        assert session.scalar(select(OntologyType)).status == "approved"
        assert session.scalar(select(ExtractionRun)).review_count == 0
        assert session.scalar(select(GraphReviewItem)).status == "pending"


def test_graph_evidence_requires_an_entity_or_relation(client) -> None:
    token = token_for(client, "graph-evidence-check@example.com")
    source_id, item_ids = import_memory(client, token)
    owner_id = _user_id(client, token)

    with client.app.state.session_factory() as session:
        session.add(
            GraphEvidence(
                owner_id=owner_id,
                source_id=source_id,
                source_item_id=item_ids[0],
                quote="No target.",
                locator={},
                confidence=0.5,
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:
            raise AssertionError("Graph evidence without an entity or relation must fail.")


def test_graph_records_are_scoped_by_owner(client) -> None:
    first = token_for(client, "graph-owner-a@example.com")
    second = token_for(client, "graph-owner-b@example.com")
    first_id = _user_id(client, first)
    second_id = _user_id(client, second)
    with client.app.state.session_factory() as session:
        session.add(
            GraphEntity(
                owner_id=first_id,
                entity_type="topic",
                name="Private topic",
                normalized_name="private topic",
            )
        )
        session.commit()

    with client.app.state.session_factory() as session:
        assert session.scalar(
            select(GraphEntity).where(GraphEntity.owner_id == first_id)
        ) is not None
        assert (
            session.scalar(select(GraphEntity).where(GraphEntity.owner_id == second_id))
            is None
        )
