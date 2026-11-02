from counsel_analytics.mcp.billing import parse_time_entries


def test_parse_time_entries_handles_varied_key_shapes():
    raw = [
        {"timekeeper": "Jane Doe", "role": "Partner", "date": "2026-02-04", "hours": 2.5, "rate": 650, "amount": 1625, "currency": "GBP", "narrative": "Review and respond to lender email."},
        {"fee_earner": "John Smith", "entry_date": "2026-02-05T00:00:00Z", "duration_hours": "1.0", "description": "Call with client."},
    ]
    entries = parse_time_entries("LIB!3000", raw)

    assert len(entries) == 2
    assert entries[0].timekeeper_name == "Jane Doe"
    assert entries[0].timekeeper_role == "Partner"
    assert entries[0].hours == 2.5
    assert entries[0].amount == 1625
    assert entries[0].currency == "GBP"
    assert entries[0].narrative == "Review and respond to lender email."
    assert entries[1].timekeeper_name == "John Smith"
    assert entries[1].hours == 1.0
    # sorted chronologically
    assert entries[0].entry_date < entries[1].entry_date


def test_parse_time_entries_skips_unattributable_lines():
    raw = [
        {"date": "2026-02-04", "hours": 2.5, "narrative": "no name given"},
        {"timekeeper": "Jane Doe", "date": "2026-02-04", "narrative": "no hours given"},
        {"timekeeper": "Jane Doe", "date": "2026-02-04", "hours": 1.0, "narrative": "valid"},
    ]
    entries = parse_time_entries("LIB!3000", raw)
    assert len(entries) == 1
    assert entries[0].narrative == "valid"


def test_parse_time_entries_empty_input():
    assert parse_time_entries("LIB!3000", []) == []


def test_parse_time_entries_carries_matter_and_source_document_id():
    raw = [{"timekeeper": "Jane Doe", "date": "2026-02-04", "hours": 1.0}]
    entries = parse_time_entries("LIB!3000", raw, source_document_id="LIB!9999.1")
    assert entries[0].matter_id == "LIB!3000"
    assert entries[0].source_document_id == "LIB!9999.1"


def test_parse_time_entries_picks_up_optional_period_start():
    raw = [
        {"timekeeper": "Jane Doe", "date": "2026-02-28", "period_start": "2026-02-01", "hours": 20.0},
        {"timekeeper": "John Smith", "date": "2026-02-04", "hours": 1.0},
    ]
    entries = parse_time_entries("LIB!3000", raw)
    by_name = {e.timekeeper_name: e for e in entries}
    assert by_name["Jane Doe"].period_start.date().isoformat() == "2026-02-01"
    assert by_name["John Smith"].period_start is None
