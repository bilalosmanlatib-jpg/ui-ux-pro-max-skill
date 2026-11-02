from datetime import datetime, timezone

from counsel_analytics.config import BillingSettings, Settings
from counsel_analytics.metrics.billing_integrity import compute_billing_signals
from counsel_analytics.models import CommentThread, MatterRef, Message, TimeEntry

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
