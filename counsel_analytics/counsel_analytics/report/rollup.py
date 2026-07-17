"""JSON + flat CSV + Markdown output for cross-matter counterparty
rollups (Phase 3). Mirrors `report/datamodel.py`/`generate.py`'s
structure-vs-render split, but for `CounterpartyRollup` objects instead of
a single matter's `MatterMetrics`.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from pydantic import TypeAdapter

from counsel_analytics.models import CounterpartyRollup
from counsel_analytics.report.generate import _GUARDRAIL_NOTE, _metrics_table

_ROLLUP_LIST_ADAPTER = TypeAdapter(list[CounterpartyRollup])


def write_rollup_json(rollups: list[CounterpartyRollup], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "counterparty_rollups.json"
    payload = _ROLLUP_LIST_ADAPTER.dump_json(rollups, indent=2)
    path.write_bytes(payload)
    return path


def write_firm_period_metrics_csv(rollups: list[CounterpartyRollup], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "firm_period_metrics.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["firm", "metric_name", "value", "unit", "direction", "note", "matters"])
        for rollup in rollups:
            matter_ids = ";".join(m.workspace_id for m in rollup.matters)
            for metric in rollup.metrics:
                writer.writerow(
                    [rollup.firm, metric.name, metric.value, metric.unit, metric.direction, metric.note or "", matter_ids]
                )
    return path


def render_rollup_markdown(rollups: list[CounterpartyRollup]) -> str:
    lines = ["# Counterparty Rollup Report", ""]

    if not rollups:
        lines.append(
            "_No firm has 2+ matters with a resolvable firm yet — nothing to roll up._"
        )
    for rollup in rollups:
        lines.append(f"## {rollup.firm}")
        lines.append("")
        lines.append(f"**Matters ({len(rollup.matters)}):** " + ", ".join(m.workspace_id for m in rollup.matters))
        lines.append("")
        if not rollup.metrics:
            lines.append("_No metric appears on 2+ of this firm's matters yet — nothing to trend._")
        else:
            lines.extend(_metrics_table(rollup.metrics))
        lines.append("")

    lines.extend(["", "## Guardrails", "", _GUARDRAIL_NOTE, ""])
    return "\n".join(lines)


def write_all_rollups(rollups: list[CounterpartyRollup], output_dir: Path) -> dict[str, Path]:
    markdown_path = output_dir / "counterparty_rollups.md"
    markdown_path.write_text(render_rollup_markdown(rollups), encoding="utf-8")
    return {
        "rollup_json": write_rollup_json(rollups, output_dir),
        "firm_period_metrics_csv": write_firm_period_metrics_csv(rollups, output_dir),
        "rollup_markdown": markdown_path,
    }
