from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

FIXTURES = Path(__file__).parents[1] / "fixtures" / "synthetic"


def register(client, email: str) -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "timezone": "Asia/Shanghai",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def create_memory_source(client, token: str) -> str:
    response = client.post(
        "/api/v1/sources",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "kind": "memory_markdown",
            "name": "Synthetic memory",
            "selected_scope": {"filename": "memory.md"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def import_memory(client, token: str, source_id: str, content: bytes | None = None):
    payload = content if content is not None else (FIXTURES / "memory.md").read_bytes()
    return client.post(
        f"/api/v1/sources/{source_id}/imports",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("memory.md", payload, "text/markdown")},
    )


def test_register_login_and_private_endpoints(client) -> None:
    token = register(client, "Alice@example.com")

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "ALICE@example.com", "password": "correct horse battery staple"},
    )
    assert login.status_code == 200
    assert login.json()["token_type"] == "bearer"

    unauthenticated = client.get("/api/v1/sources")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"]["code"] == "auth_required"


def test_memory_import_is_traceable_and_idempotent(client) -> None:
    token = register(client, "importer@example.com")
    source_id = create_memory_source(client, token)

    first = import_memory(client, token, source_id)
    assert first.status_code == 201, first.text
    assert first.json()["sync_run"]["items_created"] == 3
    assert first.json()["items"][0]["source_locator"]["line_start"] == 3

    repeated = import_memory(client, token, source_id)
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["sync_run"]["items_created"] == 0
    assert repeated.json()["sync_run"]["items_duplicate"] == 3

    timeline = client.get("/api/v1/timeline", headers={"Authorization": f"Bearer {token}"})
    assert timeline.status_code == 200
    assert timeline.json()["total"] == 3
    assert any(item["occurred_at"] is None for item in timeline.json()["items"])

    item_id = timeline.json()["items"][0]["id"]
    raw = client.get(
        f"/api/v1/items/{item_id}/raw",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert raw.status_code == 200
    assert raw.content == (FIXTURES / "memory.md").read_bytes()


def test_owner_isolation_covers_read_download_and_delete(client) -> None:
    owner_a = register(client, "a@example.com")
    owner_b = register(client, "b@example.com")
    source_id = create_memory_source(client, owner_a)
    imported = import_memory(client, owner_a, source_id)
    item_id = imported.json()["items"][0]["id"]

    assert client.get(
        f"/api/v1/sources/{source_id}",
        headers={"Authorization": f"Bearer {owner_b}"},
    ).status_code == 404
    assert client.get(
        f"/api/v1/items/{item_id}",
        headers={"Authorization": f"Bearer {owner_b}"},
    ).status_code == 404
    assert client.get(
        f"/api/v1/items/{item_id}/raw",
        headers={"Authorization": f"Bearer {owner_b}"},
    ).status_code == 404
    assert client.get(
        "/api/v1/timeline",
        headers={"Authorization": f"Bearer {owner_b}"},
    ).json()["total"] == 0
    assert client.delete(
        f"/api/v1/sources/{source_id}",
        headers={"Authorization": f"Bearer {owner_b}"},
    ).status_code == 404

    assert client.get(
        f"/api/v1/items/{item_id}",
        headers={"Authorization": f"Bearer {owner_a}"},
    ).status_code == 200


def test_pause_revoke_and_delete_block_future_access(client) -> None:
    token = register(client, "lifecycle@example.com")
    source_id = create_memory_source(client, token)
    headers = {"Authorization": f"Bearer {token}"}
    imported = import_memory(client, token, source_id)
    item_id = imported.json()["items"][0]["id"]

    paused = client.patch(
        f"/api/v1/sources/{source_id}/status",
        headers=headers,
        json={"status": "paused"},
    )
    assert paused.status_code == 200
    assert import_memory(client, token, source_id).status_code == 409

    assert client.patch(
        f"/api/v1/sources/{source_id}/status",
        headers=headers,
        json={"status": "active"},
    ).status_code == 200
    assert client.post(f"/api/v1/sources/{source_id}/revoke", headers=headers).status_code == 200
    assert import_memory(client, token, source_id).status_code == 409

    deleted = client.delete(f"/api/v1/sources/{source_id}", headers=headers)
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/items/{item_id}", headers=headers).status_code == 404
    assert client.get(f"/api/v1/items/{item_id}/raw", headers=headers).status_code == 404


def test_concurrent_reimport_does_not_duplicate_items(client) -> None:
    token = register(client, "concurrent@example.com")
    source_id = create_memory_source(client, token)

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: import_memory(client, token, source_id), range(4)))

    assert all(response.status_code == 201 for response in responses), [
        response.text for response in responses if response.status_code != 201
    ]
    assert sum(response.json()["sync_run"]["items_created"] for response in responses) == 3
    timeline = client.get("/api/v1/timeline", headers={"Authorization": f"Bearer {token}"})
    assert timeline.json()["total"] == 3


def test_timeline_search_date_and_source_filters(client) -> None:
    token = register(client, "search@example.com")
    source_id = create_memory_source(client, token)
    assert import_memory(client, token, source_id).status_code == 201
    headers = {"Authorization": f"Bearer {token}"}

    result = client.get(
        "/api/v1/timeline",
        headers=headers,
        params={"q": "Postgres", "start": "2026-11-16", "end": "2026-11-18", "source_id": source_id},
    )
    assert result.status_code == 200
    assert result.json()["total"] == 1
    assert result.json()["items"][0]["title"].startswith("2026-11-16")

    no_undated = client.get(
        "/api/v1/timeline",
        headers=headers,
        params={"start": "2026-11-16", "end": "2026-11-18", "include_undated": False},
    )
    assert all(item["occurred_at"] is not None for item in no_undated.json()["items"])


def test_date_only_markdown_uses_user_calendar_day_without_claiming_source_timezone(client) -> None:
    register_response = client.post(
        "/api/v1/auth/register",
        json={"email": "los-angeles@example.com", "password": "correct horse battery staple", "timezone": "America/Los_Angeles"},
    )
    token = register_response.json()["access_token"]
    source_id = create_memory_source(client, token)
    import_memory(client, token, source_id)
    headers = {"Authorization": "Bearer " + token}
    result = client.get(
        "/api/v1/timeline",
        headers=headers,
        params={"start": "2026-11-16", "end": "2026-11-17", "include_undated": False},
    )
    assert result.status_code == 200
    assert result.json()["total"] == 1
    assert result.json()["items"][0]["metadata"]["date_basis_timezone"] == "America/Los_Angeles"
    assert result.json()["items"][0]["source_timezone"] is None
