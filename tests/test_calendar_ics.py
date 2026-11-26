from datetime import UTC, datetime
from textwrap import dedent

import pytest
from sqlalchemy import select

from personal_ai_life_os.models import SourceItem
from personal_ai_life_os.parsers.calendar_ics import UnsupportedCalendarError, parse_calendar
from personal_ai_life_os.services.deletion import replay_deletion_tombstones


def register(client, email: str = "calendar@example.test") -> str:
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


def calendar(*events: str, method: str | None = None) -> bytes:
    method_line = f"METHOD:{method}\r\n" if method else ""
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Life OS//Synthetic//EN\r\n"
        + method_line
        + "".join("BEGIN:VEVENT\r\n" + event.strip() + "\r\nEND:VEVENT\r\n" for event in events)
        + "END:VCALENDAR\r\n"
    ).encode("utf-8")


def event(
    uid: str,
    *,
    sequence: int = 0,
    start: str = "DTSTART;TZID=Asia/Shanghai:20261125T090000",
    end: str = "DTEND;TZID=Asia/Shanghai:20261125T100000",
    summary: str = "Planning review",
    extra: str = "",
    status: str | None = None,
) -> str:
    return dedent(
        f"""\
        UID:{uid}
        SEQUENCE:{sequence}
        {start}
        {end}
        SUMMARY:{summary}
        DESCRIPTION:Discuss the next release.
        LOCATION:Room 42
        {extra}
        {f"STATUS:{status}" if status else ""}
        """
    ).strip()


def create_source(client, token: str) -> str:
    response = client.post(
        "/api/v1/sources",
        headers={"Authorization": f"Bearer {token}"},
        json={"kind": "calendar_ics", "name": "Synthetic calendar", "selected_scope": {}},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def import_calendar(client, token: str, source_id: str, payload: bytes):
    return client.post(
        f"/api/v1/sources/{source_id}/imports",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("calendar.ics", payload, "text/calendar")},
    )


def test_parser_normalizes_timezone_all_day_floating_and_dst() -> None:
    payload = calendar(
        event("zoned", start="DTSTART;TZID=America/New_York:20261101T013000", end="DTEND;TZID=America/New_York:20261101T023000"),
        event("all-day", start="DTSTART;VALUE=DATE:20261126", end="DTEND;VALUE=DATE:20261127"),
        event("floating", start="DTSTART:20261125T090000", end="DTEND:20261125T100000"),
    )
    preview = parse_calendar(payload, user_timezone="Asia/Shanghai")
    zoned, all_day, floating = preview.items
    assert zoned.occurred_at == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    assert zoned.metadata["original_tzid"] == "America/New_York"
    assert zoned.metadata["dst_ambiguous"] is True
    assert zoned.metadata["location"] == "Room 42"
    assert all_day.occurred_at == datetime(2026, 11, 25, 16, 0, tzinfo=UTC)
    assert all_day.metadata["all_day"] is True
    assert floating.occurred_at == datetime(2026, 11, 25, 1, 0, tzinfo=UTC)
    assert floating.metadata["floating"] is True

    with pytest.raises(UnsupportedCalendarError, match="does not exist"):
        parse_calendar(
            calendar(event("dst-gap", start="DTSTART;TZID=America/New_York:20260308T023000")),
            user_timezone="America/New_York",
        )


