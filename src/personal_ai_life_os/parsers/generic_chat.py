"""Best-effort parser for common chat export shapes beyond ChatGPT."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from personal_ai_life_os.parsers.base import ParsedItem

PARSER_VERSION = "generic-chat-v1"
MESSAGE_KEYS = ("messages", "chat_messages", "turns", "dialogue", "conversation", "items")
CONVERSATION_KEYS = ("conversations", "chats", "threads", "data")
ROLE_MAP = {
    "user": "user",
    "human": "user",
    "me": "user",
    "customer": "user",
    "assistant": "assistant",
    "ai": "assistant",
    "bot": "assistant",
    "model": "assistant",
    "claude": "assistant",
    "gemini": "assistant",
}


class UnsupportedChatExportError(ValueError):
    """The selected file is not a supported generic chat export."""


def _decode(payload: bytes | str) -> str:
    if isinstance(payload, str):
        return payload
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise UnsupportedChatExportError("The chat export must be UTF-8 encoded.") from error


def _load(payload: bytes | str, filename: str) -> Any:
    text = _decode(payload)
    if filename.lower().endswith(".jsonl"):
        objects: list[Any] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                objects.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise UnsupportedChatExportError("The selected JSONL file contains invalid JSON.") from error
        return objects
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise UnsupportedChatExportError("The selected file is not valid chat export JSON.") from error


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


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "content", "value", "body"):
            inner = value.get(key)
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
        parts = value.get("parts")
        if isinstance(parts, list):
            values = []
            for part in parts:
                if isinstance(part, str):
                    values.append(part)
                elif isinstance(part, dict) and isinstance(part.get("text"), str):
                    values.append(part["text"])
            return "\n".join(value for value in values if value.strip()).strip()
    return ""


def _message_text(message: dict[str, Any]) -> str:
    for key in ("text", "content", "message", "body", "value"):
        text = _text(message.get(key))
        if text:
            return text
    return ""


def _role(message: dict[str, Any]) -> str | None:
    raw = message.get("role") or message.get("sender") or message.get("from") or message.get("author")
    if isinstance(raw, dict):
        raw = raw.get("role") or raw.get("name")
    if not isinstance(raw, str):
        return None
    return ROLE_MAP.get(raw.strip().lower())


def _messages(conversation: dict[str, Any]) -> list[dict[str, Any]]:
    for key in MESSAGE_KEYS:
        value = conversation.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    mapping = conversation.get("mapping")
    if isinstance(mapping, dict):
        result: list[dict[str, Any]] = []
        for node in mapping.values():
            if not isinstance(node, dict):
                continue
            message = node.get("message", node)
            if isinstance(message, dict):
                result.append(message)
        return result
    return []


def _conversation_id(conversation: dict[str, Any], index: int) -> str:
    return str(
        conversation.get("conversation_id")
        or conversation.get("id")
        or conversation.get("uuid")
        or conversation.get("chat_id")
        or f"conversation-{index + 1}"
    )


def _title(conversation: dict[str, Any], fallback: str) -> str:
    return str(
        conversation.get("title")
        or conversation.get("name")
        or conversation.get("subject")
        or fallback
    ).strip()[:500]


def _conversations(document: Any, filename: str) -> list[dict[str, Any]]:
    if isinstance(document, list):
        if not document:
            return []
        conversation_markers = (*MESSAGE_KEYS, "mapping")
        if any(
            isinstance(item, dict) and any(key in item for key in conversation_markers)
            for item in document
        ):
            return [item for item in document if isinstance(item, dict)]
        return [{"title": filename, "messages": document}]
    if isinstance(document, dict):
        for key in CONVERSATION_KEYS:
            value = document.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [document]
    raise UnsupportedChatExportError("Unsupported chat export shape.")


def parse_generic_chat(payload: bytes | str, filename: str = "chat.json") -> list[ParsedItem]:
    """Parse common conversation/message shapes without assuming a provider."""
    document = _load(payload, filename)
    conversations = _conversations(document, filename)
    parsed: list[ParsedItem] = []
    for conversation_index, conversation in enumerate(conversations):
        conversation_id = _conversation_id(conversation, conversation_index)
        title = _title(conversation, filename)
        for message_index, message in enumerate(_messages(conversation)):
            role = _role(message)
            if role is None:
                continue
            content = _message_text(message)
            if not content:
                continue
            message_id = str(
                message.get("id")
                or message.get("uuid")
                or message.get("message_id")
                or f"message-{message_index + 1}"
            )
            occurred_at = _timestamp(
                message.get("created_at")
                or message.get("create_time")
                or message.get("timestamp")
                or message.get("updated_at")
                or message.get("date")
            )
            parsed.append(
                ParsedItem(
                    external_id=f"conversation:{conversation_id}:message:{message_id}",
                    kind="chat_message",
                    title=title,
                    content_text=content,
                    occurred_at=occurred_at,
                    source_timezone="UTC" if occurred_at is not None else None,
                    source_locator={
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "role": role,
                        "parser": PARSER_VERSION,
                    },
                    metadata={
                        "role": role,
                        "date_precision": "second" if occurred_at is not None else "unknown",
                        "source_timezone_known": occurred_at is not None,
                    },
                )
            )
    if not parsed:
        raise UnsupportedChatExportError(
            "No user/assistant messages were found. Expected conversations with messages or JSONL message objects."
        )
    return parsed
