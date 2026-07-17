"""`counsel-analytics` CLI: `run` (turnaround/volume/clause/tone analysis),
`packet` (condensed review packet), `signoff` (record a decision),
`verify-signoffs` (check the audit log's hash chain).

This module never calls an MCP tool itself. In `mcp_client: session` mode
(the only implemented mode), a Claude session with the iManage Work /
Microsoft 365 MCP tools connected fetches `get_workspace_profile` /
`get_container_children` / `get_document_versions` / `download_document` /
correspondence for the matters of interest, assembles them into the
`SessionMCPClient` raw_data shape (see `mcp/client.py`), and writes that to
a JSON file passed via `--raw-data`.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from counsel_analytics.config import load_settings
from counsel_analytics.diff.segment import align_clause_histories, segment_text
from counsel_analytics.diff.textdiff import diff_versions
from counsel_analytics.ingest.correspond import correlate_correspondence
from counsel_analytics.ingest.enumerate import enumerate_all
from counsel_analytics.ingest.extract import extract_version_text
from counsel_analytics.mcp.client import build_client
from counsel_analytics.metrics.aggregate import compute_counterparty_rollups, resolve_matter_firm
from counsel_analytics.metrics.reargument import compute_reargument_metrics
from counsel_analytics.metrics.tone import compute_tone_metrics
from counsel_analytics.metrics.turnaround import compute_turnaround_metrics
from counsel_analytics.metrics.volume import compute_volume_metrics
from counsel_analytics.models import MatterMetrics
from counsel_analytics.report.datamodel import MatterReportBundle, matter_slug, write_all
from counsel_analytics.report.generate import generate_markdown
from counsel_analytics.report.packet import build_review_packet, render_packet_markdown
from counsel_analytics.report.rollup import write_all_rollups
from counsel_analytics.signoff import (
    SignOffRecord,
    append_signoff,
    latest_signoff_for_matter,
    snapshot_hash,
    verify_chain,
)
from counsel_analytics.sources.compliance import ComplianceSourceAdapter
from counsel_analytics.sources.redline import RedlineSourceAdapter


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="counsel-analytics")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run", help="Run the turnaround/volume/clause-reargument/tone analysis"
    )
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

    packet_parser = subparsers.add_parser(
        "packet", help="Render a ~5-minute review packet from a report JSON"
    )
    packet_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    packet_parser.add_argument("--report", required=True, help="Path to a <slug>.json report written by `run`")
    packet_parser.add_argument(
        "--max-highlights", type=int, default=None, help="Override config packet.max_highlights"
    )
    packet_parser.add_argument("--out", default=None, help="Write packet markdown here (default: stdout)")

    signoff_parser = subparsers.add_parser(
        "signoff", help="Record an approve/flag/escalate decision against a report snapshot"
    )
    signoff_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    signoff_parser.add_argument("--report", required=True, help="Path to the <slug>.json report being signed off")
    signoff_parser.add_argument("--reviewer", required=True, help="Reviewer identity (email or id)")
    signoff_parser.add_argument("--decision", required=True, choices=["approve", "flag", "escalate"])
    signoff_parser.add_argument("--reason", required=True, help="Required justification")

    verify_parser = subparsers.add_parser(
        "verify-signoffs", help="Check the sign-off log's hash chain is intact"
    )
    verify_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")

    rollup_parser = subparsers.add_parser(
        "rollup", help="Compute a counterparty (firm) rollup across separately-run matter reports"
    )
    rollup_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    rollup_parser.add_argument(
        "--report",
        required=True,
        action="append",
        dest="reports",
        help="Path to a <slug>.json report written by `run` (repeatable, 2+ needed per firm)",
    )

    return parser


def run(config_path: str, raw_data_path: str, matter_overrides: list[str] | None) -> list[Path]:
    settings = load_settings(config_path)
    if matter_overrides:
        settings = settings.model_copy(update={"matter_ids": matter_overrides})

    raw_data = json.loads(Path(raw_data_path).read_text(encoding="utf-8"))
    client = build_client(settings.mcp_client, raw_data)
    source = ComplianceSourceAdapter(client, settings) if settings.domain == "compliance" else RedlineSourceAdapter(client, settings)

    output_dir = Path(settings.output_dir)
    cache_dir = output_dir / "_text_cache"
    written: list[Path] = []
    all_matter_metrics: list[MatterMetrics] = []

    for timeline in enumerate_all(source):
        version_events = []
        metrics = []
        clause_signals = []
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

            segments_by_version = {v.version_no: segment_text(texts[v.version_no], v.version_no) for v in versions}
            clause_histories = align_clause_histories(segments_by_version)
            reargument_metrics = compute_reargument_metrics(doc_timeline.document_ref, clause_histories, settings)

            rounds_by_document[doc_timeline.document_ref.document_id] = rounds
            metrics.extend(turnaround_metrics)
            metrics.extend(volume_metrics)
            clause_signals.extend(reargument_metrics)

        raw_threads = source.get_correspondence(timeline.matter_ref)
        correlated_threads, message_rounds = correlate_correspondence(raw_threads, version_events, settings)
        metrics.extend(compute_tone_metrics(timeline.matter_ref, correlated_threads, settings, rounds=message_rounds))

        matter_ref = timeline.matter_ref.model_copy(
            update={"firm": resolve_matter_firm(version_events, settings.internal_domains, settings.firm_domains)}
        )
        matter_metrics = MatterMetrics(
            matter_ref=matter_ref,
            version_events=version_events,
            metrics=metrics,
            clause_signals=clause_signals,
            generated_at=datetime.now(timezone.utc),
        )
        bundle = MatterReportBundle(matter_metrics=matter_metrics, rounds_by_document=rounds_by_document)

        paths = write_all(bundle, output_dir, settings.anonymize_authors)
        markdown_path = output_dir / f"{matter_slug(matter_metrics)}.md"
        markdown_path.write_text(generate_markdown(bundle), encoding="utf-8")

        written.extend(paths.values())
        written.append(markdown_path)
        all_matter_metrics.append(matter_metrics)
        print(f"Wrote report for matter {timeline.matter_ref.workspace_id} to {output_dir}")

    rollups = compute_counterparty_rollups(all_matter_metrics)
    if rollups:
        rollup_paths = write_all_rollups(rollups, output_dir)
        written.extend(rollup_paths.values())
        firms = ", ".join(r.firm for r in rollups)
        print(f"Wrote counterparty rollup for {firms} to {output_dir}")

    return written


def rollup(config_path: str, report_paths: list[str]) -> list[Path]:
    """Compute a counterparty rollup across matters that were `run()` in
    separate invocations (e.g. analyzed on different days). `run()` already
    does this automatically for matters processed together in one call —
    this is for combining reports generated separately.
    """
    settings = load_settings(config_path)
    output_dir = Path(settings.output_dir)

    all_matter_metrics = [
        MatterMetrics.model_validate_json(Path(p).read_text(encoding="utf-8")) for p in report_paths
    ]
    rollups = compute_counterparty_rollups(all_matter_metrics)
    if not rollups:
        print("No firm has 2+ of the given matters with a resolvable firm — nothing to roll up.")
        return []

    rollup_paths = write_all_rollups(rollups, output_dir)
    firms = ", ".join(r.firm for r in rollups)
    print(f"Wrote counterparty rollup for {firms} to {output_dir}")
    return list(rollup_paths.values())


def packet(
    config_path: str,
    report_path: str,
    max_highlights: int | None = None,
    out_path: str | None = None,
) -> str:
    settings = load_settings(config_path)
    matter_metrics = MatterMetrics.model_validate_json(Path(report_path).read_text(encoding="utf-8"))

    log_path = Path(settings.output_dir) / "signoffs.jsonl"
    prior = latest_signoff_for_matter(log_path, matter_metrics.matter_ref.workspace_id)

    review_packet = build_review_packet(
        matter_metrics,
        max_highlights=max_highlights if max_highlights is not None else settings.packet.max_highlights,
        min_abs_value=settings.packet.min_abs_value,
        prior_signoff=prior,
    )
    markdown = render_packet_markdown(review_packet)

    if out_path:
        Path(out_path).write_text(markdown, encoding="utf-8")
    else:
        print(markdown)
    return markdown


def signoff(
    config_path: str, report_path: str, reviewer: str, decision: str, reason: str
) -> SignOffRecord:
    if not reason.strip():
        raise ValueError("--reason is required and must be non-empty")

    settings = load_settings(config_path)
    matter_metrics = MatterMetrics.model_validate_json(Path(report_path).read_text(encoding="utf-8"))

    record = SignOffRecord(
        matter_workspace_id=matter_metrics.matter_ref.workspace_id,
        snapshot_hash=snapshot_hash(matter_metrics),
        decision=decision,
        reviewer=reviewer,
        reviewer_source="cli_flag",
        reason=reason,
        signed_at=datetime.now(timezone.utc),
    )
    log_path = Path(settings.output_dir) / "signoffs.jsonl"
    finalized = append_signoff(record, log_path)
    print(f"Recorded {decision} sign-off for {matter_metrics.matter_ref.workspace_id} by {reviewer}")
    return finalized


def verify_signoffs(config_path: str) -> tuple[bool, int | None]:
    settings = load_settings(config_path)
    log_path = Path(settings.output_dir) / "signoffs.jsonl"
    intact, bad_index = verify_chain(log_path)
    if intact:
        print(f"Sign-off log intact: {log_path}")
    else:
        print(f"Sign-off log TAMPERED at line {bad_index}: {log_path}")
    return intact, bad_index


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        run(args.config, args.raw_data, args.matters)
    elif args.command == "packet":
        packet(args.config, args.report, args.max_highlights, args.out)
    elif args.command == "signoff":
        signoff(args.config, args.report, args.reviewer, args.decision, args.reason)
    elif args.command == "verify-signoffs":
        verify_signoffs(args.config)
    elif args.command == "rollup":
        rollup(args.config, args.reports)


if __name__ == "__main__":
    main()
