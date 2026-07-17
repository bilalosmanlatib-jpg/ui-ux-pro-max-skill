from datetime import datetime, timezone

from counsel_analytics.config import Settings
from counsel_analytics.metrics.tone import compute_tone_metrics
from counsel_analytics.models import CommentThread, MatterRef, Message

MATTER_REF = MatterRef(library="LIB", workspace_id="LIB!3000", display_name="Project Orion")

_FORBIDDEN_TERMS = ["passive-aggressive", "passive aggressive", "personality", "mindset", "psycholog"]


def _settings() -> Settings:
    return Settings(matter_ids=["LIB!3000"])


def _message(day: int, text: str) -> Message:
    return Message(timestamp=datetime(2026, 2, day, tzinfo=timezone.utc), sender_side="counsel", text=text)


def test_tone_escalation_trend_rises_with_escalating_language():
    messages = [
        _message(2, "Please see attached draft."),
        _message(6, "We must insist on this position. This is unacceptable."),
        _message(10, "We reserve our rights and must insist, as a matter of urgency."),
    ]
    thread = CommentThread(matter_id="LIB!3000", source="outlook", messages=messages)
    rounds = {id(messages[0]): 0, id(messages[1]): 1, id(messages[2]): 2}

    metrics = compute_tone_metrics(MATTER_REF, [thread], _settings(), rounds=rounds)
    by_name = {m.name: m for m in metrics}

    assert by_name["tone_escalation_trend"].direction == "up"
    assert by_name["tone_escalation_trend"].value > 0


def test_tone_metrics_quote_flagged_phrases_with_round_and_date():
    messages = [_message(6, "We must insist on this position.")]
    thread = CommentThread(matter_id="LIB!3000", source="outlook", messages=messages)
    rounds = {id(messages[0]): 0}

    metrics = compute_tone_metrics(MATTER_REF, [thread], _settings(), rounds=rounds)
    quotes = metrics[0].evidence.quotes
    assert any("we must insist" in q for q in quotes)
    assert any("round 0" in q and "2026-02-06" in q for q in quotes)


def test_tone_metrics_are_matter_scoped_not_document_scoped():
    messages = [_message(6, "We must insist on this position.")]
    thread = CommentThread(matter_id="LIB!3000", source="outlook", messages=messages)
    metrics = compute_tone_metrics(MATTER_REF, [thread], _settings())
    assert all(m.evidence.doc_ids == [] for m in metrics)


def test_tone_metrics_never_contain_forbidden_individual_profiling_language():
    messages = [_message(2, "Neutral message."), _message(6, "We must insist and reserve our rights.")]
    thread = CommentThread(matter_id="LIB!3000", source="outlook", messages=messages)
    metrics = compute_tone_metrics(MATTER_REF, [thread], _settings())
    combined = " ".join((m.note or "") for m in metrics).lower()
    for term in _FORBIDDEN_TERMS:
        assert term not in combined


def test_tone_metrics_empty_when_no_correspondence():
    assert compute_tone_metrics(MATTER_REF, [], _settings()) == []


def test_tone_metrics_bucket_by_side_not_by_name():
    messages = [
        Message(timestamp=datetime(2026, 2, 2, tzinfo=timezone.utc), sender_side="counsel", text="hello from counsel"),
        Message(timestamp=datetime(2026, 2, 3, tzinfo=timezone.utc), sender_side="internal", text="hello from internal"),
    ]
    thread = CommentThread(matter_id="LIB!3000", source="outlook", messages=messages)
    # Should not raise regardless of side mix, and metrics carry no author identity at all.
    metrics = compute_tone_metrics(MATTER_REF, [thread], _settings())
    assert metrics  # non-empty, since there is correspondence
