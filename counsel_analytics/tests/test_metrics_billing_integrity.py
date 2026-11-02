from datetime import datetime, timezone

from counsel_analytics.config import BillingSettings, Settings
from counsel_analytics.metrics.billing_integrity import compute_billing_signals
from counsel_analytics.models import CallRecord, CommentThread, MatterRef, Message, TimeEntry

MATTER_REF = MatterRef(library="LIB", workspace_id="LIB!3000", display_name="Project Orion")


def _settings(**billing_overrides) -> Settings:
    return Settings(matter_ids=["LIB!3000"], billing=BillingSettings(**billing_overrides))


def _entry(
    hours: float,
    narrative: str = "Review and respond to lender email.",
    *,
    rate: float | None = None,
    currency: str | None = None,
) -> TimeEntry:
    return TimeEntry(
        matter_id="LIB!3000",
        timekeeper_name="Jane Doe",
        timekeeper_role="Partner",
        entry_date=datetime(2026, 2, 6, tzinfo=timezone.utc),
        hours=hours,
        narrative=narrative,
        rate=rate,
        currency=currency,
    )


def _thread(day: int, text: str) -> CommentThread:
    message = Message(timestamp=datetime(2026, 2, day, tzinfo=timezone.utc), sender_side="counsel", text=text)
    return CommentThread(matter_id="LIB!3000", source="outlook", messages=[message])


def _call(day: int, attendees: list[str], speaking_seconds: dict[str, float] | None = None) -> CallRecord:
    return CallRecord(
        matter_id="LIB!3000",
        start=datetime(2026, 2, day, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 2, day, 9, 30, tzinfo=timezone.utc),
        subject="Matter call",
        attendees=attendees,
        speaking_seconds=speaking_seconds or {},
    )


def test_flags_no_matching_activity():
    signals = compute_billing_signals(MATTER_REF, [_entry(5.0)], [], _settings())
    assert len(signals) == 1
    assert signals[0].flag == "no_matching_activity"
    assert signals[0].timekeeper_name == "Jane Doe"
    assert signals[0].observed_activity_words == 0


def test_does_not_flag_entry_with_ample_matching_correspondence():
    long_email = " ".join(["word"] * 500)
    signals = compute_billing_signals(MATTER_REF, [_entry(1.0)], [_thread(6, long_email)], _settings())
    assert signals == []


def test_flags_high_hours_relative_to_thin_correspondence():
    short_email = "Please see attached."
    signals = compute_billing_signals(MATTER_REF, [_entry(5.0)], [_thread(6, short_email)], _settings())
    assert len(signals) == 1
    assert signals[0].flag == "high_hours_per_output"
    assert signals[0].observed_activity_words == 3


def test_ignores_entries_below_hours_min_to_flag():
    signals = compute_billing_signals(MATTER_REF, [_entry(0.1)], [], _settings())
    assert signals == []


def test_window_days_controls_date_matching():
    short_email = "Please see attached."
    # Message is 3 days away; default window is 1 day, so it should not count.
    signals = compute_billing_signals(MATTER_REF, [_entry(2.0)], [_thread(3, short_email)], _settings())
    assert signals[0].flag == "no_matching_activity"

    # Widen the window to 3 days -> now a thin match should flag as high-hours instead.
    signals_wide = compute_billing_signals(
        MATTER_REF, [_entry(2.0)], [_thread(3, short_email)], _settings(window_days=3)
    )
    assert signals_wide[0].flag == "high_hours_per_output"


def test_evidence_quotes_matching_messages():
    signals = compute_billing_signals(
        MATTER_REF, [_entry(5.0)], [_thread(6, "Short reply.")], _settings()
    )
    assert any("Short reply." in q for q in signals[0].evidence.quotes)


def test_note_never_claims_overbilling_as_a_finding():
    signals = compute_billing_signals(MATTER_REF, [_entry(5.0)], [], _settings())
    note = signals[0].note.lower()
    assert "not a finding of overbilling" in note


def test_call_analysis_off_by_default_ignores_calls():
    call = _call(6, ["jane.doe@counsel.com"], speaking_seconds={"jane.doe@counsel.com": 0.0})
    signals = compute_billing_signals(MATTER_REF, [_entry(5.0)], [], _settings(), call_records=[call])
    flags = {s.flag for s in signals}
    assert "call_no_contribution" not in flags
    assert "call_no_output" not in flags


def test_attendance_mode_flags_call_with_no_output():
    call = _call(6, ["jane.doe@counsel.com"])
    signals = compute_billing_signals(
        MATTER_REF, [_entry(5.0)], [], _settings(call_analysis="attendance"), call_records=[call]
    )
    flags = {s.flag for s in signals}
    assert "call_no_output" in flags