def test_calendar_snapshot_updates_cancels_and_removes_missing_events(client) -> None:
    token = register(client)
    headers = {"Authorization": f"Bearer {token}"}
    source_id = create_source(client, token)
    first_payload = calendar(
        event("event-a"),
        event("event-b", start="DTSTART;VALUE=DATE:20261126", end="DTEND;VALUE=DATE:20261127", summary="All day"),
    )
    first = import_calendar(client, token, source_id, first_payload)
    assert first.status_code == 201, first.text
    assert first.json()["sync_run"]["items_created"] == 2
    assert {item["source_locator"]["uid"] for item in first.json()["items"]} == {"event-a", "event-b"}

    repeated = import_calendar(client, token, source_id, first_payload)
    assert repeated.json()["sync_run"]["items_duplicate"] == 2
    assert client.get("/api/v1/timeline", headers=headers).json()["total"] == 2

    updated_payload = calendar(
        event("event-a", sequence=1, start="DTSTART;TZID=Asia/Shanghai:20261125T110000", end="DTEND;TZID=Asia/Shanghai:20261125T120000", summary="Updated planning"),
        event("event-b", start="DTSTART;VALUE=DATE:20261126", end="DTEND;VALUE=DATE:20261127", summary="All day"),
    )
    updated = import_calendar(client, token, source_id, updated_payload)
    assert updated.json()["sync_run"]["items_updated"] == 1
    current = client.get("/api/v1/timeline", headers=headers).json()["items"]
    assert len(current) == 2
    assert next(item for item in current if item["source_locator"]["uid"] == "event-a")["title"] == "Updated planning"

    older = import_calendar(client, token, source_id, first_payload)
    assert older.json()["sync_run"]["items_skipped"] == 1
    assert older.json()["sync_run"]["items_updated"] == 0

    cancelled = import_calendar(
        client,
        token,
        source_id,
        calendar(
            "UID:event-a\r\nSEQUENCE:2\r\nMETHOD:CANCEL\r\nSTATUS:CANCELLED",
            event("event-b", start="DTSTART;VALUE=DATE:20261126", end="DTEND;VALUE=DATE:20261127", summary="All day"),
        ),
    )
    assert cancelled.json()["sync_run"]["items_removed"] == 1
    assert client.get("/api/v1/timeline", headers=headers).json()["total"] == 1
    assert client.get("/api/v1/search", headers=headers, params={"q": "Planning"}).json()["timeline"]["total"] == 0

    replacement = import_calendar(client, token, source_id, calendar(event("event-c", summary="Replacement")))
    assert replacement.json()["sync_run"]["items_removed"] == 1
    assert replacement.json()["sync_run"]["items_created"] == 1
    timeline = client.get("/api/v1/timeline", headers=headers).json()
    assert timeline["total"] == 1
    assert timeline["items"][0]["source_locator"]["uid"] == "event-c"

    with client.app.state.session_factory() as session:
        old_item = session.scalar(
            select(SourceItem)
            .where(SourceItem.external_id == "event-a", SourceItem.deleted_at.is_not(None))
            .order_by(SourceItem.created_at.desc())
            .limit(1)
        )
        assert old_item is not None
        old_item.is_current = True
        old_item.deleted_at = None
        restored_item_id = old_item.id
        session.commit()
    assert replay_deletion_tombstones(client.app.state.session_factory, client.app.state.object_store) >= 1
    assert client.get(f"/api/v1/items/{restored_item_id}", headers=headers).status_code == 404


def test_invalid_snapshot_does_not_change_current_calendar(client) -> None:
    token = register(client, "invalid-calendar@example.test")
    headers = {"Authorization": f"Bearer {token}"}
    source_id = create_source(client, token)
    assert import_calendar(client, token, source_id, calendar(event("kept"))).status_code == 201

    invalid = import_calendar(client, token, source_id, calendar(event("duplicate"), event("duplicate")))
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "unsupported_calendar"
    timeline = client.get("/api/v1/timeline", headers=headers)
    assert timeline.json()["total"] == 1
    assert timeline.json()["items"][0]["source_locator"]["uid"] == "kept"


def test_recurring_events_are_reported_and_protect_existing_single_event(client) -> None:
    token = register(client, "recurring@example.test")
    headers = {"Authorization": f"Bearer {token}"}
    source_id = create_source(client, token)
    assert import_calendar(client, token, source_id, calendar(event("series"))).status_code == 201

    recurring = import_calendar(
        client,
        token,
        source_id,
        calendar(event("series", sequence=1, extra="RRULE:FREQ=WEEKLY;COUNT=4")),
    )
    assert recurring.status_code == 201
    assert recurring.json()["sync_run"]["items_skipped"] == 1
    assert recurring.json()["sync_run"]["items_removed"] == 0
    timeline = client.get("/api/v1/timeline", headers=headers).json()
    assert timeline["total"] == 1
    assert timeline["items"][0]["metadata"]["ics_sequence"] == 0


def test_calendar_source_is_owner_scoped(client) -> None:
    owner_a = register(client, "calendar-a@example.test")
    owner_b = register(client, "calendar-b@example.test")
    source_id = create_source(client, owner_a)
    imported = import_calendar(client, owner_a, source_id, calendar(event("private")))
    item_id = imported.json()["items"][0]["id"]
    assert client.get(
        f"/api/v1/sources/{source_id}", headers={"Authorization": f"Bearer {owner_b}"}
    ).status_code == 404
    assert client.get(
        f"/api/v1/items/{item_id}", headers={"Authorization": f"Bearer {owner_b}"}
    ).status_code == 404
    assert client.get(
        "/api/v1/timeline", headers={"Authorization": f"Bearer {owner_b}"}
    ).json()["total"] == 0
