"""Counsel turnaround-time metrics.

A "round" is one internal -> counsel -> internal hand-off: we sent a
version out, counsel edited it (possibly across several of their own
versions), and it came back. Hold-time is measured on the round, not on
individual versions, because that's the unit the business actually cares
about ("how long did it sit with counsel").
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from counsel_analytics.metrics._stats import business_days_between, linear_trend_slope, mean, median
from counsel_analytics.models import DiffResult, DocumentRef, Evidence, Metric, VersionEvent

_TREND_FLAT_EPSILON_DAYS = 0.15  # slope magnitude below this is reported as "flat"


class TurnaroundRound(BaseModel):
    round_index: int
    sent_version: int
    sent_at: datetime
    returned_version: int
    returned_at: datetime
    hold_time_business_days: float
    diffs_in_between: list[DiffResult]


def detect_handoff_rounds(
    versions: list[VersionEvent], diffs: list[DiffResult]
) -> list[TurnaroundRound]:
    diffs_by_pair = {(d.from_version, d.to_version): d for d in diffs}
    rounds: list[TurnaroundRound] = []
    sent_version: VersionEvent | None = None

    for cur, nxt in zip(versions, versions[1:]):
        if cur.author_side == "unknown" or nxt.author_side == "unknown":
            # An unclassified author breaks our ability to say whether this
            # pair is inside a hand-off round or not. Drop whatever round was
            # in progress rather than let it linger — otherwise the `if
            # sent_version is None` guard below never re-triggers and every
            # later internal->counsel start silently stops being detected.
            sent_version = None
            continue
        if sent_version is None and cur.author_side == "internal" and nxt.author_side == "counsel":
            sent_version = cur
        elif sent_version is not None and cur.author_side == "counsel" and nxt.author_side == "internal":
            in_between = [
                diffs_by_pair[pair]
                for pair in diffs_by_pair
                if sent_version.version_no <= pair[0] and pair[1] <= nxt.version_no
            ]
            rounds.append(
                TurnaroundRound(
                    round_index=len(rounds) + 1,
                    sent_version=sent_version.version_no,
                    sent_at=sent_version.timestamp,
                    returned_version=nxt.version_no,
                    returned_at=nxt.timestamp,
                    hold_time_business_days=business_days_between(
                        sent_version.timestamp, nxt.timestamp
                    ),
                    diffs_in_between=in_between,
                )
            )
            sent_version = None

    return rounds


def _bottleneck_note(rounds: list[TurnaroundRound]) -> str | None:
    if not rounds:
        return None
    slowest = max(rounds, key=lambda r: r.hold_time_business_days)
    if not slowest.diffs_in_between:
        return (
            f"Slowest round was v{slowest.sent_version}->v{slowest.returned_version} "
            f"({slowest.hold_time_business_days:g} business days)."
        )
    busiest_diff = max(slowest.diffs_in_between, key=lambda d: d.changed_tokens)
    return (
        f"Slowest round was v{slowest.sent_version}->v{slowest.returned_version} "
        f"({slowest.hold_time_business_days:g} business days), coinciding with "
        f"{busiest_diff.changed_tokens} changed tokens between "
        f"v{busiest_diff.from_version}->v{busiest_diff.to_version}."
    )


def compute_turnaround_metrics(
    document_ref: DocumentRef, versions: list[VersionEvent], diffs: list[DiffResult]
) -> tuple[list[TurnaroundRound], list[Metric]]:
    rounds = detect_handoff_rounds(versions, diffs)
    if not rounds:
        return rounds, []

    hold_times = [r.hold_time_business_days for r in rounds]
    round_indices = [float(r.round_index) for r in rounds]
    slope = linear_trend_slope(round_indices, hold_times)
    direction = "flat"
    if slope > _TREND_FLAT_EPSILON_DAYS:
        direction = "up"
    elif slope < -_TREND_FLAT_EPSILON_DAYS:
        direction = "down"

    base_evidence = Evidence(
        doc_ids=[document_ref.document_id],
        timestamps=[r.sent_at for r in rounds] + [r.returned_at for r in rounds],
    )

    metrics = [
        Metric(
            name="counsel_turnaround_mean",
            value=round(mean(hold_times), 2),
            unit="business_days",
            direction="flat",
            evidence=base_evidence,
            note=f"Mean counsel hold time across {len(rounds)} round(s) on {document_ref.name}.",
        ),
        Metric(
            name="counsel_turnaround_median",
            value=round(median(hold_times), 2),
            unit="business_days",
            direction="flat",
            evidence=base_evidence,
            note=f"Median counsel hold time across {len(rounds)} round(s) on {document_ref.name}.",
        ),
        Metric(
            name="counsel_turnaround_trend",
            value=round(slope, 3),
            unit="business_days_per_round",
            direction=direction,
            evidence=base_evidence,
            note=_bottleneck_note(rounds),
        ),
    ]
    return rounds, metrics
