"""Parser for the conversations.json shape in a ChatGPT data export."""

import json
from datetime import UTC, datetime
from typing import Any

from personal_ai_life_os.parsers.base import ParsedItem

PARSER_VERSION = "chatgpt-export-v1"
SUPPORTED_SHAPES = "an array of conversation objects with a mapping of message nodes"


class UnsupportedExportError(ValueError):
    """The selected JSON file is not a supported ChatGPT export."""


def _timestamp(value: Any) -> datetime | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        if abs(seconds) > 100_000_000_000:
            seconds /= 1000
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if isinstance(parts, list):
        values: list[str] = []
        for part in parts:
            if isinstance(part, str):
                values.append(part)
            elif isinstance(part, dict):
                value = part.get("text")
                if isinstance(value, str):
                    values.append(value)
        return "\n".join(value for value in values if value.strip()).strip()
    text = content.get("text")
    return text.strip() if isinstance(text, str) else ""


def parse_chatgpt_export(
    payload: bytes | str,
    selected_conversation_ids: set[str] | None = None,
) -> list[ParsedItem]:
    """Parse user-selected conversations and only human-readable user/assistant messages."""
    try:
        decoded = payload.decode("utf-8-sig") if isinstance(payload, bytes) else payload
        document = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UnsupportedExportError("The selected file is not valid UTF-8 ChatGPT export JSON.") from error

    conversations = document.get("conversations") if isinstance(document, dict) else document
    if not isinstance(conversations, list):
        raise UnsupportedExportError(f"Unsupported ChatGPT export shape; expected {SUPPORTED_SHAPES}.")

    parsed: list[ParsedItem] = []
    available_ids: set[str] = set()
    for conversation_index, conversation in enumerate(conversations):
        if not isinstance(conversation, dict):
            continue
        conversation_id = str(
            conversation.get("conversation_id") or conversation.get("id") or f"conversation-{conversation_index + 1}"
        )
        available_ids.add(conversation_id)
        if selected_conversation_ids is not None and conversation_id not in selected_conversation_ids:
            continue

        title = str(conversation.get("title") or "Untitled conversation").strip()[:500]
        mapping = conversation.get("mapping")
        if not isinstance(mapping, dict):
            messages = conversation.get("messages")
            if not isinstance(messages, list):
                raise UnsupportedExportError(
                    f"Conversation {conversation_id!r} has no supported message mapping."
                )
            message_nodes = [(str(index), item) for index, item in enumerate(messages)]
        else:
            message_nodes = list(mapping.items())

        for node_key, node in message_nodes:
            if not isinstance(node, dict):
                continue
            message = node.get("message", node)
            if not isinstance(message, dict):
                continue
            author = message.get("author")
            role = author.get("role") if isinstance(author, dict) else message.get("role")
            if role not in {"user", "assistant"}:
                continue
            text = _text_from_content(message.get("content", message.get("text")))
            if not text:
                continue
            message_id = str(message.get("id") or node_key)
            occurred_at = _timestamp(
                message.get("create_time") or message.get("created_at") or message.get("timestamp")
            )
            parsed.append(
                ParsedItem(
                    external_id=f"conversation:{conversation_id}:message:{message_id}",
                    kind="chat_message",
                    title=title,
                    content_text=text,
                    occurred_at=occurred_at,
                    source_timezone="UTC" if occurred_at is not None else None,
                    source_locator={
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "role": role,
                    },
                    metadata={
                        "role": role,
                        "date_precision": "second" if occurred_at is not None else "unknown",
                        "source_timezone_known": occurred_at is not None,
                    },
                )
            )

    if selected_conversation_ids is not None:
        missing = selected_conversation_ids - available_ids
        if missing:
            missing_ids = ", ".join(sorted(missing))
            raise UnsupportedExportError(f"Selected conversation IDs were not found: {missing_ids}.")
    return parsed


def select_chatgpt_export(payload: bytes | str, selected_conversation_ids: set[str]) -> bytes:
    """Create a minimized export containing only explicitly selected conversations."""
    try:
        decoded = payload.decode("utf-8-sig") if isinstance(payload, bytes) else payload
        document = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UnsupportedExportError("The selected file is not valid UTF-8 ChatGPT export JSON.") from error
    conversations = document.get("conversations") if isinstance(document, dict) else document
    if not isinstance(conversations, list):
        raise UnsupportedExportError(f"Unsupported ChatGPT export shape; expected {SUPPORTED_SHAPES}.")

    available: dict[str, dict[str, Any]] = {}
    for index, conversation in enumerate(conversations):
        if not isinstance(conversation, dict):
            continue
        conversation_id = str(
            conversation.get("conversation_id") or conversation.get("id") or f"conversation-{index + 1}"
        )
        available[conversation_id] = conversation
    missing = selected_conversation_ids - available.keys()
    if missing:
        raise UnsupportedExportError(
            "Selected conversation IDs were not found: " + ", ".join(sorted(missing)) + "."
        )
    selected = [available[conversation_id] for conversation_id in sorted(selected_conversation_ids)]
    if isinstance(document, dict):
        minimized = {key: value for key, value in document.items() if key != "conversations"}
        minimized["conversations"] = selected
    else:
        minimized = selected
    return json.dumps(minimized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def list_chatgpt_conversations(payload: bytes | str) -> list[dict[str, Any]]:
    """Return safe conversation metadata for a local CLI preview; never include message text."""
    try:
        decoded = payload.decode("utf-8-sig") if isinstance(payload, bytes) else payload
        document = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UnsupportedExportError("The selected file is not valid UTF-8 ChatGPT export JSON.") from error
    conversations = document.get("conversations") if isinstance(document, dict) else document
    if not isinstance(conversations, list):
        raise UnsupportedExportError(f"Unsupported ChatGPT export shape; expected {SUPPORTED_SHAPES}.")

    result: list[dict[str, Any]] = []
    for index, conversation in enumerate(conversations):
        if not isinstance(conversation, dict):
            continue
        conversation_id = str(
            conversation.get("conversation_id") or conversation.get("id") or f"conversation-{index + 1}"
        )
        mapping = conversation.get("mapping")
        nodes = mapping.values() if isinstance(mapping, dict) else conversation.get("messages", [])
        message_count = 0
        if isinstance(nodes, (list, type({}.values()))):
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                message = node.get("message", node)
                author = message.get("author") if isinstance(message, dict) else None
                role = author.get("role") if isinstance(author, dict) else None
                if role in {"user", "assistant"}:
                    message_count += 1
        result.append(
            {
                "id": conversation_id,
                "title": str(conversation.get("title") or "Untitled conversation"),
                "created_at": _timestamp(conversation.get("create_time")),
                "message_count": message_count,
            }
        )
    return result
