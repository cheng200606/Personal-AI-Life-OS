"""A line-addressable parser for user-selected Markdown memory files."""

import re
import unicodedata
from datetime import UTC, date, datetime, time

from personal_ai_life_os.parsers.base import ParsedItem

PARSER_VERSION = "memory-markdown-v1"
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
DATE_RE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return slug[:100] or "section"


def _heading_date(value: str) -> date | None:
    match = DATE_RE.search(value)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def parse_memory_markdown(content: str, filename: str = "memory.md") -> list[ParsedItem]:
    """Split a Markdown document into heading sections and retain exact line ranges."""
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.splitlines()
    headings = [
        (index, len(match.group(1)), match.group(2).strip())
        for index, line in enumerate(lines)
        if (match := HEADING_RE.match(line))
    ]
    if not lines or not normalized.strip():
        return []

    # A document title is not a useful event when it contains nested sections.
    section_headings = [item for item in headings if item[1] >= 2] or headings
    if not section_headings:
        section_headings = [(0, 1, filename)]

    parsed: list[ParsedItem] = []
    for section_index, (start_index, level, heading) in enumerate(section_headings):
        end_index = len(lines)
        for next_index, next_level, _ in section_headings[section_index + 1 :]:
            if next_level <= level:
                end_index = next_index
                break
        while end_index > start_index and not lines[end_index - 1].strip():
            end_index -= 1
        section_lines = lines[start_index:end_index]
        text = "\n".join(section_lines).strip()
        if not text:
            continue

        occurred_date = _heading_date(heading)
        occurred_at = (
            datetime.combine(occurred_date, time.min, tzinfo=UTC) if occurred_date is not None else None
        )
        external_id = f"section:{section_index + 1}:{_slug(heading)}"
        parsed.append(
            ParsedItem(
                external_id=external_id,
                kind="markdown_section",
                title=heading,
                content_text=text,
                occurred_at=occurred_at,
                source_timezone=None,
                source_locator={
                    "file": filename,
                    "line_start": start_index + 1,
                    "line_end": end_index,
                    "heading": heading,
                },
                metadata={
                    "date_precision": "day" if occurred_date is not None else "unknown",
                    "source_timezone_known": False,
                },
            )
        )
    return parsed
