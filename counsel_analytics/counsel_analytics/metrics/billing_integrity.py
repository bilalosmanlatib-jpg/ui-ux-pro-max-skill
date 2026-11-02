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

Only correspondence is used as the "observed activity" proxy in this MVP
(every message is already timestamped and word-countable). Redline/diff
volume is a natural extension once diffs are joined back to the version
event timestamps they came from — not wired here.

Every flag is a candidate for manual invoice review, never a finding of
overbilling: a date with no matching correspondence may simply mean the
work happened by phone, in person, or in a system this pipeline doesn't
see (internal firm research, drafting with nothing sent that day).
"""

from __future__ import annotations

from counsel_analytics.config import Settings
from counsel_analytics.models import BillingSignal, CommentThread, Evidence, MatterRef, TimeEntry

_NARRATIVE_MAX_CHARS = 200


def _matching_messages(entry: TimeEntry, comment_threads: list[CommentThread], window_days: int):
    matches = []
    for thread in comment_threads:
        for message in thread.messages:
            if abs((message.timestamp.date() - entry.entry_date.date()).days) <= window_days:
                matches.append(message)
    return matches


def compute_billing_signals(
    matter_ref: MatterRef,
    time_entries: list[TimeEntry],
    comment_threads: list[CommentThread],
    settings: Settings,
) -> list[BillingSignal]:
    settings_billing = settings.billing
    signals: list[BillingSignal] = []

    for entry in time_entries:
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
            continue

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

    return signals
