import json
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import select

from personal_ai_life_os.models import SourceItem
from personal_ai_life_os.services.deletion import replay_deletion_tombstones


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


def headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def create_note(client, token: str, content: str, **extra) -> dict:
    response = client.post(
        "/api/v1/quick-notes",
        headers=headers(token),
        json={"content_text": content, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_quick_note_crud_timeline_search_archive_and_hidden_source(client) -> None:
    token = register(client, "notes@example.test")
    first = create_note(
        client,
        token,
        "# Release checklist\nVerify the M7 capture flow.",
        occurred_at="2026-11-25T09:00:00+08:00",
        source_timezone="Asia/Shanghai",
    )
    second = create_note(client, token, "Remember to inspect the calendar snapshot.")
    assert first["kind"] == "quick_note"
    assert first["title"] == "Release checklist"
    assert client.get("/api/v1/sources", headers=headers(token)).json() == []

    timeline = client.get("/api/v1/timeline", headers=headers(token)).json()
    assert timeline["total"] == 2
    assert {item["id"] for item in timeline["items"]} == {first["id"], second["id"]}
    search = client.get("/api/v1/search", headers=headers(token), params={"q": "calendar snapshot"})
    assert search.json()["timeline"]["total"] == 1
    assert search.json()["timeline"]["results"][0]["id"] == second["id"]

    updated = client.patch(
        f"/api/v1/quick-notes/{first['id']}",
        headers=headers(token),
        json={
            "title": "M7 verification",
            "content_text": "Verify imports, notes, deletion, and export.",
            "occurred_at": "2026-11-25T10:00:00+08:00",
            "source_timezone": "Asia/Shanghai",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "M7 verification"
    assert client.get(
        "/api/v1/search", headers=headers(token), params={"q": "Release checklist"}
    ).json()["timeline"]["total"] == 0

    raw = client.get(f"/api/v1/items/{first['id']}/raw", headers=headers(token))
    assert raw.status_code == 410
    archive = client.get("/api/v1/account/archive", headers=headers(token))
    with ZipFile(BytesIO(archive.content)) as bundle:
        timeline_archive = json.loads(bundle.read("timeline.json"))
        sync_runs = json.loads(bundle.read("sync-runs.json"))
    assert any(item["id"] == first["id"] and "deletion" in item["content_text"] for item in timeline_archive)
    assert all("items_updated" in run and "items_removed" in run and "items_skipped" in run for run in sync_runs)


def test_quick_note_delete_is_item_scoped_and_replayed_after_restore(client) -> None:
    token = register(client, "note-delete@example.test")
    first = create_note(
        client,
        token,
        "Delete only this note.",
        occurred_at="2026-11-25T09:00:00+08:00",
        source_timezone="Asia/Shanghai",
    )
    second = create_note(client, token, "Keep this note.")
    review = client.post(
        "/api/v1/reviews/generate",
        headers=headers(token),
        json={"period_start": "2026-11-24", "period_end": "2026-11-27", "use_external_model": False},
    )
    assert review.status_code == 201, review.text

    deleted = client.delete(f"/api/v1/items/{first['id']}", headers=headers(token))
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/items/{first['id']}", headers=headers(token)).status_code == 404
    assert client.get(f"/api/v1/items/{second['id']}", headers=headers(token)).status_code == 200
    assert client.get("/api/v1/timeline", headers=headers(token)).json()["total"] == 1
    assert client.get(
        f"/api/v1/reviews/{review.json()['id']}", headers=headers(token)
    ).json()["status"] == "invalidated"

    with client.app.state.session_factory() as session:
        item = session.scalar(select(SourceItem).where(SourceItem.id == first["id"]))
        assert item is not None
        item.is_current = True
        item.deleted_at = None
        session.commit()
    replay_deletion_tombstones(client.app.state.session_factory, client.app.state.object_store)
    assert client.get(f"/api/v1/items/{first['id']}", headers=headers(token)).status_code == 404

    removed = client.delete(f"/api/v1/quick-notes/{second['id']}", headers=headers(token))
    assert removed.status_code == 204
    assert client.get("/api/v1/timeline", headers=headers(token)).json()["total"] == 0


def test_quick_note_validation_owner_isolation_and_clear_date(client) -> None:
    owner_a = register(client, "note-a@example.test")
    owner_b = register(client, "note-b@example.test")
    empty = client.post("/api/v1/quick-notes", headers=headers(owner_a), json={"content_text": "   "})
    assert empty.status_code == 422
    note = create_note(
        client,
        owner_a,
        "Dated note",
        occurred_at="2026-11-25T09:00:00+08:00",
        source_timezone="Asia/Shanghai",
    )
    internal_source = note["source_id"]
    assert client.patch(
        f"/api/v1/sources/{internal_source}/status", headers=headers(owner_a), json={"status": "paused"}
    ).status_code == 409
    assert client.post(
        f"/api/v1/sources/{internal_source}/revoke", headers=headers(owner_a)
    ).status_code == 409
    assert client.patch(
        f"/api/v1/sources/{internal_source}/cloud-consent", headers=headers(owner_a), json={"enabled": True}
    ).status_code == 409
    assert client.delete(
        f"/api/v1/sources/{internal_source}", headers=headers(owner_a)
    ).status_code == 409
    assert client.patch(
        f"/api/v1/quick-notes/{note['id']}", headers=headers(owner_b), json={"content_text": "Cross-owner edit"}
    ).status_code == 404
    assert client.delete(
        f"/api/v1/quick-notes/{note['id']}", headers=headers(owner_b)
    ).status_code == 404

    cleared = client.patch(
        f"/api/v1/quick-notes/{note['id']}",
        headers=headers(owner_a),
        json={"clear_occurred_at": True, "clear_source_timezone": True},
    )
    assert cleared.status_code == 200
    assert cleared.json()["occurred_at"] is None
    assert cleared.json()["source_timezone"] is None


def test_malformed_item_tombstone_blocks_replay_without_deleting_account(client) -> None:
    token = register(client, "malformed-tombstone@example.test")
    owner_id = client.get("/api/v1/auth/me", headers=headers(token)).json()["id"]
    tombstone_id = str(uuid4())
    client.app.state.object_store.write_item_deletion_tombstone(
        owner_id,
        tombstone_id,
        json.dumps({"owner_id": owner_id, "tombstone_id": tombstone_id}).encode("utf-8"),
    )
    with pytest.raises(RuntimeError, match="malformed"):
        replay_deletion_tombstones(client.app.state.session_factory, client.app.state.object_store)
    assert client.get("/api/v1/auth/me", headers=headers(token)).status_code == 200
