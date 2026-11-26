"""Bounded parser for user-selected single-event iCalendar snapshots."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from icalendar import Calendar

from personal_ai_life_os.parsers.base import ParsedItem

PARSER_VERSION = "ics-v1"
MAX_CALENDAR_BYTES = 5 * 1024 * 1024
MAX_EVENTS = 1_000
MAX_PROPERTIES_PER_EVENT = 200
MAX_PROPERTY_CHARS = 20_000
MAX_TEXT_CHARS = 50_000
UNSUPPORTED_RECURRENCE_PROPERTIES = {"RRULE", "RDATE", "EXDATE", "RECURRENCE-ID"}


class UnsupportedCalendarError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CalendarPreview:
    items: tuple[ParsedItem, ...]
    skipped_recurring: int


def _bounded_text(value: object, *, field: str) -> str:
    text = str(value) if value is not None else ""
    if len(text) > MAX_TEXT_CHARS:
        raise UnsupportedCalendarError(f"{field} exceeds the {MAX_TEXT_CHARS} character limit.")
    return text


def _external_id(uid: str) -> str:
    if len(uid) <= 512:
        return uid
    return "sha256:" + hashlib.sha256(uid.encode("utf-8")).hexdigest()


def _localize(value: datetime, zone: ZoneInfo) -> tuple[datetime, bool]:
    localized = value.replace(tzinfo=zone, fold=0)
    roundtrip = localized.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    if roundtrip != value:
        raise UnsupportedCalendarError("A floating calendar time does not exist in the selected timezone.")
    ambiguous = (
        value.replace(tzinfo=zone, fold=0).utcoffset()
        != value.replace(tzinfo=zone, fold=1).utcoffset()
    )
    return localized.astimezone(UTC), ambiguous


def _parse_datetime(value: object, *, zone: ZoneInfo, field: str) -> tuple[datetime, dict]:
    if isinstance(value, datetime):
        raw: datetime = value
        if raw.tzinfo is not None and raw.utcoffset() is not None:
            zone_key = getattr(raw.tzinfo, "key", None)
            ambiguous = False
            if zone_key:
                zone = ZoneInfo(zone_key)
                naive = raw.replace(tzinfo=None)
                if naive.replace(tzinfo=zone, fold=0).astimezone(UTC).astimezone(zone).replace(tzinfo=None) != naive:
                    raise UnsupportedCalendarError("A zoned calendar time does not exist in its timezone.")
                ambiguous = (
                    naive.replace(tzinfo=zone, fold=0).utcoffset()
                    != naive.replace(tzinfo=zone, fold=1).utcoffset()
                )
            return raw.astimezone(UTC), {
                "all_day": False,
                "floating": False,
                "dst_ambiguous": ambiguous,
                "original_tzid": str(zone_key or "UTC"),
            }
        normalized, ambiguous = _localize(raw, zone)
        return normalized, {
            "all_day": False,
            "floating": True,
            "dst_ambiguous": ambiguous,
            "original_tzid": None,
        }
    if isinstance(value, date):
        normalized = datetime.combine(value, time.min, tzinfo=zone).astimezone(UTC)
        return normalized, {
            "all_day": True,
            "floating": False,
            "dst_ambiguous": False,
            "original_tzid": None,
            "date_value": value.isoformat(),
        }
    raise UnsupportedCalendarError(f"{field} must be an iCalendar DATE or DATE-TIME value.")


def _component_value(event, name: str) -> object | None:
    try:
        return event.decoded(name) if event.get(name) is not None else None
    except (TypeError, ValueError, KeyError) as error:
        raise UnsupportedCalendarError(f"{name} is not a valid iCalendar value.") from error


def _raw_tzid(event, name: str) -> str | None:
    prop = event.get(name)
    if prop is None:
        return None
    value = prop.params.get("TZID") if hasattr(prop, "params") else None
    return str(value) if value else None


def parse_calendar(payload: bytes, *, user_timezone: str = "UTC") -> CalendarPreview:
    if len(payload) > MAX_CALENDAR_BYTES:
        raise UnsupportedCalendarError("The calendar file exceeds the 5 MB upload limit.")
    try:
        text = payload.decode("utf-8-sig")
        zone = ZoneInfo(user_timezone)
    except (UnicodeDecodeError, KeyError) as error:
        raise UnsupportedCalendarError("The calendar must be UTF-8 encoded and use a valid IANA timezone.") from error

    try:
        calendar = Calendar.from_ical(text)
    except (TypeError, ValueError, KeyError) as error:
        raise UnsupportedCalendarError("The file is not a valid iCalendar calendar.") from error
    if isinstance(calendar, list):
        if len(calendar) != 1:
            raise UnsupportedCalendarError("Select one iCalendar calendar per upload.")
        calendar = calendar[0]
    if getattr(calendar, "name", None) != "VCALENDAR":
        raise UnsupportedCalendarError("The file does not contain a VCALENDAR component.")

    events = [component for component in calendar.walk() if component.name == "VEVENT"]
    if not events:
        raise UnsupportedCalendarError("The calendar does not contain any VEVENT entries.")
    if len(events) > MAX_EVENTS:
        raise UnsupportedCalendarError(f"The calendar exceeds the {MAX_EVENTS} event limit.")

    parsed: list[ParsedItem] = []
    seen_uids: set[str] = set()
    skipped_recurring = 0
    calendar_method = str(calendar.get("METHOD", "")).upper()
    for index, event in enumerate(events):
        if len(list(event.property_items())) > MAX_PROPERTIES_PER_EVENT:
            raise UnsupportedCalendarError("A VEVENT contains too many properties.")
        for _, value in event.property_items():
            if len(str(value)) > MAX_PROPERTY_CHARS:
                raise UnsupportedCalendarError("A VEVENT property exceeds the supported length.")

        uid = _bounded_text(event.get("UID"), field="UID").strip()
        if not uid:
            raise UnsupportedCalendarError("Every VEVENT must include a UID.")
        if uid in seen_uids:
            raise UnsupportedCalendarError("A calendar snapshot contains duplicate event UIDs.")
        seen_uids.add(uid)

        try:
            sequence = int(event.get("SEQUENCE", 0))
        except (TypeError, ValueError) as error:
            raise UnsupportedCalendarError("SEQUENCE must be a non-negative integer.") from error
        if sequence < 0:
            raise UnsupportedCalendarError("SEQUENCE must be a non-negative integer.")

        unsupported_recurrence = any(event.get(name) is not None for name in UNSUPPORTED_RECURRENCE_PROPERTIES)
        status = str(event.get("STATUS", "CONFIRMED")).upper()
        cancelled = calendar_method == "CANCEL" or str(event.get("METHOD", "")).upper() == "CANCEL" or status == "CANCELLED"
        start_value = _component_value(event, "DTSTART")
        if start_value is None and not cancelled:
            raise UnsupportedCalendarError("Every active VEVENT must include DTSTART.")
        if start_value is None:
            occurred_at = None
            time_metadata: dict = {
                "all_day": False,
                "floating": False,
                "dst_ambiguous": False,
                "original_tzid": None,
            }
            source_timezone = None
        else:
            occurred_at, time_metadata = _parse_datetime(start_value, zone=zone, field="DTSTART")
            original_tzid = _raw_tzid(event, "DTSTART")
            if original_tzid:
                time_metadata["original_tzid"] = original_tzid
            source_timezone = original_tzid or (
                user_timezone if time_metadata["all_day"] or time_metadata["floating"] else "UTC"
            )

        end_value = _component_value(event, "DTEND")
        end_at = None
        if end_value is not None:
            end_at, end_metadata = _parse_datetime(end_value, zone=zone, field="DTEND")
            if occurred_at is not None and end_at < occurred_at:
                raise UnsupportedCalendarError("DTEND cannot be earlier than DTSTART.")
            if end_metadata.get("all_day") != time_metadata.get("all_day"):
                raise UnsupportedCalendarError("DTSTART and DTEND must use the same value type.")
        if unsupported_recurrence:
            skipped_recurring += 1

        summary = _bounded_text(event.get("SUMMARY"), field="SUMMARY").strip() or "(Untitled event)"
        description = _bounded_text(event.get("DESCRIPTION"), field="DESCRIPTION").strip()
        location = _bounded_text(event.get("LOCATION"), field="LOCATION").strip()
        content_parts = [part for part in (description, f"Location: {location}" if location else "") if part]
        metadata = {
            **time_metadata,
            "ics_uid": uid,
            "ics_sequence": sequence,
            "ics_status": "cancelled" if cancelled else "confirmed",
            "ics_unsupported_recurrence": unsupported_recurrence,
            "event_end_at": end_at.isoformat() if end_at else None,
            "location": location or None,
        }
        parsed.append(
            ParsedItem(
                external_id=_external_id(uid),
                kind="calendar_event",
                title=summary[:500],
                content_text="\n\n".join(content_parts),
                occurred_at=occurred_at,
                source_timezone=source_timezone,
                source_locator={"uid": uid, "event_index": index},
                metadata=metadata,
            )
        )
    return CalendarPreview(items=tuple(parsed), skipped_recurring=skipped_recurring)
