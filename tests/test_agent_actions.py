from datetime import UTC, datetime, timedelta
from decimal import Decimal

from test_reviews_account import (
    configure_synthetic_model_pricing,
    import_memory,
    token_for,
)

from personal_ai_life_os.models import (
    AgentAction,
    GraphEntity,
    GraphRelation,
    Reminder,
    Review,
    User,
)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _owner_id(client, token: str) -> str:
    return client.get("/api/v1/auth/me", headers=_headers(token)).json()["id"]


def _goal(client, token: str, source_id: str, item_id: str) -> str:
    owner_id = _owner_id(client, token)
    with client.app.state.session_factory() as session:
        goal = GraphEntity(
            owner_id=owner_id,
            entity_type="goal",
            name="证据图谱问答目标",
            normalized_name="证据图谱问答目标",
            summary="完成图谱问答",
            confidence=0.9,
            status="active",
            created_by="model",
        )
        session.add(goal)
        session.commit()
        return goal.id


def _action(client, token: str, kind: str, payload: dict, approved: bool = False):
    return client.post(
        "/api/v1/agent/actions",
        headers=_headers(token),
        json={"kind": kind, "payload": payload, "approved": approved},
    )


def test_automatic_writes_create_records_and_undo_restores(client) -> None:
    token = token_for(client, "agent-writes@example.com")
    source_id, item_ids = import_memory(client, token)

    created = _action(
        client,
        token,
        "create_task",
        {"name": "整理导入流程", "summary": "把导入步骤写清楚", "source_item_ids": item_ids[:1]},
    )
    assert created.status_code == 201, created.text
    action = created.json()
    assert action["status"] == "active"
    assert action["approval"] == "automatic"
    assert action["undo_available"] is True
    assert action["target_type"] == "graph_entity"
    assert datetime.fromisoformat(action["expires_at"]) > datetime.now(UTC)
    with client.app.state.session_factory() as session:
        entity = session.get(GraphEntity, action["target_id"])
        assert entity is not None
        assert entity.entity_type == "task"
        assert entity.created_by == "agent"
        assert entity.status == "active"

    undone = client.post(
        "/api/v1/agent/actions/" + action["id"] + "/undo", headers=_headers(token)
    )
    assert undone.status_code == 200, undone.text
    assert undone.json()["status"] == "undone"
    with client.app.state.session_factory() as session:
        entity = session.get(GraphEntity, action["target_id"])
        assert entity is not None
        assert entity.status == "invalid"
    entities = client.get("/api/v1/graph/entities", headers=_headers(token)).json()
    assert all(item["id"] != action["target_id"] for item in entities["items"])

    reminder = _action(
        client, token, "create_reminder", {"title": "跟进导入评审", "source_item_ids": item_ids[:1]}
    )
    assert reminder.status_code == 201, reminder.text
    reminder_id = reminder.json()["target_id"]
    assert client.post(
        "/api/v1/agent/actions/" + reminder.json()["id"] + "/undo",
        headers=_headers(token),
    ).status_code == 200
    with client.app.state.session_factory() as session:
        row = session.get(Reminder, reminder_id)
        assert row is not None
        assert row.status == "cancelled"

    goal_id = _goal(client, token, source_id, item_ids[0])
    progress = _action(
        client,
        token,
        "update_goal_progress",
        {
            "goal_id": goal_id,
            "summary": "完成第一版检索",
            "source_item_ids": item_ids[1:2],
        },
    )
    assert progress.status_code == 201, progress.text
    progress_action = progress.json()
    assert progress_action["after"]["relation_id"]
    with client.app.state.session_factory() as session:
        relation = session.get(GraphRelation, progress_action["after"]["relation_id"])
        assert relation is not None
        assert relation.relation_type == "supports_goal"
        assert relation.status == "active"
    assert client.post(
        "/api/v1/agent/actions/" + progress_action["id"] + "/undo",
        headers=_headers(token),
    ).status_code == 200
    with client.app.state.session_factory() as session:
        relation = session.get(GraphRelation, progress_action["after"]["relation_id"])
        assert relation is not None
        assert relation.status == "invalid"


