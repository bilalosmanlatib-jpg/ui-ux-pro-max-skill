from datetime import datetime, timezone

from counsel_analytics.metrics.aggregate import (
    compute_counterparty_rollups,
    matter_start_date,
    resolve_firm_from_threads,
    resolve_matter_firm,
)
from counsel_analytics.models import CommentThread, Evidence, MatterMetrics, MatterRef, Message, Metric, VersionEvent

INTERNAL_DOMAINS = ["ninetyone.com"]
FIRM_DOMAINS = {"examplefirmllp.com": "Example Firm LLP"}


def _version(version_no: int, author_id: str, ts: str) -> VersionEvent:
    side = "internal" if "ninetyone" in author_id else "counsel"
    return VersionEvent(
        document_id_versioned=f"DOC.{version_no}",
        version_no=version_no,
        author_id=author_id,
        author_side=side,
        timestamp=datetime.fromisoformat(ts),
    )


def _matter_metrics(workspace_id: str, firm, value: float, ts: datetime, unit: str = "business_days", version_events=None) -> MatterMetrics:
    return MatterMetrics(
        matter_ref=MatterRef(library="LIB", workspace_id=workspace_id, display_name=f"Matter {workspace_id}", firm=firm),
        version_events=version_events or [],
        metrics=[
            Metric(
                name="counsel_turnaround_mean",
                value=value,
                unit=unit,
                direction="flat",
                evidence=Evidence(doc_ids=["DOC1"]),
                note="n",
            )
        ],
        generated_at=ts,
    )


def test_resolve_matter_firm_majority_vote():
    events = [
        _version(1, "jane@ninetyone.com", "2026-01-01T00:00:00+00:00"),
        _version(2, "counsel@examplefirmllp.com", "2026-01-02T00:00:00+00:00"),
        _version(3, "counsel@examplefirmllp.com", "2026-01-03T00:00:00+00:00"),
    ]
    assert resolve_matter_firm(events, INTERNAL_DOMAINS, FIRM_DOMAINS) == "Example Firm LLP"


def test_resolve_matter_firm_none_when_no_counsel_author():
    events = [_version(1, "jane@ninetyone.com", "2026-01-01T00:00:00+00:00")]
    assert resolve_matter_firm(events, INTERNAL_DOMAINS, FIRM_DOMAINS) is None


def test_resolve_matter_firm_none_when_unmatched_domain():
    events = [_version(1, "someone@othercorp.com", "2026-01-01T00:00:00+00:00")]
    assert resolve_matter_firm(events, INTERNAL_DOMAINS, FIRM_DOMAINS) is None


def _thread(*firms: str | None) -> CommentThread:
    return CommentThread(
        matter_id="LIB!5000",
        source="outlook",
        messages=[
            Message(timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), sender_side="counsel", text="t", firm=f)
            for f in firms
        ],
    )


def test_resolve_firm_from_threads_majority_vote():
    threads = [_thread("Example Firm LLP", "Example Firm LLP", None), _thread("Other Firm")]
    assert resolve_firm_from_threads(threads) == "Example Firm LLP"


def test_resolve_firm_from_threads_none_when_no_firm_messages():
    threads = [_thread(None, None)]
    assert resolve_firm_from_threads(threads) is None


def test_matter_start_date_uses_earliest_version_event():
    events = [
        _version(2, "counsel@examplefirmllp.com", "2026-01-10T00:00:00+00:00"),
        _version(1, "jane@ninetyone.com", "2026-01-05T00:00:00+00:00"),
    ]
    mm = _matter_metrics("LIB!1000", "Example Firm LLP", 5.0, datetime(2026, 6, 1, tzinfo=timezone.utc), version_events=events)
    assert matter_start_date(mm) == datetime(2026, 1, 5, tzinfo=timezone.utc)


