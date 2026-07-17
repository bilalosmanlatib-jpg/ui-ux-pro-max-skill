"""The review packet: a ~5-minute-read artifact, distinct from the full
Markdown report (`report/generate.py`). Takes `MatterMetrics` directly
(not `MatterReportBundle`, which carries the redline-specific
`TurnaroundRound` type) so this stays generic enough to work unchanged if
a second, non-legal domain is added later.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

from counsel_analytics.models import MatterMetrics, MatterRef, Metric
from counsel_analytics.report.generate import _GUARDRAIL_NOTE
from counsel_analytics.signoff import SignOffRecord, snapshot_hash


class PacketHighlight(BaseModel):
    name: str
    value: float
    unit: str
    direction: Literal["up", "down"]
    note: Optional[str]
    document_id: Optional[str]
    magnitude: float


class ReviewPacket(BaseModel):
    matter_ref: MatterRef
    snapshot_hash: str
    generated_at: datetime
    highlights: list[PacketHighlight]
    shown_count: int
    omitted_nonflat_count: int
    flat_count: int
    total_metric_count: int
    prior_signoff: Optional[SignOffRecord] = None
    stale: bool = False


def select_highlights(
    metrics: list[Metric], *, max_highlights: int, min_abs_value: float
) -> tuple[list[PacketHighlight], int, int]:
    """Returns (shown_highlights, omitted_nonflat_count, flat_count).

    Ranking is by abs(value) descending — a coarse, unit-naive salience
    proxy (a 3-day turnaround and a 0.4 change-ratio aren't literally
    comparable). No silent caps: every metric that doesn't make it into
    `shown_highlights` is accounted for in one of the two counts.
    """
    non_flat = [m for m in metrics if m.direction != "flat"]
    flat_count = len(metrics) - len(non_flat)

    eligible = [m for m in non_flat if abs(m.value) >= min_abs_value]
    below_threshold_count = len(non_flat) - len(eligible)

    ranked = sorted(eligible, key=lambda m: abs(m.value), reverse=True)
    shown = ranked[:max_highlights]
    omitted_nonflat_count = (len(ranked) - len(shown)) + below_threshold_count

    highlights = [
        PacketHighlight(
            name=m.name,
            value=m.value,
            unit=m.unit,
            direction=m.direction,
            note=m.note,
            document_id=m.evidence.doc_ids[0] if m.evidence.doc_ids else None,
            magnitude=abs(m.value),
        )
        for m in shown
    ]
    return highlights, omitted_nonflat_count, flat_count


def build_review_packet(
    matter_metrics: MatterMetrics,
    *,
    max_highlights: int = 8,
    min_abs_value: float = 0.0,
    prior_signoff: Optional[SignOffRecord] = None,
) -> ReviewPacket:
    all_metrics = matter_metrics.metrics + matter_metrics.clause_signals
    highlights, omitted_nonflat_count, flat_count = select_highlights(
        all_metrics, max_highlights=max_highlights, min_abs_value=min_abs_value
    )
    current_hash = snapshot_hash(matter_metrics)
    stale = prior_signoff is not None and prior_signoff.snapshot_hash != current_hash

    return ReviewPacket(
        matter_ref=matter_metrics.matter_ref,
        snapshot_hash=current_hash,
        generated_at=matter_metrics.generated_at,
        highlights=highlights,
        shown_count=len(highlights),
        omitted_nonflat_count=omitted_nonflat_count,
        flat_count=flat_count,
        total_metric_count=len(all_metrics),
        prior_signoff=prior_signoff,
        stale=stale,
    )


def _signoff_banner(packet: ReviewPacket) -> str:
    if packet.prior_signoff is None:
        return "_No sign-off recorded yet for this matter._"
    s = packet.prior_signoff
    base = f"Last signed off {s.signed_at.isoformat()} by {s.reviewer} — **{s.decision}**."
    if packet.stale:
        return base + "\n\n⚠ **This matter has newer evidence than its last sign-off — re-review required.**"
    return base


def render_packet_markdown(packet: ReviewPacket) -> str:
    lines = [
        f"# Review Packet — {packet.matter_ref.display_name}",
        "",
        f"**Generated:** {packet.generated_at.isoformat()}",
        f"**Snapshot:** `{packet.snapshot_hash[:19]}...`",
        "",
        _signoff_banner(packet),
        "",
        "## Highlights",
        "",
    ]

    if not packet.highlights:
        if packet.total_metric_count == 0:
            lines.append("_No metrics available for this matter yet._")
        else:
            lines.append(
                f"_No notable movements this snapshot; {packet.flat_count} steady "
                f"metric(s) in the full report._"
            )
    else:
        lines.append("| metric | value | unit | direction |")
        lines.append("| --- | --- | --- | --- |")
        for h in packet.highlights:
            arrow = "↑" if h.direction == "up" else "↓"
            lines.append(f"| {h.name} | {h.value} | {h.unit} | {arrow} {h.direction} |")
        for h in packet.highlights:
            if h.note:
                lines.append(f"\n> {h.note}")

    lines.append("")
    lines.append(
        f"_{packet.omitted_nonflat_count} more trending metric(s) and "
        f"{packet.flat_count} steady metric(s) not shown — see the full report._"
    )
    lines.extend(["", "## Guardrails", "", _GUARDRAIL_NOTE, ""])
    return "\n".join(lines)
