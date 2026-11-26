"""Local-only iterator for large chat exports with explicit conversation IDs."""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from itertools import chain
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO

import ijson
from ijson.common import JSONError

from personal_ai_life_os.parsers.generic_chat import CONVERSATION_KEYS, MESSAGE_KEYS

MAX_EXPORT_BYTES = 1024 * 1024 * 1024
MAX_CONVERSATION_BYTES = 32 * 1024 * 1024
ID_KEYS = ("conversation_id", "id", "uuid", "chat_id")


class ChatExportError(ValueError):
    """An invalid, oversized, or ambiguous chat export."""


class ChatExportCancelled(Exception):
    """The caller canceled local parsing."""


class ExportReader:
    def __init__(
        self, stream: BinaryIO, progress: Callable[[int], None], canceled: Callable[[], bool],
    ):
        self.stream = stream
        self.progress = progress
        self.canceled = canceled

    def read(self, size: int) -> bytes:
        if self.canceled():
            raise ChatExportCancelled()
        result = self.stream.read(size)
        if self.stream.tell() > MAX_EXPORT_BYTES:
            raise ChatExportError("The chat export exceeds 1 GiB.")
        if size:
            self.progress(self.stream.tell())
        return result


def _conversation_objects(events, array_prefix: str, stream: BinaryIO) -> Iterator[dict]:
    item_prefix = f"{array_prefix}.item" if array_prefix else "item"
    start = None
    text_size = 0

    def bounded_events():
        nonlocal start, text_size
        for event in events:
            prefix, kind, value = event
            if prefix == item_prefix and kind == "start_map" and start is None:
                start = stream.tell()
                text_size = 0
            elif prefix == item_prefix and start is None:
                raise ChatExportError("Expected a conversation object inside the export array.")
            if start is not None:
                text_size += len(value) if isinstance(value, str) else 16
                if text_size > MAX_CONVERSATION_BYTES or stream.tell() - start > MAX_CONVERSATION_BYTES:
                    raise ChatExportError("One conversation exceeds the 32 MiB parser limit.")
                if prefix == item_prefix and kind == "end_map":
                    start = None
            yield event

    yield from ijson.items(bounded_events(), item_prefix)


def _read_records(
    path: Path, stream: BinaryIO, progress: Callable[[int], None], canceled: Callable[[], bool],
) -> Iterator[dict]:
    reader = ExportReader(stream, progress, canceled)
    if path.suffix.lower() == ".jsonl":
        while line := stream.readline(MAX_CONVERSATION_BYTES + 1):
            reader.read(0)
            progress(stream.tell())
            if len(line) > MAX_CONVERSATION_BYTES:
                raise ChatExportError("One JSONL record exceeds the 32 MiB parser limit.")
            if line.strip():
                yield json.loads(line)
        return

    events = iter(ijson.parse(reader, use_float=True))
    first = next(events, None)
    if first == ("", "start_array", None):
        yield from _conversation_objects(events, "", stream)
        return
    if first == ("", "start_map", None):
        for event in events:
            if event[0] in CONVERSATION_KEYS and event[1] == "start_array":
                yield from _conversation_objects(chain((event,), events), event[0], stream)
                return
        # A small single-conversation export has no array wrapper.
        if stream.tell() <= MAX_CONVERSATION_BYTES:
            stream.seek(0)
            yield json.loads(reader.read(MAX_CONVERSATION_BYTES).decode("utf-8-sig"))
            return
    raise ChatExportError("Expected a JSON/JSONL export containing conversation objects.")


def stream_conversations(
    path: Path,
    *,
    progress: Callable[[int], None] = lambda _: None,
    canceled: Callable[[], bool] = lambda: False,
) -> Iterator[tuple[str, dict]]:
    """Keep only one conversation in memory and reject unsafe positional IDs."""
    if path.stat().st_size > MAX_EXPORT_BYTES:
        raise ChatExportError("The chat export exceeds 1 GiB.")
    visited: set[str] = set()
    try:
        with path.open("rb") as stream:
            if stream.read(3) != b"\xef\xbb\xbf":
                stream.seek(0)
            for record in _read_records(path, stream, progress, canceled):
                if canceled():
                    raise ChatExportCancelled()
                if not isinstance(record, dict) or not (
                    isinstance(record.get("mapping"), dict)
                    or any(isinstance(record.get(key), list) for key in MESSAGE_KEYS)
                ):
                    raise ChatExportError("Expected a conversation with a message list or mapping.")
                identity = next((record[key] for key in ID_KEYS if record.get(key)), None)
                if not isinstance(identity, (int, str)) or isinstance(identity, bool):
                    raise ChatExportError("Each selectable conversation must have a stable ID.")
                conversation_id = str(identity)
                if not conversation_id.strip() or len(conversation_id) > 512 or conversation_id in visited:
                    raise ChatExportError("Conversation IDs must be unique, non-empty, and at most 512 characters.")
                visited.add(conversation_id)
                yield conversation_id, record
    except (JSONError, UnicodeError, json.JSONDecodeError, OverflowError) as error:
        raise ChatExportError("Invalid UTF-8 chat export JSON.") from error


@contextmanager
def stage_selected_conversations(
    records: Iterator[tuple[str, dict]], selected: set[str],
):
    """Validate the full input before releasing minimized conversations to ingestion."""
    with TemporaryDirectory(prefix="lifeos-selected-chat-") as directory:
        staged = []
        for identity, record in records:
            if identity not in selected:
                continue
            path = Path(directory) / f"{len(staged)}.json"
            path.write_text(
                json.dumps([{**record, "conversation_id": identity}], ensure_ascii=False),
                encoding="utf-8",
            )
            staged.append((identity, isinstance(record.get("mapping"), dict), path))
        yield staged
