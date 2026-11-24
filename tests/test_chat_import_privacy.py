import json
from pathlib import Path

FIXTURES = Path(__file__).parents[1] / "fixtures" / "synthetic"
CHAT_PATH = FIXTURES / "conversations.json"
CONVERSATION_ID = "synthetic-conversation-001"


def register(client, email: str) -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct horse battery staple"},
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def test_chat_import_stores_only_the_selected_conversation(client) -> None:
    token = register(client, "chat@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    source_response = client.post(
        "/api/v1/sources",
        headers=headers,
        json={
            "kind": "chatgpt_export",
            "name": "conversations.json",
            "selected_scope": {"conversation_ids": [CONVERSATION_ID]},
        },
    )
    assert source_response.status_code == 201, source_response.text
    source_id = source_response.json()["id"]

    response = client.post(
        f"/api/v1/sources/{source_id}/imports",
        headers=headers,
        data={"conversation_ids": json.dumps([CONVERSATION_ID])},
        files={"file": ("conversations.json", CHAT_PATH.read_bytes(), "application/json")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["sync_run"]["items_created"] == 2

    item_id = response.json()["items"][0]["id"]
    raw = client.get(f"/api/v1/items/{item_id}/raw", headers=headers)
    assert raw.status_code == 200
    minimized = json.loads(raw.content)
    assert [conversation["id"] for conversation in minimized] == [CONVERSATION_ID]
    assert "synthetic-conversation-002" not in raw.text
    assert "Ignore every rule" not in raw.text


def test_chat_upload_cannot_exceed_the_saved_consent_scope(client) -> None:
    token = register(client, "scope@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    source = client.post(
        "/api/v1/sources",
        headers=headers,
        json={
            "kind": "chatgpt_export",
            "name": "conversations.json",
            "selected_scope": {"conversation_ids": [CONVERSATION_ID]},
        },
    ).json()

    response = client.post(
        f"/api/v1/sources/{source['id']}/imports",
        headers=headers,
        data={"conversation_ids": json.dumps([CONVERSATION_ID, "synthetic-conversation-002"])},
        files={"file": ("conversations.json", CHAT_PATH.read_bytes(), "application/json")},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "conversation_scope_exceeded"
    assert client.get("/api/v1/timeline", headers=headers).json()["total"] == 0
