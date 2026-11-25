"""Local text extraction for Markdown, plain text, PDF, and DOCX documents."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from docx import Document
from pypdf import PdfReader

from personal_ai_life_os.parsers.base import ParsedItem
from personal_ai_life_os.parsers.memory_markdown import parse_memory_markdown

PARSER_VERSION = "local-document-v1"
SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".pdf", ".docx"}


class UnsupportedDocumentError(ValueError):
    """The selected document cannot be parsed locally."""


def _decode_text(payload: bytes) -> str:
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise UnsupportedDocumentError("The document must be UTF-8 encoded.") from error


def _plain_text(payload: bytes, filename: str) -> list[ParsedItem]:
    text = _decode_text(payload).replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise UnsupportedDocumentError("The selected text document is empty.")
    return [
        ParsedItem(
            external_id="document:1",
            kind="document",
            title=Path(filename).stem or filename,
            content_text=text.strip(),
            source_locator={"file": filename, "line_start": 1, "line_end": len(text.splitlines())},
            metadata={"media_type": "text/plain", "date_precision": "unknown"},
        )
    ]


def _pdf(payload: bytes, filename: str) -> list[ParsedItem]:
    try:
        reader = PdfReader(BytesIO(payload))
    except Exception as error:
        raise UnsupportedDocumentError("The PDF could not be read locally.") from error
    if reader.is_encrypted:
        raise UnsupportedDocumentError("Encrypted PDFs are not supported.")
    items: list[ParsedItem] = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except Exception as error:
            raise UnsupportedDocumentError(
                f"Page {page_number} could not be extracted as text."
            ) from error
        if not text:
            continue
        items.append(
            ParsedItem(
                external_id=f"document:page:{page_number}",
                kind="document_page",
                title=(Path(filename).stem or filename) + f" · page {page_number}",
                content_text=text,
                source_locator={
                    "file": filename,
                    "page": page_number,
                    "page_count": len(reader.pages),
                },
                metadata={"media_type": "application/pdf", "date_precision": "unknown"},
            )
        )
    if not items:
        raise UnsupportedDocumentError(
            "No extractable text was found. Scanned PDFs need OCR, which this version does not support."
        )
    return items


def _docx(payload: bytes, filename: str) -> list[ParsedItem]:
    try:
        document = Document(BytesIO(payload))
    except Exception as error:
        raise UnsupportedDocumentError("The DOCX file could not be read locally.") from error
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    if not paragraphs:
        raise UnsupportedDocumentError("The DOCX file contains no extractable paragraphs.")
    return [
        ParsedItem(
            external_id="document:1",
            kind="document",
            title=Path(filename).stem or filename,
            content_text="\n\n".join(paragraphs),
            source_locator={
                "file": filename,
                "paragraph_start": 1,
                "paragraph_end": len(paragraphs),
            },
            metadata={"media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        )
    ]


def parse_document(payload: bytes, filename: str) -> list[ParsedItem]:
    suffix = Path(filename).suffix.lower()
    if suffix in {".md", ".markdown"}:
        return parse_memory_markdown(_decode_text(payload), filename)
    if suffix == ".txt":
        return _plain_text(payload, filename)
    if suffix == ".pdf":
        return _pdf(payload, filename)
    if suffix == ".docx":
        return _docx(payload, filename)
    raise UnsupportedDocumentError(
        "Choose a Markdown, TXT, text-based PDF, or DOCX document."
    )
