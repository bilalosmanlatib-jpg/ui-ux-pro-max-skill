"""Translate raw invoice/time-entry line items into `TimeEntry` domain models.

There is no e-billing MCP connector connected — billing data is extracted
from invoice documents filed in iManage like any other document (PDF/Excel
via `download_document`, or `get_rows_from_csv_document` for a CSV/Excel
invoice), itemized in-session the same way correspondence already is, and
written to `raw_data["billing"]`. This module only translates those
already-itemized dicts into `TimeEntry` objects — it never touches MCP
tools or parses raw invoice text/bytes itself, mirroring `mcp/m365.py`'s
`_first()`-over-key-aliases pattern.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dateutil import parser as dateutil_parser

from counsel_analytics.models import TimeEntry

_NAME_KEYS = ("timekeeper", "timekeeper_name", "fee_earner", "author", "name")
_ROLE_KEYS = ("role", "timekeeper_role", "position", "title")
_DATE_KEYS = ("date", "entry_date", "work_date", "service_date")
_HOURS_KEYS = ("hours", "time", "duration_hours", "hours_billed")
_RATE_KEYS = ("rate", "hourly_rate")
_AMOUNT_KEYS = ("amount", "total", "line_amount", "value")
_CURRENCY_KEYS = ("currency", "ccy")
_NARRATIVE_KEYS = ("narrative", "description", "task_description", "notes")


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
            raise ValueError("Time entry is missing a date field")
        parsed = dateutil_parser.parse(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_time_entries(
    matter_id: str, raw_entries: list[dict], *, source_document_id: str | None = None
) -> list[TimeEntry]:
    """A line item with no timekeeper name or no hours is skipped rather
    than guessed — an unattributable entry can't be audited against
    anything, and silently inventing a name would be worse than dropping it.
    """
    entries: list[TimeEntry] = []
    for raw in raw_entries:
        name = _first(raw, _NAME_KEYS)
        hours = _first(raw, _HOURS_KEYS)
        if not name or hours is None:
            continue
        entries.append(
            TimeEntry(
                matter_id=matter_id,
                source_document_id=source_document_id,
                timekeeper_name=str(name),
                timekeeper_role=_first(raw, _ROLE_KEYS),
                entry_date=_parse_timestamp(_first(raw, _DATE_KEYS)),
                hours=float(hours),
                rate=_first(raw, _RATE_KEYS),
                amount=_first(raw, _AMOUNT_KEYS),
                currency=_first(raw, _CURRENCY_KEYS),
                narrative=str(_first(raw, _NARRATIVE_KEYS) or ""),
            )
        )
    entries.sort(key=lambda e: e.entry_date)
    return entries
