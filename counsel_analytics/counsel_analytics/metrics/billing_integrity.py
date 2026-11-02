"""Billing-integrity (invoice audit) signals — populates
`MatterMetrics.billing_signals`.

This is deliberately NOT part of the aggregate, never-individual metrics
pipeline (`metrics/turnaround.py`, `volume.py`, `reargument.py`, `tone.py`):
those stay matter/document/firm-scoped per the README's non-negotiable
guardrail. This module names the timekeeper on an invoice line item on
purpose, under the engagement's contractual right to review billed work
against work actually produced — it's invoice/vendor-spend audit, not
behavioral profiling, and the two must never be merged: `BillingSignal` is
a distinct type from `Metric`, and `anonymize_authors` never touches it.

Three independent check families:
- **Rate-cap violation** — the invoiced hourly rate for a timekeeper vs. the
  rate contracted for them in the engagement letter (`settings.billing.rate_caps`,
  read off the letter in-session). This is the one deterministic check here:
  no heuristic, no tolerance band — a contract fixes a rate, an invoice either
  matches it or doesn't. Checked on every entry with both an invoiced rate
  and a configured cap, regardless of `hours_min_to_flag`, since a wrong rate
  is a contract breach at any volume.
- **Hours vs. observed activity** — only correspondence is used as the
  "observed activity" proxy in this MVP (every message is already
  timestamped and word-countable). Redline/diff volume is a natural
  extension once diffs are joined back to the version event timestamps
  they came from — not wired here. Unlike the rate check, this is a rough
  proxy, not a fact: a date with no matching correspondence may simply mean
  the work happened by phone, in person, or in a system this pipeline
  doesn't see (internal firm research, drafting with nothing sent that day).
- **Calls** (`settings.billing.call_analysis`, off by default) — attendance
  (`CallRecord.attendees`) is a hard calendar fact; whether that attendance
  produced anything is not. Two modes, picked per call by what data exists
  (`"auto"`), never guessed: `"attendance"` flags a confirmed attendee with
  no correspondence around the call (`call_no_output`) — the same proxy
  caveat as the hours-vs-correspondence check, since presence on a call
  doesn't rule out real, unlogged contribution; `"transcript"` flags a
  confirmed attendee whose meeting transcript shows under
  `call_min_speaking_seconds` of speaking (`call_no_contribution`) — only
  possible when a transcript was actually fetched for that call (most
  won't have one), and a genuine step up in sensitivity over everything
  else here: it looks at what was said, not just whether work exists
  around the call. See the README for why this one is opt-in and off by
  default.

Every flag is a candidate for manual invoice review, never a verdict.
"""

from __future__ import annotations

from counsel_analytics.config import Settings
from counsel_analytics.models import BillingSignal, CallRecord, CommentThread, Evidence, MatterRef, TimeEntry

_NARRATIVE_MAX_CHARS = 200


def _matching_messages(entry: TimeEntry, comment_threads: list[CommentThread], window_days: int):
    matches = []
    for thread in comment_threads:
        for message in thread.messages:
            if abs((message.timestamp.date() - entry.entry_date.date()).days) <= window_days:
                matches.append(message)
    return matches


def _name_matches_identity(name: str, identity: str) -> bool:
    """Heuristic, not exact: an invoice shows 'Newton-Savage, H.' while a
    calendar shows 'henry.newton-savage@cliffordchance.com'. Every
    meaningful token of the timekeeper's name must appear in the identity
    string — no attempt at a cleverer match, so a miss is a silent
    non-match rather than a wrong one."""
    tokens = [t for t in name.lower().replace("-", " ").replace(",", " ").split() if len(t) > 1]
    if not tokens:
        return False
    identity_norm = identity.lower()
    return all(t in identity_norm for t in tokens)


def _matching_calls(
    entry: TimeEntry, call_records: list[CallRecord], window_days: int
) -> list[tuple[CallRecord, str]]:
    matches = []
    for call in call_records:
        if abs((call.start.date() - entry.entry_date.date()).days) > window_days:
            continue
        identity = next((a for a in call.attendees if _name_matches_identity(entry.timekeeper_name, a)), None)
        if identity:
            matches.append((call, identity))
    return matches


