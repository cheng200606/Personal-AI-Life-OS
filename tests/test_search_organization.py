import json
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

from sqlalchemy import text

from personal_ai_life_os.services.search_index import rebuild_search_index, search_backend


def register(client, email: str) -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct horse battery staple", "timezone": "Asia/Shanghai"},
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def import_memory(client, token: str, content: str) -> str:
    source = client.post(
        "/api/v1/sources",
        headers=headers(token),
        json={"kind": "memory_markdown", "name": "M8 synthetic", "selected_scope": {}},
    )
    assert source.status_code == 201, source.text
    source_id = source.json()["id"]
    imported = client.post(
        f"/api/v1/sources/{source_id}/imports",
        headers=headers(token),
        files={"file": ("memory.md", content.encode("utf-8"), "text/markdown")},
    )
    assert imported.status_code == 201, imported.text
    return source_id


def test_fts_filters_saved_searches_and_trigger_updates(client) -> None:
    token = register(client, "m8-search@example.test")
    source_id = import_memory(
        client,
        token,
        "# 2026-11-20 Harbor record\n\nAlpha record about the harbor release.\n\n"
        "# 2026-11-22 Granite record\n\nBeta record about granite planning.",
    )
    with client.app.state.session_factory() as session:
        assert search_backend(session) == "sqlite-fts5-trigram"

    result = client.get("/api/v1/search", headers=headers(token), params={"q": "harbor release"})
    assert result.status_code == 200, result.text
    assert result.json()["index_backend"] == "sqlite-fts5-trigram"
    assert result.json()["timeline"]["total"] == 1
    assert "Harbor" in result.json()["timeline"]["results"][0]["title"]

    reminder = client.post(
        "/api/v1/reminders",
        headers=headers(token),
        json={"title": "Harbor follow-up", "notes": "Initial note", "due_at": "2026-11-21T09:00:00+08:00"},
    )
    assert reminder.status_code == 201, reminder.text
    reminder_id = reminder.json()["id"]
    client.patch(
        f"/api/v1/reminders/{reminder_id}/status",
        headers=headers(token),
        json={"status": "snoozed"},
    )

    review = client.post(
        "/api/v1/reviews/generate",
        headers=headers(token),
        json={"period_start": "2026-11-19", "period_end": "2026-11-23", "use_external_model": False},
    )
    assert review.status_code == 201, review.text
    review_id = review.json()["id"]
    client.patch(
        f"/api/v1/reviews/{review_id}",
        headers=headers(token),
        json={"final_text": "Confirmed the harbor release and granite planning."},
    )

    timeline_only = client.get(
        "/api/v1/search", headers=headers(token), params={"q": "record", "types": "timeline"}
    ).json()
    assert timeline_only["timeline"]["total"] == 2
    assert timeline_only["reviews"]["total"] == 0
    assert timeline_only["reminders"]["total"] == 0
    filtered = client.get(
        "/api/v1/search",
        headers=headers(token),
        params={"q": "record", "types": "timeline", "start": "2026-11-21", "end": "2026-11-23", "source_id": source_id},
    ).json()
    assert filtered["timeline"]["total"] == 1
    assert "Granite" in filtered["timeline"]["results"][0]["title"]
    assert client.get(
        "/api/v1/search", headers=headers(token), params={"q": "record", "source_id": "not-a-uuid"}
    ).status_code == 422
    reminders = client.get(
        "/api/v1/search",
        headers=headers(token),
        params={"q": "harbor", "types": "reminders", "status": "snoozed"},
    ).json()
    assert reminders["reminders"]["total"] == 1
    reviews = client.get(
        "/api/v1/search", headers=headers(token), params={"q": "harbor release", "types": "reviews"}
    ).json()
    assert reviews["reviews"]["total"] == 1

    saved = client.post(
        "/api/v1/saved-searches",
        headers=headers(token),
        json={
            "name": "Recent harbor",
            "query": "harbor",
            "filters": {"types": ["timeline", "reminders"], "start": "2026-11-19", "end": "2026-11-23", "status": ["snoozed"]},
        },
    )
    assert saved.status_code == 201, saved.text
    saved_id = saved.json()["id"]
    assert saved.json()["filters"]["types"] == ["timeline", "reminders"]
    assert client.post(
        "/api/v1/saved-searches",
        headers=headers(token),
        json={"name": "RECENT HARBOR", "query": "harbor"},
    ).status_code == 409
    renamed = client.patch(
        f"/api/v1/saved-searches/{saved_id}",
        headers=headers(token),
        json={"name": "Harbor follow-ups", "filters": {"types": ["reminders"]}},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Harbor follow-ups"
    assert len(client.get("/api/v1/saved-searches", headers=headers(token)).json()) == 1
    assert client.delete(f"/api/v1/saved-searches/{saved_id}", headers=headers(token)).status_code == 204


def test_tags_collections_organization_export_and_owner_isolation(client) -> None:
    owner_a = register(client, "m8-tags-a@example.test")
    owner_b = register(client, "m8-tags-b@example.test")
    source_id = import_memory(client, owner_a, "# 2026-11-20 Organized note\n\nTagged needle content.")
    item_id = client.get(
        f"/api/v1/sources/{source_id}/items", headers=headers(owner_a)
    ).json()["items"][0]["id"]

    tag = client.post(
        "/api/v1/tags", headers=headers(owner_a), json={"name": "Research", "color": "#aabbcc"}
    )
    assert tag.status_code == 201, tag.text
    tag_id = tag.json()["id"]
    assert tag.json()["color"] == "#AABBCC"
    assert client.post(
        "/api/v1/tags", headers=headers(owner_a), json={"name": "research"}
    ).status_code == 409
    collection = client.post(
        "/api/v1/collections",
        headers=headers(owner_a),
        json={"name": "Release notes", "description": "M8 delivery"},
    )
    assert collection.status_code == 201, collection.text
    collection_id = collection.json()["id"]
    organized = client.put(
        f"/api/v1/items/{item_id}/organization",
        headers=headers(owner_a),
        json={"tag_ids": [tag_id], "collection_ids": [collection_id]},
    )
    assert organized.status_code == 200, organized.text
    assert organized.json()["tags"][0]["name"] == "Research"
    assert client.put(
        f"/api/v1/items/{item_id}/organization",
        headers=headers(owner_a),
        json={"tag_ids": ["not-a-uuid"], "collection_ids": []},
    ).status_code == 422
    by_tag = client.get(
        "/api/v1/search", headers=headers(owner_a), params={"q": "needle", "tag_id": tag_id}
    ).json()
    assert by_tag["timeline"]["total"] == 1
    assert client.put(
        f"/api/v1/items/{item_id}/organization",
        headers=headers(owner_b),
        json={"tag_ids": [tag_id], "collection_ids": []},
    ).status_code == 404

    foreign = client.post(
        "/api/v1/tags", headers=headers(owner_b), json={"name": "Foreign"}
    ).json()["id"]
    assert client.put(
        f"/api/v1/items/{item_id}/organization",
        headers=headers(owner_a),
        json={"tag_ids": [foreign], "collection_ids": []},
    ).status_code == 422

    cleared = client.patch(
        f"/api/v1/tags/{tag_id}", headers=headers(owner_a), json={"clear_color": True}
    )
    assert cleared.json()["color"] is None
    archive = client.get("/api/v1/account/archive", headers=headers(owner_a))
    with ZipFile(BytesIO(archive.content)) as bundle:
        tags = json.loads(bundle.read("tags.json"))
        collections = json.loads(bundle.read("collections.json"))
        organization = json.loads(bundle.read("item-organization.json"))
    assert tags[0]["name"] == "Research"
    assert collections[0]["name"] == "Release notes"
    assert organization[0]["tag_ids"] == [tag_id]

    assert client.delete(f"/api/v1/tags/{tag_id}", headers=headers(owner_a)).status_code == 204
    assert client.get(f"/api/v1/items/{item_id}", headers=headers(owner_a)).status_code == 200
    assert client.get(
        "/api/v1/search", headers=headers(owner_a), params={"q": "needle", "tag_id": tag_id}
    ).json()["timeline"]["total"] == 0
    assert client.delete(f"/api/v1/collections/{collection_id}", headers=headers(owner_a)).status_code == 204
    assert client.get("/api/v1/tags", headers=headers(owner_b)).json()[0]["name"] == "Foreign"


def test_stale_index_rows_and_deleted_items_are_not_recalled(client) -> None:
    token = register(client, "m8-stale@example.test")
    source_id = import_memory(client, token, "# 2026-11-20 Phantom note\n\nUnique phantom content.")
    with client.app.state.session_factory() as session:
        session.execute(
            text("INSERT INTO timeline_fts(item_id, title, content) VALUES (:id, :title, :content)"),
            {"id": str(uuid4()), "title": "Stale phantom", "content": "stale phantom needle"},
        )
        session.commit()
    stale = client.get(
        "/api/v1/search", headers=headers(token), params={"q": "stale phantom needle"}
    ).json()
    assert stale["timeline"]["total"] == 0
    assert client.delete(f"/api/v1/sources/{source_id}", headers=headers(token)).status_code == 204
    assert client.get(
        "/api/v1/search", headers=headers(token), params={"q": "phantom"}
    ).json()["timeline"]["total"] == 0
    with client.app.state.session_factory() as session:
        assert rebuild_search_index(session) == "sqlite-fts5-trigram"
        assert session.scalar(text("SELECT count(*) FROM timeline_fts")) == 0


def test_organization_survives_calendar_event_version_update(client) -> None:
    token = register(client, "m8-calendar-tags@example.test")
    source = client.post(
        "/api/v1/sources",
        headers=headers(token),
        json={"kind": "calendar_ics", "name": "Tagged calendar", "selected_scope": {}},
    )
    assert source.status_code == 201, source.text
    source_id = source.json()["id"]

    def payload(sequence: int, summary: str) -> bytes:
        return (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//M8//EN\r\nBEGIN:VEVENT\r\n"
            f"UID:tagged-event\r\nSEQUENCE:{sequence}\r\n"
            "DTSTART;TZID=Asia/Shanghai:20261125T090000\r\n"
            "DTEND;TZID=Asia/Shanghai:20261125T100000\r\n"
            f"SUMMARY:{summary}\r\nDESCRIPTION:Tagged needle event\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        ).encode()

    first = client.post(
        f"/api/v1/sources/{source_id}/imports",
        headers=headers(token),
        files={"file": ("calendar.ics", payload(0, "Original event"), "text/calendar")},
    )
    assert first.status_code == 201, first.text
    item_id = first.json()["items"][0]["id"]
    tag = client.post("/api/v1/tags", headers=headers(token), json={"name": "Calendar"}).json()
    collection = client.post("/api/v1/collections", headers=headers(token), json={"name": "Planning"}).json()
    assert client.put(
        f"/api/v1/items/{item_id}/organization",
        headers=headers(token),
        json={"tag_ids": [tag["id"]], "collection_ids": [collection["id"]]},
    ).status_code == 200

    updated = client.post(
        f"/api/v1/sources/{source_id}/imports",
        headers=headers(token),
        files={"file": ("calendar.ics", payload(1, "Updated event"), "text/calendar")},
    )
    assert updated.status_code == 201, updated.text
    result = client.get(
        "/api/v1/search",
        headers=headers(token),
        params={"q": "needle", "tag_id": tag["id"], "collection_id": collection["id"]},
    ).json()
    assert result["timeline"]["total"] == 1
    assert result["timeline"]["results"][0]["title"] == "Updated event"
    organization = client.get(
        f"/api/v1/items/{result['timeline']['results'][0]['id']}/organization", headers=headers(token)
    ).json()
    assert organization["tags"][0]["id"] == tag["id"]
    assert organization["collections"][0]["id"] == collection["id"]
