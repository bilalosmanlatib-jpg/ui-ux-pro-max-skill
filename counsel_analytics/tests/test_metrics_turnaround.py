from datetime import datetime

from counsel_analytics.metrics.turnaround import compute_turnaround_metrics, detect_handoff_rounds
from counsel_analytics.models import DocumentRef, VersionEvent

DOC = DocumentRef(document_id="LIB!2001", name="Share Purchase Agreement.docx")


def _event(version_no: int, side: str, ts: str) -> VersionEvent:
    return VersionEvent(
        document_id_versioned=f"LIB!2001.{version_no}",
        version_no=version_no,
        author_id=f"user{version_no}@example.com",
        author_side=side,
        timestamp=datetime.fromisoformat(ts),
    )


VERSIONS = [
    _event(1, "internal", "2026-01-05T09:00:00"),
    _event(2, "counsel", "2026-01-09T17:00:00"),
    _event(3, "internal", "2026-01-12T10:00:00"),
    _event(4, "counsel", "2026-01-14T12:00:00"),
    _event(5, "internal", "2026-01-16T09:00:00"),
]


def test_detect_handoff_rounds_finds_two_rounds():
    rounds = detect_handoff_rounds(VERSIONS, diffs=[])
    assert len(rounds) == 2
    assert (rounds[0].sent_version, rounds[0].returned_version) == (1, 3)
    assert (rounds[1].sent_version, rounds[1].returned_version) == (3, 5)
    assert rounds[0].hold_time_business_days == 5.0
    assert rounds[1].hold_time_business_days == 4.0


def test_compute_turnaround_metrics_trend_direction_down_when_speeding_up():
    rounds, metrics = compute_turnaround_metrics(DOC, VERSIONS, diffs=[])
    assert len(rounds) == 2

    by_name = {m.name: m for m in metrics}
    assert by_name["counsel_turnaround_mean"].value == 4.5
    assert by_name["counsel_turnaround_median"].value == 4.5
    trend = by_name["counsel_turnaround_trend"]
    assert trend.direction == "down"
    assert trend.value == -1.0
    assert "Slowest round" in trend.note


def test_compute_turnaround_metrics_no_rounds_returns_empty():
    solo_internal = [VERSIONS[0]]
    rounds, metrics = compute_turnaround_metrics(DOC, solo_internal, diffs=[])
    assert rounds == []
    assert metrics == []


def test_detect_handoff_rounds_unknown_author_drops_only_affected_round():
    """An 'unknown'-classified author mid-round must not corrupt every
    later round on the document — only the round open at the time of the
    unknown side should be dropped; later, unambiguous rounds must still
    be detected (see metrics/turnaround.py's round-in-progress reset)."""
    versions = [
        _event(1, "internal", "2026-01-05T09:00:00"),
        _event(2, "counsel", "2026-01-06T09:00:00"),
        _event(3, "unknown", "2026-01-07T09:00:00"),
        _event(4, "internal", "2026-01-08T09:00:00"),
        _event(5, "internal", "2026-01-09T09:00:00"),
        _event(6, "counsel", "2026-01-12T09:00:00"),
        _event(7, "internal", "2026-01-16T09:00:00"),
    ]

    rounds = detect_handoff_rounds(versions, diffs=[])

    assert len(rounds) == 1
    assert (rounds[0].sent_version, rounds[0].returned_version) == (5, 7)
