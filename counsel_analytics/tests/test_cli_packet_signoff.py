from pathlib import Path

import pytest

from counsel_analytics import cli

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def output_dir(tmp_path):
    config_src = FIXTURES / "test_config.yaml"
    config = tmp_path / "config.yaml"
    out_dir = tmp_path / "output"
    config.write_text(
        config_src.read_text().replace("./data/output", str(out_dir)), encoding="utf-8"
    )
    return config, out_dir


def test_build_parser_parses_new_subcommands():
    parser = cli._build_parser()

    args = parser.parse_args(["packet", "--report", "r.json"])
    assert args.command == "packet"
    assert args.report == "r.json"

    args = parser.parse_args(
        ["signoff", "--report", "r.json", "--reviewer", "a@x.com", "--decision", "approve", "--reason", "ok"]
    )
    assert args.command == "signoff"
    assert args.decision == "approve"

    args = parser.parse_args(["verify-signoffs"])
    assert args.command == "verify-signoffs"


def test_signoff_rejects_empty_reason(output_dir):
    config, out_dir = output_dir
    raw_data_path = FIXTURES / "one_matter.json"
    cli.run(str(config), str(raw_data_path), matter_overrides=None)
    report_path = out_dir / "LIB_1000.json"

    with pytest.raises(ValueError):
        cli.signoff(str(config), str(report_path), reviewer="a@ninetyone.com", decision="approve", reason="   ")


def test_packet_signoff_verify_end_to_end(output_dir):
    config, out_dir = output_dir
    raw_data_path = FIXTURES / "one_matter.json"
    cli.run(str(config), str(raw_data_path), matter_overrides=None)
    report_path = out_dir / "LIB_1000.json"

    before = cli.packet(str(config), str(report_path))
    assert "No sign-off recorded yet" in before

    record = cli.signoff(
        str(config), str(report_path), reviewer="jane.doe@ninetyone.com", decision="approve", reason="Looks fine."
    )
    assert record.record_hash is not None

    after = cli.packet(str(config), str(report_path))
    assert "jane.doe@ninetyone.com" in after
    assert "**approve**" in after
    assert "re-review required" not in after

    intact, bad_index = cli.verify_signoffs(str(config))
    assert intact is True
    assert bad_index is None
