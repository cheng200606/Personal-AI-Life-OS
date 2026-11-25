import json
from datetime import UTC, datetime
from io import BytesIO

from docx import Document
from pypdf import PdfWriter
from sqlalchemy import select
from test_reviews_account import import_memory, token_for

from personal_ai_life_os.models import GraphEntity, GraphEvidence
from personal_ai_life_os.parsers.document import UnsupportedDocumentError, parse_document
from personal_ai_life_os.parsers.generic_chat import parse_generic_chat


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _create_source(client, token: str, kind: str, name: str) -> str:
    response = client.post(
        "/api/v1/sources",
        headers=_headers(token),
        json={"kind": kind, "name": name, "selected_scope": {}},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_generic_chat_parses_claude_like_export() -> None:
    payload = [
        {
            "uuid": "conv-1",
            "name": "Synthetic Claude chat",
            "created_at": "2026-11-20T10:00:00Z",
            "chat_messages": [
                {
                    "uuid": "m-1",
                    "sender": "human",
                    "text": "We agreed to use Postgres.",
                    "created_at": "2026-11-20T10:00:00Z",
                },
                {
                    "uuid": "m-2",
                    "sender": "assistant",
                    "text": "I will document the migration.",
                    "created_at": "2026-11-20T10:01:00Z",
                },
                {"uuid": "m-3", "sender": "system", "text": "ignore this"},
            ],
        }
    ]
    items = parse_generic_chat(json.dumps(payload), "claude.json")
    assert len(items) == 2
    assert [item.metadata["role"] for item in items] == ["user", "assistant"]
    assert items[0].occurred_at == datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    assert items[0].source_locator["conversation_id"] == "conv-1"


def test_generic_chat_parses_jsonl_and_gemini_like_shapes() -> None:
    lines = "\n".join(
        [
            json.dumps({"role": "user", "content": "Plan the release.", "timestamp": 1763632800}),
            json.dumps({"role": "assistant", "content": "I will prepare the checklist."}),
        ]
    )
    items = parse_generic_chat(lines, "export.jsonl")
    assert len(items) == 2
    assert items[0].title == "export.jsonl"
    assert items[0].occurred_at is not None

    gemini = {
        "conversations": [
            {
                "id": "gem-1",
                "title": "Gemini synthetic",
                "turns": [
                    {"role": "user", "content": {"parts": ["Summarize the project."]}},
                    {"role": "model", "content": {"parts": [{"text": "Here is the summary."}]}},
                ],
            }
        ]
    }
    parsed = parse_generic_chat(json.dumps(gemini), "gemini.json")
    assert len(parsed) == 2
    assert parsed[1].metadata["role"] == "assistant"


def test_document_parses_txt_markdown_and_docx() -> None:
    txt = parse_document(b"A plain note.\n\nA second line.", "note.txt")
    assert len(txt) == 1
    assert txt[0].kind == "document"
    assert txt[0].source_locator["line_end"] == 3

    markdown = parse_document(b"## 2026-11-20 Project\n\nDecision text.", "notes.md")
    assert markdown[0].kind == "markdown_section"
    assert markdown[0].metadata["date_precision"] == "day"

    buffer = BytesIO()
    document = Document()
    document.add_paragraph("DOCX synthetic paragraph.")
    document.save(buffer)
    docx_items = parse_document(buffer.getvalue(), "note.docx")
    assert len(docx_items) == 1
    assert "DOCX synthetic paragraph." in docx_items[0].content_text


def test_scanned_pdf_reports_no_extractable_text() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = BytesIO()
    writer.write(buffer)
    try:
        parse_document(buffer.getvalue(), "blank.pdf")
    except UnsupportedDocumentError as error:
        assert "Scanned PDFs" in str(error)
    else:
        raise AssertionError("A blank/scanned PDF must report unsupported text extraction.")


def test_chat_export_and_document_import_are_idempotent(client) -> None:
    token = token_for(client, "graph-inputs@example.com")
    chat_source = _create_source(client, token, "chat_export", "Claude export")
    payload = json.dumps(
        [
            {
                "id": "conv-1",
                "title": "Synthetic chat",
                "messages": [
                    {"id": "m-1", "role": "user", "content": "We chose Postgres."},
                    {"id": "m-2", "role": "assistant", "content": "Noted."},
                ],
            }
        ]
    ).encode()
    first = client.post(
        "/api/v1/sources/" + chat_source + "/imports",
        headers=_headers(token),
        files={"file": ("chat.json", payload, "application/json")},
    )
    assert first.status_code == 201, first.text
    assert first.json()["sync_run"]["items_created"] == 2
    second = client.post(
        "/api/v1/sources/" + chat_source + "/imports",
        headers=_headers(token),
        files={"file": ("chat.json", payload, "application/json")},
    )
    assert second.status_code == 201, second.text
    assert second.json()["sync_run"]["items_created"] == 0
    assert second.json()["sync_run"]["items_duplicate"] == 2

    document_source = _create_source(client, token, "document", "Local notes")
    imported = client.post(
        "/api/v1/sources/" + document_source + "/imports",
        headers=_headers(token),
        files={"file": ("notes.txt", b"A synthetic local note.", "text/plain")},
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["sync_run"]["items_created"] == 1


def test_cloud_consent_and_revoke_marks_evidence_unavailable(client) -> None:
    token = token_for(client, "graph-consent@example.com")
    source_id, item_ids = import_memory(client, token)
    owner_id = client.get("/api/v1/auth/me", headers=_headers(token)).json()["id"]
    version = client.app.state.settings.graph_cloud_consent_version

    mismatch = client.patch(
        "/api/v1/sources/" + source_id + "/cloud-consent",
        headers=_headers(token),
        json={"enabled": True, "consent_version": "old-version"},
    )
    assert mismatch.status_code == 409

    enabled = client.patch(
        "/api/v1/sources/" + source_id + "/cloud-consent",
        headers=_headers(token),
        json={"enabled": True, "consent_version": version},
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["cloud_consent_at"] is not None
    assert enabled.json()["cloud_consent_version"] == version

    disabled = client.patch(
        "/api/v1/sources/" + source_id + "/cloud-consent",
        headers=_headers(token),
        json={"enabled": False, "consent_version": version},
    )
    assert disabled.status_code == 200
    assert disabled.json()["cloud_consent_at"] is None

    with client.app.state.session_factory() as session:
        entity = GraphEntity(
            owner_id=owner_id,
            entity_type="project",
            name="Consent evidence project",
            normalized_name="consent evidence project",
        )
        session.add(entity)
        session.flush()
        session.add(
            GraphEvidence(
                owner_id=owner_id,
                entity_id=entity.id,
                source_id=source_id,
                source_item_id=item_ids[0],
                quote="Synthetic evidence.",
                locator={},
                confidence=0.9,
            )
        )
        session.commit()
        evidence_id = session.scalar(select(GraphEvidence.id))

    revoked = client.post(
        "/api/v1/sources/" + source_id + "/revoke", headers=_headers(token)
    )
    assert revoked.status_code == 200
    with client.app.state.session_factory() as session:
        evidence = session.get(GraphEvidence, evidence_id)
        assert evidence is not None
        assert evidence.availability == "revoked"

    deleted = client.delete("/api/v1/sources/" + source_id, headers=_headers(token))
    assert deleted.status_code == 204
    with client.app.state.session_factory() as session:
        assert session.get(GraphEvidence, evidence_id) is None
