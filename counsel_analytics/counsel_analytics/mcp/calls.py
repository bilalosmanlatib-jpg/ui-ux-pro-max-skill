"""Translate raw calendar/Teams meeting data into `CallRecord` domain models.

Attendance (`attendees`) comes from the Microsoft 365 calendar tools
(`outlook_calendar_search` / a calendar event read) — a hard fact, not
something an invoice narrative claims. `speaking_seconds` comes from a
Teams meeting transcript (`meeting-transcript:///` resource), fetched and
summed per speaker in-session, only when a transcript exists for that
call; most calls won't have one, and that's the normal case, not a
data-quality gap. Mirrors `mcp/m365.py`'s `_first()`-over-key-aliases
pattern.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dateutil import parser as dateutil_parser

from counsel_analytics.models import CallRecord

_START_KEYS = ("start", "startDateTime", "start_time")
_END_KEYS = ("end", "endDateTime", "end_time")
_SUBJECT_KEYS = ("subject", "title")
_ATTENDEES_KEYS = ("attendees", "participants")
_SPEAKING_KEYS = ("speakingSeconds", "speaking_seconds")
_EVENT_ID_KEYS = ("id", "eventId", "event_id")


def _first(raw: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in raw and raw[key] is not None:
            return raw[key]
    return None


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        if not value:
            raise ValueError("Call record is missing a start/end time")
        parsed = dateutil_parser.parse(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _attendee_identity(entry: Any) -> str | None:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return entry.get("email") or entry.get("address") or entry.get("name")
    return None


def parse_call_records(matter_id: str, raw_calls: list[dict]) -> list[CallRecord]:
    """A call with no start/end is skipped rather than guessed, same as an
    unattributable billing line item — there's nothing to correlate it
    against without a real time window."""
    records: list[CallRecord] = []
    for raw in raw_calls:
        start_raw, end_raw = _first(raw, _START_KEYS), _first(raw, _END_KEYS)
        if not start_raw or not end_raw:
            continue
        attendees_raw = _first(raw, _ATTENDEES_KEYS) or []
        attendees = [a for a in (_attendee_identity(e) for e in attendees_raw) if a]
        speaking = _first(raw, _SPEAKING_KEYS) or {}
        records.append(
            CallRecord(
                matter_id=matter_id,
                source_event_id=_first(raw, _EVENT_ID_KEYS),
                start=_parse_timestamp(start_raw),
                end=_parse_timestamp(end_raw),
                subject=_first(raw, _SUBJECT_KEYS),
                attendees=attendees,
                speaking_seconds={str(k): float(v) for k, v in speaking.items()},
            )
        )
    records.sort(key=lambda c: c.start)
    return records
