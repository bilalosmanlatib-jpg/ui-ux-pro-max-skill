import json
from datetime import datetime, timezone

from counsel_analytics.models import CounterpartyRollup, Evidence, MatterRef, Metric
from counsel_analytics.report.rollup import render_rollup_markdown, write_all_rollups, write_firm_period_metrics_csv

_GENERATED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _rollup(firm="Example Firm LLP", with_metrics=True) -> CounterpartyRollup:
    matters = [
        MatterRef(library="LIB", workspace_id="LIB!1000", display_name="M1", firm=firm),
        MatterRef(library="LIB", workspace_id="LIB!3000", display_name="M2", firm=firm),
    ]
    metrics = []
    if with_metrics:
        metrics = [
            Metric(
                name="counsel_turnaround_mean_firm_trend",
                value=-1.5,
                unit="business_days_per_matter",
                direction="down",
                evidence=Evidence(timestamps=[], quotes=["LIB!1000 (2026-01-01): 5.0", "LIB!3000 (2026-02-01): 2.0"]),
                note="Trend note, hypothesis-level.",
            )
        ]
    return CounterpartyRollup(firm=firm, matters=matters, metrics=metrics, generated_at=_GENERATED_AT)


def test_render_rollup_markdown_includes_firm_matters_and_guardrail():
    md = render_rollup_markdown([_rollup()])
    assert "## Example Firm LLP" in md
    assert "LIB!1000, LIB!3000" in md
    assert "counsel_turnaround_mean_firm_trend" in md
    assert "Trend note, hypothesis-level." in md
    assert "## Guardrails" in md


def test_render_rollup_markdown_empty_rollups_list():
    md = render_rollup_markdown([])
    assert "nothing to roll up" in md.lower()


def test_render_rollup_markdown_firm_with_no_trendable_metrics():
    md = render_rollup_markdown([_rollup(with_metrics=False)])
    assert "nothing to trend" in md.lower()


def test_write_firm_period_metrics_csv_columns_and_rows(tmp_path):
    path = write_firm_period_metrics_csv([_rollup()], tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "firm,metric_name,value,unit,direction,note,matters" in text
    assert "Example Firm LLP,counsel_turnaround_mean_firm_trend" in text
    assert "LIB!1000;LIB!3000" in text


def test_write_all_rollups_writes_json_csv_and_markdown(tmp_path):
    paths = write_all_rollups([_rollup()], tmp_path)
    assert set(paths.keys()) == {"rollup_json", "firm_period_metrics_csv", "rollup_markdown"}
    for path in paths.values():
        assert path.exists()

    payload = json.loads(paths["rollup_json"].read_text(encoding="utf-8"))
    assert payload[0]["firm"] == "Example Firm LLP"
    assert len(payload[0]["matters"]) == 2
