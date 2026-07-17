import json
from pathlib import Path

import pytest

from counsel_analytics import cli

FIXTURES = Path(__file__).parent / "fixtures"

# Language a named-individual psychological/personality profile would use.
# None of these should ever appear in generated output (guardrail check).
_FORBIDDEN_TERMS = [
    "passive-aggressive",
    "passive aggressive",
    "personality",
    "mindset",
    "psycholog",
]


@pytest.fixture()
def output_dir(tmp_path, monkeypatch):
    config_src = FIXTURES / "test_config.yaml"
    config = tmp_path / "config.yaml"
    out_dir = tmp_path / "output"
    config.write_text(
        config_src.read_text().replace("./data/output", str(out_dir)), encoding="utf-8"
    )
    return config, out_dir


def test_run_produces_reports_with_no_individual_profiling_language(output_dir):
    config, out_dir = output_dir
    raw_data_path = FIXTURES / "one_matter.json"

    written = cli.run(str(config), str(raw_data_path), matter_overrides=None)

    assert written, "expected at least one output file"
    for path in written:
        assert path.exists()

    md_files = [p for p in written if p.suffix == ".md"]
    assert len(md_files) == 1
    report_text = md_files[0].read_text(encoding="utf-8").lower()
    for term in _FORBIDDEN_TERMS:
        assert term not in report_text, f"forbidden term {term!r} found in report"

    json_files = [p for p in written if p.suffix == ".json"]
    assert len(json_files) == 1
    payload = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert payload["matter_ref"]["workspace_id"] == "LIB!1000"
    assert len(payload["version_events"]) == 5

    metric_names = {m["name"] for m in payload["metrics"]}
    assert "counsel_turnaround_mean" in metric_names
    assert "redline_density_mean" in metric_names


@pytest.fixture()
def phase2_output_dir(tmp_path):
    config_src = FIXTURES / "phase2_config.yaml"
    config = tmp_path / "config.yaml"
    out_dir = tmp_path / "output"
    config.write_text(
        config_src.read_text().replace("./data/output", str(out_dir)), encoding="utf-8"
    )
    return config, out_dir


def test_run_produces_clause_reargument_and_tone_sections(phase2_output_dir):
    config, out_dir = phase2_output_dir
    raw_data_path = FIXTURES / "phase2_matter.json"

    written = cli.run(str(config), str(raw_data_path), matter_overrides=None)

    md_files = [p for p in written if p.suffix == ".md"]
    assert len(md_files) == 1
    report_text = md_files[0].read_text(encoding="utf-8")
    report_text_lower = report_text.lower()

    assert "## Clause Re-argument" in report_text
    assert "## Tone / Escalation" in report_text
    for term in _FORBIDDEN_TERMS:
        assert term not in report_text_lower, f"forbidden term {term!r} found in report"

    clause_csv = out_dir / "clause_signals.csv"
    assert clause_csv.exists()
    assert "clause_reargument_pingpong" in clause_csv.read_text(encoding="utf-8")

    json_files = [p for p in written if p.suffix == ".json"]
    payload = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert len(payload["clause_signals"]) >= 1
    tone_metric_names = {m["name"] for m in payload["metrics"] if m["name"].startswith("tone_")}
    assert "tone_escalation_trend" in tone_metric_names


@pytest.fixture()
def zero_versions_output_dir(tmp_path):
    config_src = FIXTURES / "redline_zero_versions_config.yaml"
    config = tmp_path / "config.yaml"
    out_dir = tmp_path / "output"
    config.write_text(
        config_src.read_text().replace("./data/output", str(out_dir)), encoding="utf-8"
    )
    return config, out_dir


def test_run_warns_when_redline_document_enumerates_zero_versions(zero_versions_output_dir, caplog):
    # Regression test for the has_documents wiring bug: a redline-domain
    # matter with 1+ documents (list_documents non-empty) whose every
    # document enumerates zero version events (get_versions() -> []) must
    # still trigger ingest/correspond.py's "documents but no version
    # events" warning when driven through cli.run() end-to-end, not just
    # when correlate_correspondence() is called directly with
    # has_documents=True.
    config, out_dir = zero_versions_output_dir
    raw_data_path = FIXTURES / "redline_zero_versions_matter.json"

    with caplog.at_level("WARNING"):
        written = cli.run(str(config), str(raw_data_path), matter_overrides=None)

    assert written, "expected at least one output file"
    warning_messages = [r.message for r in caplog.records if r.levelname == "WARNING"]
    assert any("has documents but no version events" in m for m in warning_messages), (
        f"expected the correspond.py data-quality warning to fire; got: {warning_messages}"
    )


def _merge_raw_data(a: dict, b: dict) -> dict:
    return {key: {**a.get(key, {}), **b.get(key, {})} for key in set(a) | set(b)}


@pytest.fixture()
def two_matters_same_firm(tmp_path):
    # one_matter.json (LIB!1000, Jan) and phase2_matter.json (LIB!3000, Feb)
    # both use "Example Firm LLP" as the counsel domain, at different dates
    # -- exactly what a counterparty rollup needs.
    one_matter = json.loads((FIXTURES / "one_matter.json").read_text())
    phase2_matter = json.loads((FIXTURES / "phase2_matter.json").read_text())
    merged_raw = tmp_path / "merged_raw.json"
    merged_raw.write_text(json.dumps(_merge_raw_data(one_matter, phase2_matter)), encoding="utf-8")

    config_src = FIXTURES / "test_config.yaml"
    config = tmp_path / "config.yaml"
    out_dir = tmp_path / "output"
    config_text = config_src.read_text().replace("./data/output", str(out_dir))
    config_text = config_text.replace('matter_ids:\n  - "LIB!1000"', 'matter_ids:\n  - "LIB!1000"\n  - "LIB!3000"')
    config.write_text(config_text, encoding="utf-8")

    return config, out_dir, merged_raw


def test_run_produces_counterparty_rollup_across_two_matters(two_matters_same_firm):
    config, out_dir, merged_raw = two_matters_same_firm

    written = cli.run(str(config), str(merged_raw), matter_overrides=None)

    rollup_md = out_dir / "counterparty_rollups.md"
    assert rollup_md in written
    md_text = rollup_md.read_text(encoding="utf-8")
    assert "## Example Firm LLP" in md_text
    assert "LIB!1000" in md_text and "LIB!3000" in md_text
    for term in _FORBIDDEN_TERMS:
        assert term not in md_text.lower()

    csv_text = (out_dir / "firm_period_metrics.csv").read_text(encoding="utf-8")
    assert "Example Firm LLP" in csv_text
    assert "_firm_trend" in csv_text


def test_rollup_command_combines_separately_run_reports(two_matters_same_firm):
    config, out_dir, merged_raw = two_matters_same_firm
    cli.run(str(config), str(merged_raw), matter_overrides=None)

    report_paths = [str(out_dir / "LIB_1000.json"), str(out_dir / "LIB_3000.json")]
    written = cli.rollup(str(config), report_paths)

    assert len(written) == 3  # json, csv, markdown
    assert any(p.name == "counterparty_rollups.md" for p in written)
