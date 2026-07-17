from datetime import datetime, timezone

from counsel_analytics.models import Evidence, MatterMetrics, MatterRef, Metric
from counsel_analytics.signoff import (
    SignOffRecord,
    append_signoff,
    latest_signoff_for_matter,
    snapshot_hash,
    verify_chain,
)

MATTER_REF = MatterRef(library="LIB", workspace_id="LIB!1000", display_name="Test Matter")


def _matter_metrics(generated_at: datetime, value: float = -1.0) -> MatterMetrics:
    return MatterMetrics(
        matter_ref=MATTER_REF,
        version_events=[],
        metrics=[
            Metric(
                name="counsel_turnaround_trend",
                value=value,
                unit="business_days_per_round",
                direction="down",
                evidence=Evidence(doc_ids=["LIB!2001"]),
                note="test note",
            )
        ],
        generated_at=generated_at,
    )


def _record(**overrides) -> SignOffRecord:
    defaults = dict(
        matter_workspace_id="LIB!1000",
        snapshot_hash="sha256:deadbeef",
        decision="approve",
        reviewer="jane.doe@ninetyone.com",
        reason="looks fine",
        signed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return SignOffRecord(**defaults)


def test_snapshot_hash_stable_across_generated_at():
    a = _matter_metrics(datetime(2026, 1, 1, tzinfo=timezone.utc))
    b = _matter_metrics(datetime(2026, 6, 1, tzinfo=timezone.utc))
    assert snapshot_hash(a) == snapshot_hash(b)


def test_snapshot_hash_sensitive_to_metric_change():
    a = _matter_metrics(datetime(2026, 1, 1, tzinfo=timezone.utc), value=-1.0)
    b = _matter_metrics(datetime(2026, 1, 1, tzinfo=timezone.utc), value=-2.0)
    assert snapshot_hash(a) != snapshot_hash(b)


def test_append_signoff_appends_one_line_and_preserves_prior_bytes(tmp_path):
    log_path = tmp_path / "signoffs.jsonl"
    first = append_signoff(_record(reviewer="a@ninetyone.com"), log_path)
    prior_bytes = log_path.read_bytes()

    second = append_signoff(_record(reviewer="b@ninetyone.com"), log_path)

    assert log_path.read_bytes().startswith(prior_bytes)
    assert second.prev_record_hash == first.record_hash
    assert first.prev_record_hash is None


def test_verify_chain_intact_on_untouched_log(tmp_path):
    log_path = tmp_path / "signoffs.jsonl"
    append_signoff(_record(), log_path)
    append_signoff(_record(reviewer="second@ninetyone.com"), log_path)

    intact, bad_index = verify_chain(log_path)
    assert intact is True
    assert bad_index is None


def test_verify_chain_detects_tampered_line(tmp_path):
    log_path = tmp_path / "signoffs.jsonl"
    append_signoff(_record(), log_path)
    append_signoff(_record(reviewer="second@ninetyone.com"), log_path)

    lines = log_path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace("approve", "escalate")
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    intact, bad_index = verify_chain(log_path)
    assert intact is False
    assert bad_index == 0


def test_verify_chain_on_missing_log_is_trivially_intact(tmp_path):
    intact, bad_index = verify_chain(tmp_path / "does_not_exist.jsonl")
    assert intact is True
    assert bad_index is None


def test_latest_signoff_for_matter_returns_newest(tmp_path):
    log_path = tmp_path / "signoffs.jsonl"
    append_signoff(_record(signed_at=datetime(2026, 1, 1, tzinfo=timezone.utc), decision="flag"), log_path)
    append_signoff(_record(signed_at=datetime(2026, 2, 1, tzinfo=timezone.utc), decision="approve"), log_path)

    latest = latest_signoff_for_matter(log_path, "LIB!1000")
    assert latest.decision == "approve"


def test_latest_signoff_for_matter_returns_none_when_absent(tmp_path):
    assert latest_signoff_for_matter(tmp_path / "missing.jsonl", "LIB!1000") is None
