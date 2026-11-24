import json
from pathlib import Path

import pytest

from personal_ai_life_os.parsers.chatgpt_export import (
    UnsupportedExportError,
    list_chatgpt_conversations,
    parse_chatgpt_export,
)
from personal_ai_life_os.parsers.memory_markdown import parse_memory_markdown

FIXTURES = Path(__file__).parents[1] / "fixtures" / "synthetic"


def test_memory_parser_preserves_section_lines_and_unknown_dates() -> None:
    content = (FIXTURES / "memory.md").read_text(encoding="utf-8")

    items = parse_memory_markdown(content, "memory.md")

    assert len(items) == 3
    assert items[0].title == "2026-11-16 — Research setup"
    assert items[0].source_locator["line_start"] == 3
    assert items[0].source_locator["line_end"] == 7
    assert items[0].occurred_at is not None
    assert items[2].occurred_at is None
    assert items[2].metadata["date_precision"] == "unknown"


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_memory_parser_handles_empty_documents_and_windows_newlines(newline: str) -> None:
    content = newline.join(["# Notes", "", "## 2026-11-20 Follow-up", "", "- Keep the source line."])

    items = parse_memory_markdown(content, "memory.md")

    assert len(items) == 1
    assert items[0].source_locator["line_start"] == 3
    assert items[0].source_locator["line_end"] == 5
    assert parse_memory_markdown("", "empty.md") == []


def test_chatgpt_parser_filters_to_selected_conversations_and_keeps_locator() -> None:
    payload = (FIXTURES / "conversations.json").read_bytes()

    items = parse_chatgpt_export(payload, {"synthetic-conversation-001"})

    assert len(items) == 2
    assert all(item.source_locator["conversation_id"] == "synthetic-conversation-001" for item in items)
    assert items[0].occurred_at is not None
    assert "message-001" in items[0].external_id


def test_chatgpt_preview_does_not_return_message_bodies() -> None:
    payload = (FIXTURES / "conversations.json").read_bytes()

    conversations = list_chatgpt_conversations(payload)

    assert len(conversations) == 2
    assert conversations[0]["message_count"] == 2
    assert "content_text" not in conversations[0]


def test_chatgpt_parser_rejects_unknown_shape_and_missing_selection() -> None:
    with pytest.raises(UnsupportedExportError, match="Unsupported ChatGPT export shape"):
        parse_chatgpt_export(json.dumps({"unexpected": []}))
    with pytest.raises(UnsupportedExportError, match="not found"):
        parse_chatgpt_export((FIXTURES / "conversations.json").read_bytes(), {"does-not-exist"})
