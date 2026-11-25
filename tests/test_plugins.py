from pathlib import Path

from test_reviews_account import import_memory, token_for

FIXTURE_MEMORY = Path(__file__).parents[1] / "fixtures" / "synthetic" / "memory.md"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _install(client, token: str, name: str, permissions: list[str] | None = None):
    body: dict = {"name": name}
    if permissions is not None:
        body["permissions"] = permissions
    return client.post("/api/v1/plugins/install", headers=_headers(token), json=body)


def _enable(client, token: str, plugin_id: str):
    return client.post(
        "/api/v1/plugins/" + plugin_id + "/status",
        headers=_headers(token),
        json={"status": "enabled"},
    )


def _invoke(client, token: str, plugin_id: str, action: str, payload: dict):
    return client.post(
        "/api/v1/plugins/" + plugin_id + "/invoke",
        headers=_headers(token),
        json={"action": action, "payload": payload},
    )


def test_connector_install_preview_import_and_uninstall(client) -> None:
    token = token_for(client, "plugin-connector@example.com")
    catalog = client.get("/api/v1/plugins/catalog", headers=_headers(token)).json()
    assert catalog["total"] == 2
    assert {entry["name"] for entry in catalog["items"]} == {
        "generic-json-connector",
        "graph-search-agent",
    }

    installed = _install(
        client,
        token,
        "generic-json-connector",
        permissions=[
            "connector.preview",
            "connector.import",
            "connector.delete",
            "connector.read_selected_path",
        ],
    )
    assert installed.status_code == 201, installed.text
    plugin = installed.json()
    assert plugin["status"] == "installed"
    assert set(plugin["permissions"]) == {
        "connector.preview",
        "connector.import",
        "connector.delete",
        "connector.read_selected_path",
    }

    content = FIXTURE_MEMORY.read_text(encoding="utf-8")
    disabled = _invoke(
        client, token, plugin["id"], "preview", {"filename": "memory.md", "content": content}
    )
    assert disabled.status_code == 409
    assert disabled.json()["error"]["code"] == "plugin_disabled"

    assert _enable(client, token, plugin["id"]).status_code == 200
    preview = _invoke(
        client, token, plugin["id"], "preview", {"filename": "memory.md", "content": content}
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["total"] >= 1
    assert preview.json()["preview"][0]["source_locator"]

    imported = _invoke(
        client, token, plugin["id"], "import", {"filename": "memory.md", "content": content}
    )
    assert imported.status_code == 200, imported.text
    result = imported.json()
    assert result["items_created"] >= 1
    sources = client.get("/api/v1/sources", headers=_headers(token)).json()
    assert any(source["id"] == result["source_id"] for source in sources)

    deleted = _invoke(client, token, plugin["id"], "delete", {"source_id": result["source_id"]})
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] is True
    remaining = client.get("/api/v1/sources", headers=_headers(token)).json()
    assert all(source["id"] != result["source_id"] for source in remaining)

    disabled_response = client.post(
        "/api/v1/plugins/" + plugin["id"] + "/status",
        headers=_headers(token),
        json={"status": "disabled"},
    )
    assert disabled_response.status_code == 200
    assert _invoke(
        client, token, plugin["id"], "preview", {"filename": "memory.md", "content": content}
    ).status_code == 409

    removed = client.delete("/api/v1/plugins/" + plugin["id"], headers=_headers(token))
    assert removed.status_code == 204
    assert client.get("/api/v1/plugins", headers=_headers(token)).json()["total"] == 0
    audit = client.get("/api/v1/plugins/audit", headers=_headers(token)).json()
    assert audit["total"] >= 4
    assert {entry["status"] for entry in audit["items"]} >= {"succeeded", "denied"}


def test_undeclared_permissions_are_denied_and_failures_are_isolated(client) -> None:
    token = token_for(client, "plugin-permissions@example.com")
    installed = _install(
        client,
        token,
        "generic-json-connector",
        permissions=["connector.preview", "connector.read_selected_path"],
    )
    assert installed.status_code == 201, installed.text
    plugin = installed.json()
    assert _enable(client, token, plugin["id"]).status_code == 200
    content = FIXTURE_MEMORY.read_text(encoding="utf-8")

    preview = _invoke(
        client, token, plugin["id"], "preview", {"filename": "memory.md", "content": content}
    )
    assert preview.status_code == 200, preview.text
    denied = _invoke(
        client, token, plugin["id"], "import", {"filename": "memory.md", "content": content}
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "plugin_permission_denied"

    failed = _invoke(
        client, token, plugin["id"], "preview", {"filename": "bad.html", "content": "<html>"}
    )
    assert failed.status_code == 422
    assert failed.json()["error"]["code"] == "plugin_unsupported_file"

    audit = client.get("/api/v1/plugins/audit", headers=_headers(token)).json()
    assert any(entry["status"] == "denied" for entry in audit["items"])
    assert any(entry["status"] == "failed" for entry in audit["items"])
    assert client.get("/api/v1/timeline", headers=_headers(token)).status_code == 200

    invalid = client.post(
        "/api/v1/plugins/install",
        headers=_headers(token),
        json={"name": "generic-json-connector", "permissions": ["connector.preview"]},
    )
    assert invalid.status_code == 409
    unknown = client.post(
        "/api/v1/plugins/install",
        headers=_headers(token),
        json={"name": "not-a-plugin"},
    )
    assert unknown.status_code == 404


def test_reference_agent_tool_searches_graph(client) -> None:
    token = token_for(client, "plugin-agent@example.com")
    _source_id, item_ids = import_memory(client, token)
    created = client.post(
        "/api/v1/agent/actions",
        headers=_headers(token),
        json={
            "kind": "create_project",
            "payload": {"name": "Life OS", "summary": "Local memory project", "source_item_ids": item_ids[:1]},
        },
    )
    assert created.status_code == 201, created.text

    installed = _install(client, token, "graph-search-agent")
    assert installed.status_code == 201, installed.text
    plugin = installed.json()
    assert _enable(client, token, plugin["id"]).status_code == 200
    result = _invoke(client, token, plugin["id"], "search", {"query": "Life OS"})
    assert result.status_code == 200, result.text
    assert result.json()["results"][0]["name"] == "Life OS"
    assert result.json()["results"][0]["evidence"]

    stranger = token_for(client, "plugin-stranger@example.com")
    assert client.get("/api/v1/plugins", headers=_headers(stranger)).json()["total"] == 0
    assert _invoke(client, stranger, plugin["id"], "search", {"query": "Life OS"}).status_code == 404
    assert client.delete(
        "/api/v1/plugins/" + plugin["id"], headers=_headers(stranger)
    ).status_code == 404