def compute_billing_signals(
    matter_ref: MatterRef,
    time_entries: list[TimeEntry],
    comment_threads: list[CommentThread],
    settings: Settings,
    call_records: list[CallRecord] | None = None,
) -> list[BillingSignal]:
    settings_billing = settings.billing
    call_records = call_records or []
    signals: list[BillingSignal] = []

    for entry in time_entries:
        cap = settings_billing.rate_caps.get(entry.timekeeper_name)
        if cap is not None and entry.rate is not None and entry.rate > cap + 1e-6:
            narrative = entry.narrative[:_NARRATIVE_MAX_CHARS]
            signals.append(
                BillingSignal(
                    timekeeper_name=entry.timekeeper_name,
                    timekeeper_role=entry.timekeeper_role,
                    entry_date=entry.entry_date,
                    hours=entry.hours,
                    narrative=narrative,
                    flag="rate_cap_violation",
                    observed_activity_words=0,
                    note=(
                        f"Invoiced at {entry.rate:.2f}{('/' + entry.currency) if entry.currency else ''} "
                        f"per hour on {entry.entry_date.date()}, against a contracted rate of "
                        f"{cap:.2f} for {entry.timekeeper_name} under the engagement letter — "
                        f"{entry.rate - cap:.2f} over the agreed rate. Flagged for manual invoice "
                        "review against the contract, not a finding of deliberate overbilling."
                    ),
                    evidence=Evidence(timestamps=[entry.entry_date]),
                )
            )

        if entry.hours < settings_billing.hours_min_to_flag:
            continue

        matches = _matching_messages(entry, comment_threads, settings_billing.window_days)
        observed_words = sum(len(m.text.split()) for m in matches)
        narrative = entry.narrative[:_NARRATIVE_MAX_CHARS]
        quotes = [f"{m.timestamp.date()}: {m.text[:_NARRATIVE_MAX_CHARS]}" for m in matches[:5]]
        evidence = Evidence(timestamps=[entry.entry_date] + [m.timestamp for m in matches], quotes=quotes)

        if observed_words == 0:
            signals.append(
                BillingSignal(
                    timekeeper_name=entry.timekeeper_name,
                    timekeeper_role=entry.timekeeper_role,
                    entry_date=entry.entry_date,
                    hours=entry.hours,
                    narrative=narrative,
                    flag="no_matching_activity",
                    observed_activity_words=0,
                    note=(
                        f"{entry.hours:.2f}h billed on {entry.entry_date.date()} "
                        f"(\"{narrative}\") has no matching correspondence in this system within "
                        f"{settings_billing.window_days} day(s) of that date. May reflect work this "
                        "pipeline can't see (calls, in-person meetings, internal drafting/research "
                        "with nothing sent) — flagged for manual invoice review, not a finding of "
                        "overbilling."
                    ),
                    evidence=evidence,
                )
            )
        else:
            hours_per_100_words = entry.hours / (observed_words / 100)
            if hours_per_100_words >= settings_billing.hours_per_100_words_threshold:
                signals.append(
                    BillingSignal(
                        timekeeper_name=entry.timekeeper_name,
                        timekeeper_role=entry.timekeeper_role,
                        entry_date=entry.entry_date,
                        hours=entry.hours,
                        narrative=narrative,
                        flag="high_hours_per_output",
                        observed_activity_words=observed_words,
                        note=(
                            f"{entry.hours:.2f}h billed on {entry.entry_date.date()} (\"{narrative}\") "
                            f"against {observed_words} word(s) of matching correspondence within "
                            f"{settings_billing.window_days} day(s) ({hours_per_100_words:.2f}h per 100 "
                            f"words, threshold {settings_billing.hours_per_100_words_threshold:.2f}). "
                            "Correspondence volume is a rough proxy for the work actually visible in "
                            "this system, not a timer on the lawyer's day — flagged for manual invoice "
                            "review, not a finding of overbilling."
                        ),
                        evidence=evidence,
                    )
                )

        if settings_billing.call_analysis == "off":
            continue

        for call, identity in _matching_calls(entry, call_records, settings_billing.window_days):
            spoke = call.speaking_seconds.get(identity)
            subject = call.subject or "an unnamed call"
            call_evidence = Evidence(
                timestamps=[entry.entry_date, call.start, call.end],
                quotes=[f"{subject}: {call.start.isoformat()} - {call.end.isoformat()}"],
            )

            if spoke is not None and settings_billing.call_analysis in ("transcript", "auto"):
                if spoke < settings_billing.call_min_speaking_seconds:
                    signals.append(
                        BillingSignal(
                            timekeeper_name=entry.timekeeper_name,
                            timekeeper_role=entry.timekeeper_role,
                            entry_date=entry.entry_date,
                            hours=entry.hours,
                            narrative=narrative,
                            flag="call_no_contribution",
                            observed_activity_words=observed_words,
                            note=(
                                f"Attended \"{subject}\" on {call.start.date()}; the meeting transcript "
                                f"shows {spoke:.0f}s of speaking time, below the "
                                f"{settings_billing.call_min_speaking_seconds:.0f}s threshold. This looks "
                                "at what was said in the meeting, not just whether work exists around "
                                "it — flagged for manual invoice review, not a finding that nothing of "
                                "value was contributed (reviewing without speaking is real work)."
                            ),
                            evidence=call_evidence,
                        )
                    )
            elif settings_billing.call_analysis in ("attendance", "auto") and observed_words == 0:
                signals.append(
                    BillingSignal(
                        timekeeper_name=entry.timekeeper_name,
                        timekeeper_role=entry.timekeeper_role,
                        entry_date=entry.entry_date,
                        hours=entry.hours,
                        narrative=narrative,
                        flag="call_no_output",
                        observed_activity_words=0,
                        note=(
                            f"Confirmed attendance at \"{subject}\" on {call.start.date()}, but no "
                            f"correspondence followed within {settings_billing.window_days} day(s). "
                            "Calendar attendance is a hard fact; the absence of follow-up is not proof "
                            "nothing happened in the call — flagged for manual invoice review, not a "
                            "finding of overbilling."
                        ),
                        evidence=call_evidence,
                    )
                )

    return signals
