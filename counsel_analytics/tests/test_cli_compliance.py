import json
from pathlib import Path

import pytest

from counsel_analytics import cli

FIXTURES = Path(__file__).parent / "fixtures"

_FORBIDDEN_TERMS = ["passive-aggressive", "passive aggressive", "personality", "mindset", "psycholog"]


@pytest.fixture()
def compliance_output_dir(tmp_path):
    config_src = FIXTURES / "compliance_config.yaml"
    config = tmp_path / "config.yaml"
    out_dir = tmp_path / "output"
    config.write_text(config_src.read_text().replace("./data/output", str(out_dir)), encoding="utf-8")
    return config, out_dir


def test_run_compliance_domain_produces_tone_metrics_with_no_documents(compliance_output_dir):
    config, out_dir = compliance_output_dir
    raw_data_path = FIXTURES / "compliance_matter.json"

    written = cli.run(str(config), str(raw_data_path), matter_overrides=None)

    md_files = [p for p in written if p.suffix == ".md"]
    assert len(md_files) == 1
    report_text = md_files[0].read_text(encoding="utf-8")
    report_text_lower = report_text.lower()

    assert "## Tone / Escalation" in report_text
    assert "tone_escalation_trend" in report_text
    for term in _FORBIDDEN_TERMS:
        assert term not in report_text_lower, f"forbidden term {term!r} found in report"

    json_files = [p for p in written if p.suffix == ".json"]
    payload = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert payload["version_events"] == []
    assert payload["clause_signals"] == []
    tone_metric_names = {m["name"] for m in payload["metrics"] if m["name"].startswith("tone_")}
    assert "tone_escalation_trend" in tone_metric_names

    escalation_trend = next(m for m in payload["metrics"] if m["name"] == "tone_escalation_trend")
    assert escalation_trend["direction"] == "up"


def test_run_compliance_domain_resolves_firm_from_correspondence_and_produces_rollup(tmp_path):
    # Compliance matters have no document version events at all, so firm
    # resolution can only come from correspondence -- this is the case
    # sources/compliance.py's "resolved later from correspondence" comment
    # describes. Two matters correspond with the same regulator domain, so
    # a firm should resolve for both and a counterparty rollup should be
    # produced (previously: firm always stayed None for this domain, and
    # the rollup was permanently dead).
    config_src = FIXTURES / "compliance_config_two_matters.yaml"
    out_dir = tmp_path / "output"
    config = tmp_path / "config.yaml"
    config.write_text(config_src.read_text().replace("./data/output", str(out_dir)), encoding="utf-8")
    raw_data_path = FIXTURES / "compliance_two_matters.json"

    written = cli.run(str(config), str(raw_data_path), matter_overrides=None)

    json_files = [p for p in written if p.suffix == ".json" and p.name != "counterparty_rollups.json"]
    assert len(json_files) == 2
    for p in json_files:
        payload = json.loads(p.read_text(encoding="utf-8"))
        assert payload["matter_ref"]["firm"] == "FCA"

    rollup_json = out_dir / "counterparty_rollups.json"
    assert rollup_json.exists()
    rollups = json.loads(rollup_json.read_text(encoding="utf-8"))
    assert len(rollups) == 1
    assert rollups[0]["firm"] == "FCA"
    assert {m["workspace_id"] for m in rollups[0]["matters"]} == {"LIB!5000", "LIB!6000"}