def test_review_draft_budget_rejection_and_undo(client) -> None:
    token = token_for(client, "agent-review@example.com")
    _source_id, _item_ids = import_memory(client, token)
    draft = _action(
        client,
        token,
        "create_review_draft",
        {"period_start": "2026-11-16", "period_end": "2026-11-21"},
    )
    assert draft.status_code == 201, draft.text
    action = draft.json()
    assert action["target_type"] == "review"
    with client.app.state.session_factory() as session:
        review = session.get(Review, action["target_id"])
        assert review is not None
        assert review.status == "draft"
        assert review.final_text
    assert client.post(
        "/api/v1/agent/actions/" + action["id"] + "/undo", headers=_headers(token)
    ).status_code == 200
    with client.app.state.session_factory() as session:
        review = session.get(Review, action["target_id"])
        assert review is not None
        assert review.status == "invalidated"

    config = client.app.state.settings
    config.model_provider = "openai"
    config.openai_api_key = "synthetic-api-key"
    configure_synthetic_model_pricing(config)
    config.model_monthly_budget_usd = Decimal("0.0000001")
    config.processing_mode = "worker"
    owner_id = _owner_id(client, token)
    with client.app.state.session_factory() as session:
        user = session.get(User, owner_id)
        assert user is not None
        user.ai_consent_at = datetime.now(UTC)
        user.ai_consent_provider = config.model_provider
        user.ai_consent_disclosure_version = config.model_disclosure_version
        session.commit()

    blocked = _action(
        client,
        token,
        "create_review_draft",
        {
            "period_start": "2026-11-17",
            "period_end": "2026-11-21",
            "use_external_model": True,
        },
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "agent_budget_exhausted"
    rejected = client.get(
        "/api/v1/agent/actions?status=rejected", headers=_headers(token)
    ).json()
    assert any(
        item["error_code"] == "agent_budget_exhausted" for item in rejected["items"]
    )


def test_red_lines_are_rejected_and_audited(client) -> None:
    token = token_for(client, "agent-redlines@example.com")
    tools = client.get("/api/v1/agent/tools", headers=_headers(token)).json()
    red_lines = {tool["name"] for tool in tools["items"] if tool["red_line"]}
    assert {"external.send", "file.write", "payment.charge", "data.delete", "goal.change"} <= red_lines
    assert all(
        tool["requires_approval"]
        for tool in tools["items"]
        if tool["name"] in red_lines
    )

    for kind in ("external.send", "file.write", "payment.charge", "data.delete", "goal.change"):
        response = _action(client, token, kind, {})
        assert response.status_code == 403, (kind, response.text)
        assert response.json()["error"]["code"] == "agent_requires_human_approval"

    rejected = client.get(
        "/api/v1/agent/actions?status=rejected", headers=_headers(token)
    ).json()
    assert rejected["total"] >= 5
    assert {item["kind"] for item in rejected["items"]} >= {
        "external.send",
        "file.write",
        "payment.charge",
        "data.delete",
        "goal.change",
    }
    assert all(item["approval"] == "required" for item in rejected["items"])

    unknown = _action(client, token, "send_everything", {})
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "agent_action_unknown"


def test_undo_window_expiry_and_owner_scope(client) -> None:
    token = token_for(client, "agent-expiry@example.com")
    _source_id, item_ids = import_memory(client, token)
    created = _action(
        client, token, "create_reminder", {"title": "过期撤销测试", "source_item_ids": item_ids[:1]}
    )
    assert created.status_code == 201, created.text
    action_id = created.json()["id"]
    with client.app.state.session_factory() as session:
        action = session.get(AgentAction, action_id)
        assert action is not None
        action.expires_at = datetime.now(UTC) - timedelta(hours=1)
        session.commit()

    expired = client.post(
        "/api/v1/agent/actions/" + action_id + "/undo", headers=_headers(token)
    )
    assert expired.status_code == 409
    assert expired.json()["error"]["code"] == "agent_action_expired"
    with client.app.state.session_factory() as session:
        action = session.get(AgentAction, action_id)
        assert action is not None
        assert action.status == "expired"

    stranger = token_for(client, "agent-stranger@example.com")
    assert client.post(
        "/api/v1/agent/actions/" + action_id + "/undo", headers=_headers(stranger)
    ).status_code == 404
