"""Cross-matter counterparty (firm) rollup — Phase 3.

Groups already-computed `MatterMetrics` by firm and computes, per metric
name, how that metric has trended across the firm relationship over time
(ordered by each matter's start date, not report-generation date). This is
a coarse, hypothesis-level signal by design: a slope across a handful of
matters is not a statistically rigorous trend, and the note text on every
rollup metric says so explicitly — never a verdict, always attributable
back to the matters listed in its evidence.

Only `MatterMetrics.metrics` (turnaround/volume/tone) feed the rollup, not
`clause_signals`: a matter's `metrics` list has at most one representative
value per metric name per document (averaged across documents into one
matter-level value here), whereas `clause_signals` is one entry *per
flagged clause* — there's no single well-defined "this matter's value" to
compare across matters without inventing an aggregation rule nobody asked
for. If clause-level firm rollups are wanted later, that's a deliberate
follow-on, not an oversight.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from counsel_analytics.mcp.imanage import classify_author_side
from counsel_analytics.metrics._stats import linear_trend_slope, mean
from counsel_analytics.models import CommentThread, CounterpartyRollup, Direction, Evidence, MatterMetrics, Metric, VersionEvent

_MIN_MATTERS_FOR_ROLLUP = 2
_TREND_EPSILON = 0.001
_MAX_EVIDENCE_QUOTES = 20


def resolve_matter_firm(
    version_events: list[VersionEvent], internal_domains: list[str], firm_domains: dict[str, str]
) -> str | None:
    """The most frequent firm among the matter's counsel-side authors, or
    None if no counsel-side author resolved to a known firm. Deliberately
    a majority vote rather than "first seen" — a matter can have version
    events from more than one firm's domain (co-counsel, a firm switch
    mid-matter), and the most frequent one is the more representative
    single label for a rollup bucket.
    """
    firms = []
    for event in version_events:
        _side, firm = classify_author_side(event.author_id, internal_domains, firm_domains)
        if firm:
            firms.append(firm)
    if not firms:
        return None
    return Counter(firms).most_common(1)[0][0]


def resolve_firm_from_threads(threads: list[CommentThread]) -> str | None:
    """Same majority-vote logic as `resolve_matter_firm`, but over
    correspondence rather than document version events — the only signal
    available for domains with no documents to diff (e.g. compliance, see
    `sources/compliance.py`), and a fallback for any matter where the
    version-event-based resolution above turns up nothing.
    """
    firms = [message.firm for thread in threads for message in thread.messages if message.firm]
    if not firms:
        return None
    return Counter(firms).most_common(1)[0][0]


def matter_start_date(matter_metrics: MatterMetrics) -> datetime:
    if matter_metrics.version_events:
        return min(e.timestamp for e in matter_metrics.version_events)
    return matter_metrics.generated_at


def _matter_level_metric_values(matter_metrics: MatterMetrics) -> dict[str, tuple[float, str]]:
    """Collapses a matter's (possibly multi-document) `metrics` list into
    one representative (mean value, unit) per metric name."""
    values_by_name: dict[str, list[float]] = defaultdict(list)
    unit_by_name: dict[str, str] = {}
    for metric in matter_metrics.metrics:
        values_by_name[metric.name].append(metric.value)
        unit_by_name.setdefault(metric.name, metric.unit)
    return {name: (mean(values), unit_by_name[name]) for name, values in values_by_name.items()}


def _direction(slope: float) -> Direction:
    if slope > _TREND_EPSILON:
        return "up"
    if slope < -_TREND_EPSILON:
        return "down"
    return "flat"


def _build_rollup(firm: str, ordered_matters: list[MatterMetrics]) -> CounterpartyRollup:
    series: dict[str, list[tuple[int, float, str, datetime, str]]] = defaultdict(list)

    for idx, mm in enumerate(ordered_matters):
        start_date = matter_start_date(mm)
        for name, (value, unit) in _matter_level_metric_values(mm).items():
            series[name].append((idx, value, mm.matter_ref.workspace_id, start_date, unit))

    rollup_metrics: list[Metric] = []
    for name, points in series.items():
        if len(points) < _MIN_MATTERS_FOR_ROLLUP:
            continue  # this metric only appears on one matter so far — nothing to trend yet

        xs = [float(p[0]) for p in points]
        ys = [p[1] for p in points]
        slope = linear_trend_slope(xs, ys)
        unit = points[0][4]

        quotes = [f"{workspace_id} ({start_date.date()}): {value}" for _idx, value, workspace_id, start_date, _u in points]

        rollup_metrics.append(
            Metric(
                name=f"{name}_firm_trend",
                value=round(slope, 4),
                unit=f"{unit}_per_matter",
                direction=_direction(slope),
                evidence=Evidence(
                    # Not document ids at this level — the workspace_ids of
                    # the specific matters this metric's points were drawn
                    # from (a subset of the firm's matters when a metric
                    # doesn't appear on all of them). `report/rollup.py`'s
                    # CSV writer relies on this to attribute each row.
                    doc_ids=[p[2] for p in points],
                    timestamps=[p[3] for p in points],
                    quotes=quotes[:_MAX_EVIDENCE_QUOTES],
                ),
                note=(
                    f"Trend of {name} across {len(points)} matter(s) with {firm}, ordered by "
                    f"matter start date. A slope across this few matters is a coarse, "
                    f"hypothesis-level signal about the relationship over time — not a "
                    f"statistically rigorous trend and never a verdict."
                ),
            )
        )

    return CounterpartyRollup(
        firm=firm,
        matters=[mm.matter_ref for mm in ordered_matters],
        metrics=rollup_metrics,
        generated_at=max(mm.generated_at for mm in ordered_matters),
    )


def compute_counterparty_rollups(all_matter_metrics: list[MatterMetrics]) -> list[CounterpartyRollup]:
    """Only firms with >= 2 matters get a rollup — a single matter has
    nothing to trend against yet. Matters with no resolvable firm
    (`matter_ref.firm is None`) are excluded, not silently guessed at.
    """
    by_firm: dict[str, list[MatterMetrics]] = defaultdict(list)
    for mm in all_matter_metrics:
        if mm.matter_ref.firm:
            by_firm[mm.matter_ref.firm].append(mm)

    rollups = []
    for firm, matters in by_firm.items():
        if len(matters) < _MIN_MATTERS_FOR_ROLLUP:
            continue
        ordered = sorted(matters, key=matter_start_date)
        rollups.append(_build_rollup(firm, ordered))
    return rollups