def test_attendance_mode_does_not_flag_call_with_output():
    call = _call(6, ["jane.doe@counsel.com"])
    long_email = " ".join(["word"] * 500)
    signals = compute_billing_signals(
        MATTER_REF, [_entry(1.0)], [_thread(6, long_email)], _settings(call_analysis="attendance"), call_records=[call]
    )
    flags = {s.flag for s in signals}
    assert "call_no_output" not in flags


def test_transcript_mode_flags_low_speaking_time():
    call = _call(6, ["jane.doe@counsel.com"], speaking_seconds={"jane.doe@counsel.com": 5.0})
    signals = compute_billing_signals(
        MATTER_REF, [_entry(5.0)], [], _settings(call_analysis="transcript"), call_records=[call]
    )
    flags = {s.flag for s in signals}
    assert "call_no_contribution" in flags
    assert "call_no_output" not in flags  # transcript present -> attendance check does not also fire


def test_transcript_mode_does_not_flag_ample_speaking_time():
    call = _call(6, ["jane.doe@counsel.com"], speaking_seconds={"jane.doe@counsel.com": 900.0})
    signals = compute_billing_signals(
        MATTER_REF, [_entry(5.0)], [], _settings(call_analysis="transcript"), call_records=[call]
    )
    flags = {s.flag for s in signals}
    assert "call_no_contribution" not in flags


def test_auto_mode_prefers_transcript_when_available_else_attendance():
    with_transcript = _call(6, ["jane.doe@counsel.com"], speaking_seconds={"jane.doe@counsel.com": 2.0})
    no_transcript = _call(6, ["jane.doe@counsel.com"])

    signals_t = compute_billing_signals(
        MATTER_REF, [_entry(5.0)], [], _settings(call_analysis="auto"), call_records=[with_transcript]
    )
    assert {s.flag for s in signals_t} >= {"call_no_contribution"}
    assert "call_no_output" not in {s.flag for s in signals_t}

    signals_a = compute_billing_signals(
        MATTER_REF, [_entry(5.0)], [], _settings(call_analysis="auto"), call_records=[no_transcript]
    )
    assert "call_no_output" in {s.flag for s in signals_a}


def test_call_matching_is_name_to_identity_heuristic_not_exact():
    call = _call(6, ["JDoe <jane.doe@counsel.com>"])
    signals = compute_billing_signals(
        MATTER_REF, [_entry(5.0)], [], _settings(call_analysis="attendance"), call_records=[call]
    )
    assert any(s.flag == "call_no_output" for s in signals)


def test_unmatched_attendee_does_not_trigger_call_flags():
    call = _call(6, ["someone.else@counsel.com"])
    signals = compute_billing_signals(
        MATTER_REF, [_entry(5.0)], [], _settings(call_analysis="attendance"), call_records=[call]
    )
    flags = {s.flag for s in signals}
    assert "call_no_output" not in flags
    assert "call_no_contribution" not in flags


def test_call_note_never_claims_idleness_as_a_finding():
    call = _call(6, ["jane.doe@counsel.com"], speaking_seconds={"jane.doe@counsel.com": 1.0})
    signals = compute_billing_signals(
        MATTER_REF, [_entry(5.0)], [], _settings(call_analysis="transcript"), call_records=[call]
    )
    contribution_signal = next(s for s in signals if s.flag == "call_no_contribution")
    assert "not a finding" in contribution_signal.note.lower()


def test_flags_rate_cap_violation_regardless_of_hours():
    # Below hours_min_to_flag, so the hours-based checks would stay silent --
    # the rate check must still fire, since a wrong rate is a contract issue
    # at any volume.
    entry = _entry(0.1, rate=525.0, currency="EUR")
    signals = compute_billing_signals(
        MATTER_REF, [entry], [], _settings(rate_caps={"Jane Doe": 500.0})
    )
    assert len(signals) == 1
    assert signals[0].flag == "rate_cap_violation"
    assert "525.00" in signals[0].note and "500.00" in signals[0].note


def test_does_not_flag_rate_at_or_below_cap():
    entry = _entry(5.0, rate=500.0)
    signals = compute_billing_signals(
        MATTER_REF, [entry], [], _settings(rate_caps={"Jane Doe": 500.0})
    )
    flags = {s.flag for s in signals}
    assert "rate_cap_violation" not in flags


def test_rate_check_ignored_when_timekeeper_has_no_configured_cap():
    entry = _entry(0.1, rate=10000.0)
    signals = compute_billing_signals(MATTER_REF, [entry], [], _settings())
    assert signals == []


def test_entry_can_carry_both_rate_and_activity_flags():
    entry = _entry(5.0, rate=525.0)
    signals = compute_billing_signals(
        MATTER_REF, [entry], [], _settings(rate_caps={"Jane Doe": 500.0})
    )
    flags = {s.flag for s in signals}
    assert flags == {"rate_cap_violation", "no_matching_activity"}
