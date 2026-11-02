from counsel_analytics.mcp.calls import parse_call_records


def test_parse_call_records_handles_varied_key_shapes():
    raw = [
        {
            "start": "2026-03-02T09:00:00Z",
            "end": "2026-03-02T09:30:00Z",
            "subject": "AfDB Facility S call",
            "attendees": ["henry.newton-savage@cliffordchance.com", {"email": "bilal.osmanlatib@ninetyone.com"}],
            "speakingSeconds": {"bilal.osmanlatib@ninetyone.com": 820.0, "henry.newton-savage@cliffordchance.com": 12.0},
        },
        {
            "startDateTime": "2026-03-03T10:00:00Z",
            "endDateTime": "2026-03-03T10:15:00Z",
            "title": "Quick check-in",
            "participants": ["jane.doe@ninetyone.com"],
        },
    ]
    calls = parse_call_records("LIB!3000", raw)

    assert len(calls) == 2
    assert calls[0].subject == "AfDB Facility S call"
    assert "henry.newton-savage@cliffordchance.com" in calls[0].attendees
    assert "bilal.osmanlatib@ninetyone.com" in calls[0].attendees
    assert calls[0].speaking_seconds["henry.newton-savage@cliffordchance.com"] == 12.0
    assert calls[1].subject == "Quick check-in"
    assert calls[1].speaking_seconds == {}
    # sorted chronologically
    assert calls[0].start < calls[1].start


def test_parse_call_records_skips_calls_with_no_time_window():
    raw = [{"subject": "No start/end given", "attendees": ["a@b.com"]}]
    assert parse_call_records("LIB!3000", raw) == []


def test_parse_call_records_empty_input():
    assert parse_call_records("LIB!3000", []) == []