def test_matter_start_date_falls_back_to_generated_at_when_no_versions():
    mm = _matter_metrics("LIB!1000", "Example Firm LLP", 5.0, datetime(2026, 6, 1, tzinfo=timezone.utc))
    assert matter_start_date(mm) == datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_compute_counterparty_rollups_two_matters_same_firm_produces_trend():
    m1 = _matter_metrics("LIB!1000", "Example Firm LLP", 5.0, datetime(2026, 1, 1, tzinfo=timezone.utc))
    m2 = _matter_metrics("LIB!3000", "Example Firm LLP", 2.0, datetime(2026, 2, 1, tzinfo=timezone.utc))

    rollups = compute_counterparty_rollups([m1, m2])
    assert len(rollups) == 1
    rollup = rollups[0]
    assert rollup.firm == "Example Firm LLP"
    assert {m.workspace_id for m in rollup.matters} == {"LIB!1000", "LIB!3000"}

    metric = next(m for m in rollup.metrics if m.name == "counsel_turnaround_mean_firm_trend")
    assert metric.direction == "down"  # 5.0 -> 2.0, turnaround improving
    assert metric.value < 0
    assert "hypothesis" in metric.note


def test_compute_counterparty_rollups_single_matter_firm_produces_no_rollup():
    m1 = _matter_metrics("LIB!1000", "Example Firm LLP", 5.0, datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert compute_counterparty_rollups([m1]) == []


def test_compute_counterparty_rollups_excludes_matters_with_no_firm():
    m1 = _matter_metrics("LIB!1000", None, 5.0, datetime(2026, 1, 1, tzinfo=timezone.utc))
    m2 = _matter_metrics("LIB!3000", None, 2.0, datetime(2026, 2, 1, tzinfo=timezone.utc))
    assert compute_counterparty_rollups([m1, m2]) == []


def test_compute_counterparty_rollups_orders_by_matter_start_date_not_list_order():
    # m2 (Feb) passed first, m1 (Jan) passed second -- ordering must follow
    # matter_start_date, not input order, or the trend direction would flip.
    m2 = _matter_metrics("LIB!3000", "Example Firm LLP", 2.0, datetime(2026, 2, 1, tzinfo=timezone.utc))
    m1 = _matter_metrics("LIB!1000", "Example Firm LLP", 5.0, datetime(2026, 1, 1, tzinfo=timezone.utc))

    rollups = compute_counterparty_rollups([m2, m1])
    assert [m.workspace_id for m in rollups[0].matters] == ["LIB!1000", "LIB!3000"]


def test_compute_counterparty_rollups_collapses_multi_document_matter_to_one_value():
    mm = MatterMetrics(
        matter_ref=MatterRef(library="LIB", workspace_id="LIB!1000", display_name="M", firm="Example Firm LLP"),
        version_events=[],
        metrics=[
            Metric(name="counsel_turnaround_mean", value=4.0, unit="business_days", direction="flat", evidence=Evidence(doc_ids=["D1"])),
            Metric(name="counsel_turnaround_mean", value=6.0, unit="business_days", direction="flat", evidence=Evidence(doc_ids=["D2"])),
        ],
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    m2 = _matter_metrics("LIB!3000", "Example Firm LLP", 1.0, datetime(2026, 2, 1, tzinfo=timezone.utc))

    rollups = compute_counterparty_rollups([mm, m2])
    quotes = next(m for m in rollups[0].metrics if m.name == "counsel_turnaround_mean_firm_trend").evidence.quotes
    assert any("LIB!1000 (2026-01-01): 5.0" in q for q in quotes)  # mean of 4.0 and 6.0


def test_compute_counterparty_rollups_metric_evidence_lists_only_contributing_matters():
    # 3 matters in the firm, but only 2 of them carry counsel_turnaround_mean
    # -- the metric's evidence must name just those 2, not all 3 firm matters.
    m1 = _matter_metrics("LIB!1000", "Example Firm LLP", 5.0, datetime(2026, 1, 1, tzinfo=timezone.utc))
    m2 = _matter_metrics("LIB!3000", "Example Firm LLP", 2.0, datetime(2026, 2, 1, tzinfo=timezone.utc))
    m3 = MatterMetrics(
        matter_ref=MatterRef(library="LIB", workspace_id="LIB!5000", display_name="M3", firm="Example Firm LLP"),
        version_events=[],
        metrics=[],  # no counsel_turnaround_mean on this matter
        generated_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
    )

    rollups = compute_counterparty_rollups([m1, m2, m3])
    assert len(rollups) == 1
    rollup = rollups[0]
    assert {m.workspace_id for m in rollup.matters} == {"LIB!1000", "LIB!3000", "LIB!5000"}

    metric = next(m for m in rollup.metrics if m.name == "counsel_turnaround_mean_firm_trend")
    assert set(metric.evidence.doc_ids) == {"LIB!1000", "LIB!3000"}
