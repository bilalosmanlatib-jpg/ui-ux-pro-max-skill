from datetime import datetime, timezone

from counsel_analytics.models import Evidence, MatterMetrics, MatterRef, Metric
from counsel_analytics.report.packet import build_review_packet, render_packet_markdown, select_highlights
from counsel_analytics.signoff import SignOffRecord, snapshot_hash

MATTER_REF = MatterRef(library="LIB", workspace_id="LIB!1000", display_name="Test Matter")
GENERATED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _metric(name, value, direction, note="a note", doc_ids=None) -> Metric:
    return Metric(
        name=name,
        value=value,
        unit="u",
        direction=direction,
        evidence=Evidence(doc_ids=doc_ids or []),
        note=note,
    )


MIXED_METRICS = [
    _metric("m_up_small", 5.0, "up", note="note-up-small", doc_ids=["D1"]),
    _metric("m_down_small", -3.0, "down", note="note-down-small", doc_ids=["D2"]),
    _metric("m_flat", 0.01, "flat", note="flat note"),
    _metric("m_up_big", 10.0, "up", note="note-up-big", doc_ids=["D1"]),
    _metric("m_down_tiny", 1.0, "down", note=None),
]


def test_select_highlights_excludes_flat_and_ranks_by_magnitude():
    shown, omitted, flat_count = select_highlights(MIXED_METRICS, max_highlights=2, min_abs_value=0.0)
    assert flat_count == 1
    assert [h.name for h in shown] == ["m_up_big", "m_up_small"]
    assert omitted == 2  # m_down_small, m_down_tiny past the cap


def test_select_highlights_notes_never_truncated():
    long_note = "x" * 500
    metrics = [_metric("m1", 5.0, "up", note=long_note)]
    shown, _, _ = select_highlights(metrics, max_highlights=8, min_abs_value=0.0)
    assert shown[0].note == long_note


def test_select_highlights_min_abs_value_filters_small_movers():
    shown, omitted, flat_count = select_highlights(MIXED_METRICS, max_highlights=8, min_abs_value=2.0)
    assert {h.name for h in shown} == {"m_up_small", "m_down_small", "m_up_big"}
    assert omitted == 1  # m_down_tiny (1.0) filtered by threshold
    assert flat_count == 1


def test_select_highlights_all_flat_returns_empty():
    shown, omitted, flat_count = select_highlights([MIXED_METRICS[2]], max_highlights=8, min_abs_value=0.0)
    assert shown == []
    assert omitted == 0
    assert flat_count == 1


def test_select_highlights_ranks_cosine_similarity_by_severity_not_magnitude():
    """clause_reargument_semantic (unit=cosine_similarity) encodes severity
    inversely: a LOWER similarity is a MORE concerning reopened clause.
    Ranking by abs(value) would rank the barely-below-threshold, least
    concerning case (0.54) ahead of the severely dissimilar, most
    concerning case (0.02) — see report/packet.py's `_salience`."""
    less_concerning = _metric("clause_reargument_semantic", 0.54, "down", note="barely below threshold")
    less_concerning = less_concerning.model_copy(update={"unit": "cosine_similarity"})
    more_concerning = _metric("clause_reargument_semantic", 0.02, "down", note="severely dissimilar")
    more_concerning = more_concerning.model_copy(update={"unit": "cosine_similarity"})

    shown, omitted, _ = select_highlights(
        [less_concerning, more_concerning], max_highlights=1, min_abs_value=0.0
    )

    assert [h.note for h in shown] == ["severely dissimilar"]
    assert omitted == 1


def test_select_highlights_empty_input():
    shown, omitted, flat_count = select_highlights([], max_highlights=8, min_abs_value=0.0)
    assert (shown, omitted, flat_count) == ([], 0, 0)


def _matter_metrics(metrics, clause_signals=None) -> MatterMetrics:
    return MatterMetrics(
        matter_ref=MATTER_REF,
        version_events=[],
        metrics=metrics,
        clause_signals=clause_signals or [],
        generated_at=GENERATED_AT,
    )


def test_render_packet_markdown_no_silent_truncation_line():
    mm = _matter_metrics(MIXED_METRICS)
    packet = build_review_packet(mm, max_highlights=2, min_abs_value=0.0)
    md = render_packet_markdown(packet)
    assert "2 more trending metric(s) and 1 steady metric(s) not shown" in md
    assert "note-up-big" in md
    assert "note-up-small" in md


def test_render_packet_markdown_all_flat_case():
    mm = _matter_metrics([MIXED_METRICS[2]])
    packet = build_review_packet(mm)
    md = render_packet_markdown(packet)
    assert "No notable movements" in md


def test_render_packet_markdown_empty_metrics_case():
    mm = _matter_metrics([])
    packet = build_review_packet(mm)
    md = render_packet_markdown(packet)
    assert "No metrics available" in md


def test_packet_not_stale_when_signoff_matches_current_hash():
    mm = _matter_metrics(MIXED_METRICS)
    prior = SignOffRecord(
        matter_workspace_id="LIB!1000",
        snapshot_hash=snapshot_hash(mm),
        decision="approve",
        reviewer="jane@ninetyone.com",
        reason="fine",
        signed_at=GENERATED_AT,
    )
    packet = build_review_packet(mm, prior_signoff=prior)
    assert packet.stale is False
    assert "re-review required" not in render_packet_markdown(packet)


def test_build_review_packet_includes_clause_signals():
    """clause_signals (e.g. reargument findings) must be counted and eligible
    for highlighting, not silently ignored (see report/packet.py's own
    'no silent caps: every metric is accounted for' contract)."""
    reargument = _metric("clause_reargument_pingpong", 12.0, "up", note="ping-pong note", doc_ids=["D3"])
    mm = _matter_metrics(MIXED_METRICS, clause_signals=[reargument])

    packet = build_review_packet(mm, max_highlights=8, min_abs_value=0.0)

    assert packet.total_metric_count == len(MIXED_METRICS) + 1
    assert "clause_reargument_pingpong" in [h.name for h in packet.highlights]
    md = render_packet_markdown(packet)
    assert "clause_reargument_pingpong" in md
    assert "ping-pong note" in md


def test_packet_stale_when_evidence_changed_since_signoff():
    mm = _matter_metrics(MIXED_METRICS)
    prior = SignOffRecord(
        matter_workspace_id="LIB!1000",
        snapshot_hash="sha256:stale-hash-does-not-match",
        decision="approve",
        reviewer="jane@ninetyone.com",
        reason="fine",
        signed_at=GENERATED_AT,
    )
    packet = build_review_packet(mm, prior_signoff=prior)
    assert packet.stale is True
    assert "re-review required" in render_packet_markdown(packet)
