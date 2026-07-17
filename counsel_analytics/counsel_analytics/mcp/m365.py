"""Translate raw Microsoft 365 MCP responses (outlook_email_search,
sharepoint_search, chat_message_search) into domain models.

Mirrors `mcp/imanage.py`'s pattern exactly: a `_first()`-over-key-aliases
helper for tolerating varied raw shapes, and reuse of
`imanage.classify_author_side` for `sender_side` — no parallel
side-classification logic.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from dateutil import parser as dateutil_parser

from counsel_analytics.mcp.imanage import classify_author_side
from counsel_analytics.models import CommentThread, CorrespondenceSource, Message

_SENDER_KEYS = ("from", "sender", "senderEmailAddress", "from_address", "author")
_TIMESTAMP_KEYS = ("sentDateTime", "receivedDateTime", "timestamp", "date", "createdDateTime")
_SUBJECT_KEYS = ("subject", "title", "topic")
_BODY_KEYS = ("body", "bodyPreview", "content", "text", "message")
_SOURCE_KEYS = ("source",)

_SOURCE_ALIASES: dict[str, CorrespondenceSource] = {
    "outlook": "outlook",
    "email": "outlook",
    "outlook_email": "outlook",
    "imanage_email": "imanage_email",
    "imanage": "imanage_email",
    "teams": "teams",
    "chat": "teams",
    "chat_message": "teams",
}


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
            raise ValueError("Message record is missing a timestamp field")
        parsed = dateutil_parser.parse(str(value))
    # Some sources (e.g. chat exports, legacy email fields) omit an offset.
    # Assume UTC so these compare cleanly against timezone-aware timestamps
    # from other sources instead of raising on subtraction.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _extract_body_text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("content", ""))
    return str(value) if value is not None else ""


def _normalize_source(raw_source: Any) -> CorrespondenceSource:
    key = str(raw_source or "outlook").strip().lower()
    return _SOURCE_ALIASES.get(key, "outlook")


def parse_messages(
    raw_messages: list[dict], internal_domains: list[str], firm_domains: dict[str, str]
) -> list[Message]:
    messages = []
    for raw in raw_messages:
        sender_identity = _first(raw, _SENDER_KEYS) or "unknown"
        side, _firm = classify_author_side(str(sender_identity), internal_domains, firm_domains)
        messages.append(
            Message(
                timestamp=_parse_timestamp(_first(raw, _TIMESTAMP_KEYS)),
                sender_side=side,
                text=_extract_body_text(_first(raw, _BODY_KEYS)),
                subject=_first(raw, _SUBJECT_KEYS),
            )
        )
    messages.sort(key=lambda m: m.timestamp)
    return messages


def parse_comment_threads(
    matter_id: str,
    raw_messages: list[dict],
    internal_domains: list[str],
    firm_domains: dict[str, str],
) -> list[CommentThread]:
    grouped_raw: dict[CorrespondenceSource, list[dict]] = defaultdict(list)
    for raw in raw_messages:
        source = _normalize_source(_first(raw, _SOURCE_KEYS))
        grouped_raw[source].append(raw)

    return [
        CommentThread(
            matter_id=matter_id,
            source=source,
            messages=parse_messages(raws, internal_domains, firm_domains),
        )
        for source, raws in grouped_raw.items()
    ]
