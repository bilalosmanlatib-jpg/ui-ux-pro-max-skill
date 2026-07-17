"""Translate raw iManage Work MCP responses into domain models.

Field names below cover the variants observed in iManage Work API
responses (`version`/`versionNumber`, `author`/`createdBy`/`author_id`,
etc.). Confirm the exact shape against a real `get_document_versions` call
during the Phase 0 smoke test and adjust `_FIELD_ALIASES` if needed — this
is the one place that mapping lives, by design.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dateutil import parser as dateutil_parser

from counsel_analytics.models import AuthorSide, VersionEvent

_VERSION_NO_KEYS = ("version", "versionNumber", "version_number", "ver")
_AUTHOR_KEYS = ("author", "authorId", "author_id", "createdBy", "created_by", "editedBy")
_TIMESTAMP_KEYS = ("modifiedDate", "modified_date", "editDate", "edit_date", "createDate", "lastModified")
_SIZE_KEYS = ("size", "sizeInBytes", "size_bytes", "documentSize")
_COMMENT_KEYS = ("comment", "versionComment", "version_comment", "description")


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
            raise ValueError("Version record is missing a timestamp field")
        parsed = dateutil_parser.parse(str(value))
    # iManage fields (e.g. on-prem `modifiedDate`) are frequently
    # timezone-naive. Assume UTC so these compare cleanly against
    # timezone-aware timestamps from other sources (e.g. Graph's
    # 'Z'-suffixed `sentDateTime`) instead of raising on subtraction.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def classify_author_side(
    author_identity: str, internal_domains: list[str], firm_domains: dict[str, str]
) -> tuple[AuthorSide, str | None]:
    """Returns (side, firm_name). `author_identity` is typically an email
    address; falls back to `unknown` if no domain match is found, which the
    caller should surface as a data-quality note rather than guess.
    """
    identity = author_identity.strip().lower()
    domain = identity.rsplit("@", 1)[-1] if "@" in identity else ""
    if domain and any(domain == d.lower() for d in internal_domains):
        return "internal", None
    firm = firm_domains.get(domain)
    if firm:
        return "counsel", firm
    return "unknown", None


def parse_version_events(
    document_id: str,
    raw_versions: list[dict],
    internal_domains: list[str],
    firm_domains: dict[str, str],
) -> list[VersionEvent]:
    """`raw_versions` is the list returned by `get_document_versions`,
    ordered oldest-first or newest-first depending on the API — this
    function sorts by version number to guarantee order regardless.
    """
    events: list[VersionEvent] = []
    for raw in raw_versions:
        version_no = _first(raw, _VERSION_NO_KEYS)
        if version_no is None:
            raise ValueError(f"Version record for {document_id} has no version number: {raw}")
        author_identity = _first(raw, _AUTHOR_KEYS) or "unknown"
        side, _firm = classify_author_side(str(author_identity), internal_domains, firm_domains)
        events.append(
            VersionEvent(
                document_id_versioned=f"{document_id}.{version_no}",
                version_no=int(version_no),
                author_id=str(author_identity),
                author_side=side,
                timestamp=_parse_timestamp(_first(raw, _TIMESTAMP_KEYS)),
                size_bytes=_first(raw, _SIZE_KEYS),
                imanage_comment=_first(raw, _COMMENT_KEYS),
            )
        )
    events.sort(key=lambda e: e.version_no)
    return events
