"""Redline volume/density metrics.

Per-version comment/correspondence volume (the other half of this metric
per the design doc) needs `ingest.correspond`, which is a Phase 2 item —
this module only covers the diff-derived density signal available in
Phase 1.
"""

from __future__ import annotations

from counsel_analytics.metrics._stats import linear_trend_slope, mean
from counsel_analytics.models import DiffResult, DocumentRef, Evidence, Metric

_TREND_FLAT_EPSILON = 0.01

_DENSITY_TREND_NOTE = (
    "Rising density may indicate increasing friction or increasing "
    "thoroughness of review — reported as a hypothesis, not a verdict."
)


def compute_volume_metrics(document_ref: DocumentRef, diffs: list[DiffResult]) -> list[Metric]:
    if not diffs:
        return []

    densities = [d.changed_tokens / d.total_tokens for d in diffs]
    version_indices = [float(d.to_version) for d in diffs]
    slope = linear_trend_slope(version_indices, densities)
    direction = "flat"
    if slope > _TREND_FLAT_EPSILON:
        direction = "up"
    elif slope < -_TREND_FLAT_EPSILON:
        direction = "down"

    evidence = Evidence(doc_ids=[document_ref.document_id])

    return [
        Metric(
            name="redline_density_mean",
            value=round(mean(densities), 4),
            unit="changed_tokens_ratio",
            direction="flat",
            evidence=evidence,
            note=(
                f"Mean redline density across {len(diffs)} version "
                f"transition(s) on {document_ref.name}."
            ),
        ),
        Metric(
            name="redline_density_trend",
            value=round(slope, 5),
            unit="ratio_per_version",
            direction=direction,
            evidence=evidence,
            note=_DENSITY_TREND_NOTE,
        ),
    ]
