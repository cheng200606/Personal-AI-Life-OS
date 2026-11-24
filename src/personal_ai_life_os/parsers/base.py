"""Shared parser result types."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ParsedItem:
    external_id: str
    kind: str
    title: str
    content_text: str
    occurred_at: datetime | None = None
    source_timezone: str | None = None
    source_locator: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
