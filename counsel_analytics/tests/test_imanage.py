from datetime import timezone

from counsel_analytics.mcp.imanage import parse_version_events

INTERNAL_DOMAINS = ["ninetyone.com"]
FIRM_DOMAINS = {"examplefirmllp.com": "Example Firm LLP"}


def test_parse_version_events_naive_timestamp_is_normalized_to_utc():
    # On-prem/legacy iManage `modifiedDate` values commonly omit a UTC
    # offset. These must come out timezone-aware so they can be compared
    # against timezone-aware timestamps from other sources (e.g. Graph's
    # 'Z'-suffixed `sentDateTime`) without raising.
    raw = [
        {
            "version": 1,
            "author": "jane.doe@ninetyone.com",
            "modifiedDate": "2026-02-04T15:30:00",
        }
    ]
    events = parse_version_events("LIB!4001", raw, INTERNAL_DOMAINS, FIRM_DOMAINS)

    assert events[0].timestamp.tzinfo is not None
    assert events[0].timestamp.utcoffset() == timezone.utc.utcoffset(None)


def test_parse_version_events_aware_timestamp_is_preserved():
    raw = [
        {
            "version": 1,
            "author": "jane.doe@ninetyone.com",
            "modifiedDate": "2026-02-04T15:30:00+05:00",
        }
    ]
    events = parse_version_events("LIB!4001", raw, INTERNAL_DOMAINS, FIRM_DOMAINS)

    assert events[0].timestamp.utcoffset().total_seconds() == 5 * 3600
