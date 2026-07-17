"""Render an explainable Markdown report from a `MatterReportBundle`.

Every stated number comes straight from a `Metric.value`/`Metric.note` — the
report never states anything the underlying `Evidence` can't back up, and it
never names an individual (guardrail: aggregate matter/document-level
analytics only).
"""

from __future__ import annotations

from collections import defaultdict

from counsel_analytics.models import Metric
from counsel_analytics.report.datamodel import MatterReportBundle

_TURNAROUND_PREFIX = "counsel_turnaround"
_VOLUME_PREFIX = "redline_density"
_REARGUMENT_PREFIX = "clause_reargument"
_TONE_PREFIX = "tone_"

_GUARDRAIL_NOTE = (
    "All metrics in this report are aggregated at the document/matter level. "
    "None of them identify or characterize a named individual's behavior or "
    "state of mind — they describe patterns in a document thread with a "
    "counterparty over time."
)


def _metrics_by_document(metrics: list[Metric]) -> dict[str, list[Metric]]:
    grouped: dict[str, list[Metric]] = defaultdict(list)
    for metric in metrics:
        doc_id = metric.evidence.doc_ids[0] if metric.evidence.doc_ids else "unknown-document"
        grouped[doc_id].append(metric)
    return grouped


def _metrics_table(metrics: list[Metric]) -> list[str]:
    lines = ["| metric | value | unit | direction |", "| --- | --- | --- | --- |"]
    for m in metrics:
        lines.append(f"| {m.name} | {m.value} | {m.unit} | {m.direction} |")
    for m in metrics:
        if m.note:
            lines.append(f"\n> {m.note}")
    return lines


def generate_markdown(bundle: MatterReportBundle) -> str:
    matter = bundle.matter_metrics.matter_ref
    lines = [
        f"# Counsel Analytics Report — {matter.display_name}",
        "",
        f"**Generated:** {bundle.matter_metrics.generated_at.isoformat()}",
        f"**Matter:** {matter.workspace_id} "
        f"(client: {matter.client_id or '—'}, matter ref: {matter.matter_id or '—'})",
        f"**Documents with version history:** {len({e.document_id_versioned.rsplit('.', 1)[0] for e in bundle.matter_metrics.version_events})}",
        f"**Total version events:** {len(bundle.matter_metrics.version_events)}",
        "",
        "## Turnaround",
        "",
    ]

    turnaround_by_doc = _metrics_by_document(
        [m for m in bundle.matter_metrics.metrics if m.name.startswith(_TURNAROUND_PREFIX)]
    )
    if not turnaround_by_doc:
        lines.append("_No internal→counsel→internal hand-off rounds detected._")
    for doc_id, metrics in turnaround_by_doc.items():
        lines.append(f"### {doc_id}")
        lines.extend(_metrics_table(metrics))
        lines.append("")

    lines.extend(["", "## Redline Volume & Density", ""])
    volume_by_doc = _metrics_by_document(
        [m for m in bundle.matter_metrics.metrics if m.name.startswith(_VOLUME_PREFIX)]
    )
    if not volume_by_doc:
        lines.append("_No version-to-version diffs available._")
    for doc_id, metrics in volume_by_doc.items():
        lines.append(f"### {doc_id}")
        lines.extend(_metrics_table(metrics))
        lines.append("")

    lines.extend(["", "## Clause Re-argument", ""])
    reargument_by_doc = _metrics_by_document(bundle.matter_metrics.clause_signals)
    if not reargument_by_doc:
        lines.append("_No clauses re-argued across the configured round threshold._")
    for doc_id, metrics in reargument_by_doc.items():
        lines.append(f"### {doc_id}")
        lines.extend(_metrics_table(metrics))
        lines.append("")

    lines.extend(["", "## Tone / Escalation", ""])
    tone_metrics = [m for m in bundle.matter_metrics.metrics if m.name.startswith(_TONE_PREFIX)]
    if not tone_metrics:
        lines.append("_No correspondence available for tone analysis._")
    else:
        # Matter-scoped (doc_ids=[]) — rendered as one flat table, not grouped
        # per-document like turnaround/volume/reargument above.
        lines.extend(_metrics_table(tone_metrics))
        lines.append("")

    lines.extend(["", "## Guardrails", "", _GUARDRAIL_NOTE, ""])
    return "\n".join(lines)
