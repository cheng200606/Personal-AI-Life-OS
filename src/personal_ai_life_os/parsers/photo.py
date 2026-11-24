"""Sanitize selected photos and extract searchable OCR text."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytesseract
from PIL import Image, ImageOps, UnidentifiedImageError

from personal_ai_life_os.parsers.base import ParsedItem

PARSER_VERSION = "photo-ocr-v1"
MAX_IMAGE_PIXELS = 40_000_000
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


class UnsupportedPhotoError(ValueError):
    """The uploaded file is not a supported, safe raster image."""


@dataclass(slots=True)
class ProcessedPhoto:
    item: ParsedItem
    sanitized_bytes: bytes
    content_type: str


def _exif_datetime(image: Image.Image) -> tuple[datetime | None, str | None, str | None]:
    try:
        exif = image.getexif()
    except (OSError, ValueError):
        return None, None, None
    local = exif.get(36867) or exif.get(36868) or exif.get(306)
    if not isinstance(local, str):
        return None, None, None
    try:
        value = datetime.strptime(local.strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None, None, None
    offset = exif.get(36881) or exif.get(36880)
    if isinstance(offset, str):
        try:
            sign = -1 if offset.startswith("-") else 1
            hours, minutes = (int(part) for part in offset[1:].split(":"))
            zone = timezone(sign * timedelta(hours=hours, minutes=minutes))
            return value.replace(tzinfo=zone), offset, value.isoformat()
        except (ValueError, IndexError):
            pass
    return None, None, value.isoformat()


def process_photo(
    payload: bytes,
    filename: str,
    *,
    captured_at: datetime | None = None,
    source_timezone: str | None = None,
) -> ProcessedPhoto:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedPhotoError("Choose a JPEG, PNG, or WebP image.")
    try:
        with Image.open(BytesIO(payload)) as opened:
            if opened.format not in {"JPEG", "PNG", "WEBP"}:
                raise UnsupportedPhotoError("Choose a JPEG, PNG, or WebP image.")
            if opened.width * opened.height > MAX_IMAGE_PIXELS:
                raise UnsupportedPhotoError("This image exceeds the supported 40 megapixel limit.")
            exif_time, exif_zone, local_time = _exif_datetime(opened)
            oriented = ImageOps.exif_transpose(opened)
            output = BytesIO()
            if suffix == ".png":
                image = oriented.convert("RGBA") if "A" in oriented.getbands() else oriented.convert("RGB")
                image.save(output, format="PNG", optimize=True)
                media_type = "image/png"
            elif suffix == ".webp":
                image = oriented.convert("RGBA") if "A" in oriented.getbands() else oriented.convert("RGB")
                image.save(output, format="WEBP", quality=92, method=4)
                media_type = "image/webp"
            else:
                image = oriented.convert("RGB")
                image.save(output, format="JPEG", quality=92, optimize=True)
                media_type = "image/jpeg"
    except UnsupportedPhotoError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise UnsupportedPhotoError("The selected file is not a valid supported image.") from error

    sanitized = output.getvalue()
    occurred_at = captured_at or exif_time
    ocr_status = "unavailable"
    extracted_text = ""
    if shutil.which("tesseract"):
        try:
            extracted_text = pytesseract.image_to_string(image, lang="eng+chi_sim", timeout=20).strip()
            ocr_status = "extracted" if extracted_text else "no_text"
        except (pytesseract.TesseractError, OSError, RuntimeError, ValueError):
            ocr_status = "failed"

    basename = Path(filename).name[:180] or "photo"
    raw_digest = sha256(payload).hexdigest()
    item = ParsedItem(
        external_id="photo:" + raw_digest,
        kind="photo",
        title=basename,
        content_text=extracted_text,
        occurred_at=occurred_at,
        source_timezone=source_timezone or exif_zone,
        source_locator={"filename": basename, "media_type": media_type},
        metadata={
            "ocr_status": ocr_status,
            "date_precision": "second" if occurred_at else ("local_second" if local_time else "unknown"),
            "capture_local": local_time,
            "source_timezone_known": bool(source_timezone or exif_zone),
            "location_metadata_removed": True,
            "sanitized": True,
            "width": image.width,
            "height": image.height,
            "media_type": media_type,
        },
    )
    return ProcessedPhoto(item=item, sanitized_bytes=sanitized, content_type=media_type)
