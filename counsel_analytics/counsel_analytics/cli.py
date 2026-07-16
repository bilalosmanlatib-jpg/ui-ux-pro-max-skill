"""`counsel-analytics run` — the Phase 1 MVP entry point.

This module never calls an MCP tool itself. In `mcp_client: session` mode
(the only implemented mode), a Claude session with the iManage Work MCP
tools connected fetches `get_workspace_profile` / `get_container_children`
/ `get_document_versions` / `download_document` for the matters of
interest, assembles them into the `SessionMCPClient` raw_data shape (see
`mcp/client.py`), and writes that to a JSON file passed via `--raw-data`.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from counsel_analytics.config import load_settings
from counsel_analytics.diff.textdiff import diff_versions
from counsel_analytics.ingest.enumerate import enumerate_all
from counsel_analytics.ingest.extract import extract_version_text
from counsel_analytics.mcp.client import build_client
from counsel_analytics.metrics.turnaround import compute_turnaround_metrics
from counsel_analytics.metrics.volume import compute_volume_metrics
from counsel_analytics.models import MatterMetrics
from counsel_analytics.report.datamodel import MatterReportBundle, matter_slug, write_all
from counsel_analytics.report.generate import generate_markdown
from counsel_analytics.sources.redline import RedlineSourceAdapter


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="counsel-analytics")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the Phase 1 turnaround/volume analysis")
    run_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    run_parser.add_argument(
        "--raw-data",
        required=True,
        help="Path to a JSON file with pre-fetched MCP responses (SessionMCPClient shape)",
    )
    run_parser.add_argument(
        "--matter",
        action="append",
        dest="matters",
        help="Override matter_ids from config (repeatable)",
    )
    return parser


def run(config_path: str, raw_data_path: str, matter_overrides: list[str] | None) -> list[Path]:
    settings = load_settings(config_path)
    if matter_overrides:
        settings = settings.model_copy(update={"matter_ids": matter_overrides})

    raw_data = json.loads(Path(raw_data_path).read_text(encoding="utf-8"))
    client = build_client(settings.mcp_client, raw_data)
    source = RedlineSourceAdapter(client, settings)

    output_dir = Path(settings.output_dir)
    cache_dir = output_dir / "_text_cache"
    written: list[Path] = []

    for timeline in enumerate_all(source):
        version_events = []
        metrics = []
        rounds_by_document: dict[str, list] = {}

        for doc_timeline in timeline.documents:
            versions = doc_timeline.versions
            version_events.extend(versions)

            texts = {v.version_no: extract_version_text(source, v, cache_dir) for v in versions}
            diffs = [
                diff_versions(a.version_no, b.version_no, texts[a.version_no], texts[b.version_no])
                for a, b in zip(versions, versions[1:])
            ]

            rounds, turnaround_metrics = compute_turnaround_metrics(
                doc_timeline.document_ref, versions, diffs
            )
            volume_metrics = compute_volume_metrics(doc_timeline.document_ref, diffs)

            rounds_by_document[doc_timeline.document_ref.document_id] = rounds
            metrics.extend(turnaround_metrics)
            metrics.extend(volume_metrics)

        matter_metrics = MatterMetrics(
            matter_ref=timeline.matter_ref,
            version_events=version_events,
            metrics=metrics,
            clause_signals=[],
            generated_at=datetime.now(timezone.utc),
        )
        bundle = MatterReportBundle(matter_metrics=matter_metrics, rounds_by_document=rounds_by_document)

        paths = write_all(bundle, output_dir, settings.anonymize_authors)
        markdown_path = output_dir / f"{matter_slug(matter_metrics)}.md"
        markdown_path.write_text(generate_markdown(bundle), encoding="utf-8")

        written.extend(paths.values())
        written.append(markdown_path)
        print(f"Wrote report for matter {timeline.matter_ref.workspace_id} to {output_dir}")

    return written


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        run(args.config, args.raw_data, args.matters)


if __name__ == "__main__":
    main()
