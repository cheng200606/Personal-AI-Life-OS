from pathlib import Path

from test_reviews_account import token_for

FIXTURE_MEMORY = Path(__file__).parents[1] / "fixtures" / "synthetic" / "memory.md"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def import_markdown(client, token: str, content: str, *, name: str = "search notes") -> str:
    headers = _headers(token)
    source = client.post(
        "/api/v1/sources",
        headers=headers,
        json={"kind": "memory_markdown", "name": name, "selected_scope": {}},
    )
    assert source.status_code == 201, source.text
    source_id = source.json()["id"]
    imported = client.post(
        "/api/v1/sources/" + source_id + "/imports",
        headers=headers,
        files={"file": ("notes.md", content.encode("utf-8"), "text/markdown")},
    )
    assert imported.status_code == 201, imported.text
    return source_id


def search(client, token: str, q: str, **params) -> dict:
    response = client.get("/api/v1/search", headers=_headers(token), params={"q": q, **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_search_matches_timeline_reviews_and_reminders(client) -> None:
    token = token_for(client, "search-cross@example.com")
    headers = _headers(token)
    source = client.post(
        "/api/v1/sources",
        headers=headers,
        json={"kind": "memory_markdown", "name": "synthetic notes", "selected_scope": {}},
    )
    assert source.status_code == 201, source.text
    imported = client.post(
        "/api/v1/sources/" + source.json()["id"] + "/imports",
        headers=headers,
        files={"file": ("memory.md", FIXTURE_MEMORY.read_bytes(), "text/markdown")},
    )
    assert imported.status_code == 201, imported.text
    review = client.post(
        "/api/v1/reviews/generate",
        headers=headers,
        json={"period_start": "2026-11-16", "period_end": "2026-11-18"},
    )
    assert review.status_code == 201, review.text
    reminder = client.post(
        "/api/v1/reminders",
        headers=headers,
        json={"title": "Postgres follow-up", "notes": "Confirm the Postgres decision."},
    )
    assert reminder.status_code == 201, reminder.text

    body = search(client, token, "Postgres")

    assert body["query"] == "Postgres"
    assert body["timeline"]["total"] >= 1
    assert body["reviews"]["total"] >= 1
    assert body["reminders"]["total"] >= 1
    timeline_hit = body["timeline"]["results"][0]
    assert set(timeline_hit) == {
        "id",
        "source_id",
        "source_name",
        "title",
        "snippet",
        "occurred_at",
        "kind",
    }
    assert timeline_hit["source_name"] == "synthetic notes"
    assert "content_text" not in timeline_hit
    assert set(body["reviews"]["results"][0]) == {
        "id",
        "period_start",
        "period_end",
        "status",
        "snippet",
        "updated_at",
    }
    assert set(body["reminders"]["results"][0]) == {
        "id",
        "title",
        "snippet",
        "due_at",
        "status",
    }
    for group in ("timeline", "reviews", "reminders"):
        for result in body[group]["results"]:
            assert len(result["snippet"]) <= 200


def test_search_is_owner_scoped(client) -> None:
    owner = token_for(client, "search-owner@example.com")
    other = token_for(client, "search-other@example.com")
    import_markdown(
        client,
        other,
        "# Other notes\n\n## 2026-11-17 — Private\n\nA ZephyrExclusive decision.\n",
        name="other notes",
    )

    body = search(client, owner, "ZephyrExclusive")

    assert body["timeline"]["total"] == 0
    assert body["reviews"]["total"] == 0
    assert body["reminders"]["total"] == 0
    assert body["timeline"]["results"] == []


def test_search_excludes_deleted_sources_and_invalidated_reviews(client) -> None:
    token = token_for(client, "search-deleted@example.com")
    headers = _headers(token)
    source_id = import_markdown(
        client,
        token,
        "# Notes\n\n## 2026-11-17 — Choice\n\nThe ErasureTerm phrase is recorded here.\n",
    )
    review = client.post(
        "/api/v1/reviews/generate",
        headers=headers,
        json={"period_start": "2026-11-16", "period_end": "2026-11-18"},
    )
    assert review.status_code == 201, review.text
    assert search(client, token, "ErasureTerm")["timeline"]["total"] == 1
    assert search(client, token, "ErasureTerm")["reviews"]["total"] == 1

    deleted = client.delete("/api/v1/sources/" + source_id, headers=headers)
    assert deleted.status_code == 204, deleted.text
    assert client.get("/api/v1/reviews/" + review.json()["id"], headers=headers).json()["status"] == (
        "invalidated"
    )

    body = search(client, token, "ErasureTerm")

    assert body["timeline"]["total"] == 0
    assert body["reviews"]["total"] == 0


def test_search_query_validation(client) -> None:
    token = token_for(client, "search-validation@example.com")
    headers = _headers(token)
    assert client.get("/api/v1/search", headers=headers).status_code == 422
    assert client.get("/api/v1/search", headers=headers, params={"q": ""}).status_code == 422
    whitespace = client.get("/api/v1/search", headers=headers, params={"q": "   "})
    assert whitespace.status_code == 422
    assert whitespace.json()["error"]["code"] == "invalid_search_query"
    too_long = client.get("/api/v1/search", headers=headers, params={"q": "a" * 201})
    assert too_long.status_code == 422


def test_search_reports_group_total_and_respects_limit(client) -> None:
    token = token_for(client, "search-limit@example.com")
    lines = ["# Bulk notes", ""]
    for index in range(15):
        lines.extend(
            [
                f"## 2026-10-{index + 1:02d} — Section {index + 1}",
                "",
                "NeedleTerm appears in this section body.",
                "",
            ]
        )
    import_markdown(client, token, "\n".join(lines))

    bounded = search(client, token, "NeedleTerm", limit=5)
    assert bounded["timeline"]["total"] == 15
    assert len(bounded["timeline"]["results"]) == 5

    default = search(client, token, "NeedleTerm")
    assert default["timeline"]["total"] == 15
    assert len(default["timeline"]["results"]) == 10


def test_search_prioritizes_title_matches(client) -> None:
    token = token_for(client, "search-title@example.com")
    import_markdown(
        client,
        token,
        "# Priority notes\n\n"
        "## 2026-10-01 — PriorityTerm heading\n\nRoutine body text only.\n\n"
        "## 2026-10-20 — Newer section\n\nThis body mentions PriorityTerm once.\n",
    )

    body = search(client, token, "PriorityTerm")

    assert body["timeline"]["total"] == 2
    assert body["timeline"]["results"][0]["title"] == "2026-10-01 — PriorityTerm heading"


def test_search_snippet_is_bounded_around_long_match(client) -> None:
    token = token_for(client, "search-snippet@example.com")
    body_text = ("filler text " * 40) + "LongNeedle marker " + ("more filler " * 40)
    import_markdown(
        client,
        token,
        "# Long notes\n\n## 2026-11-02 — Long section\n\n" + body_text + "\n",
    )

    result = search(client, token, "LongNeedle")["timeline"]["results"][0]

    assert "LongNeedle" in result["snippet"]
    assert len(result["snippet"]) <= 200
    assert len(result["snippet"]) < len(body_text)
