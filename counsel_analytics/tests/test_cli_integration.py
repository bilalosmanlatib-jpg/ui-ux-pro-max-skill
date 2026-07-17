import json
import shutil
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
