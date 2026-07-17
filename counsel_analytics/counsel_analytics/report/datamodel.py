"""JSON + flat CSV output for a matter's metrics.

CSVs are for BI tools; the JSON is the canonical, fully-evidenced record.
`firm_period_metrics.csv` lands with Phase 3 (counterparty rollup) once
there's real data to put in it.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from pydantic import BaseModel

from counsel_analytics.metrics.turnaround import TurnaroundRound
from counsel_analytics.models import MatterMetrics


class MatterReportBundle(BaseModel):
    matter_metrics: MatterMetrics
    rounds_by_document: dict[str, list[TurnaroundRound]]


def _anonymize(author_id: str, anonymize: bool) -> str:
    if not anonymize:
        return author_id
    digest = hashlib.sha256(author_id.encode("utf-8")).hexdigest()[:10]
    return f"author-{digest}"


def matter_slug(matter_metrics: MatterMetrics) -> str:
    return matter_metrics.matter_ref.workspace_id.replace("!", "_")


def write_json(bundle: MatterReportBundle, output_dir: Path, anonymize_authors: bool) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = bundle.matter_metrics.model_copy(deep=True)
    for event in payload.version_events:
        event.author_id = _anonymize(event.author_id, anonymize_authors)
    path = output_dir / f"{matter_slug(bundle.matter_metrics)}.json"
    path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
    return path


def write_version_events_csv(
    bundle: MatterReportBundle, output_dir: Path, anonymize_authors: bool
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "version_events.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["document_id_versioned", "version_no", "author_id", "author_side", "timestamp", "size_bytes", "imanage_comment"]
        )
        for event in bundle.matter_metrics.version_events:
            writer.writerow(
                [
                    event.document_id_versioned,
                    event.version_no,
                    _anonymize(event.author_id, anonymize_authors),
                    event.author_side,
                    event.timestamp.isoformat(),
                    event.size_bytes or "",
                    event.imanage_comment or "",
                ]
            )
    return path


def write_turnaround_rounds_csv(bundle: MatterReportBundle, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "turnaround_rounds.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["document_id", "round_index", "sent_version", "sent_at", "returned_version", "returned_at", "hold_time_business_days"]
        )
        for document_id, rounds in bundle.rounds_by_document.items():
            for r in rounds:
                writer.writerow(
                    [
                        document_id,
                        r.round_index,
                        r.sent_version,
                        r.sent_at.isoformat(),
                        r.returned_version,
                        r.returned_at.isoformat(),
                        r.hold_time_business_days,
                    ]
                )
    return path


def write_matter_metrics_csv(bundle: MatterReportBundle, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "matter_metrics.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["matter_workspace_id", "metric_name", "value", "unit", "direction", "note"])
        for metric in bundle.matter_metrics.metrics:
            writer.writerow(
                [
                    bundle.matter_metrics.matter_ref.workspace_id,
                    metric.name,
                    metric.value,
                    metric.unit,
                    metric.direction,
                    metric.note or "",
                ]
            )
    return path


def write_clause_signals_csv(bundle: MatterReportBundle, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "clause_signals.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["document_id", "clause_id", "metric_name", "value", "unit", "direction", "note"])
        for metric in bundle.matter_metrics.clause_signals:
            writer.writerow(
                [
                    metric.evidence.doc_ids[0] if metric.evidence.doc_ids else "",
                    metric.evidence.clause_ids[0] if metric.evidence.clause_ids else "",
                    metric.name,
                    metric.value,
                    metric.unit,
                    metric.direction,
                    metric.note or "",
                ]
            )
    return path


def write_all(bundle: MatterReportBundle, output_dir: Path, anonymize_authors: bool) -> dict[str, Path]:
    return {
        "json": write_json(bundle, output_dir, anonymize_authors),
        "version_events_csv": write_version_events_csv(bundle, output_dir, anonymize_authors),
        "turnaround_rounds_csv": write_turnaround_rounds_csv(bundle, output_dir),
        "matter_metrics_csv": write_matter_metrics_csv(bundle, output_dir),
        "clause_signals_csv": write_clause_signals_csv(bundle, output_dir),
    }
