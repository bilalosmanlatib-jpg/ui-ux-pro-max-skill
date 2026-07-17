"""Aggregate tone/escalation signal — thread-scoped, never person-scoped.

Every metric here describes the correspondence *thread* on a matter, not
any individual: `sender_side` (internal vs. counsel) is used only to keep
scoring grounded in the negotiation, never to bucket by name. Notes keep
the same epistemic-humility framing as `metrics/volume.py` and
`metrics/reargument.py` — a rising escalation-lexicon score is reported as
a hypothesis about the thread, never a verdict about anyone's state of
mind.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from counsel_analytics.config import Settings
from counsel_analytics.metrics._stats import business_days_between, linear_trend_slope, mean
from counsel_analytics.models import CommentThread, Direction, Evidence, MatterRef, Metric

_DEFAULT_LEXICON_PATH = (
    Path(__file__).resolve().parent.parent.parent / "config" / "lexicons" / "escalation_terms.yaml"
)

_ESCALATION_TREND_EPSILON = 0.05
_LENGTH_TREND_EPSILON = 0.5
_LATENCY_TREND_EPSILON = 0.15
_MAX_EVIDENCE_QUOTES = 20

_HYPOTHESIS_NOTE_SUFFIX = (
    "Aggregate linguistic pattern across the correspondence thread on this matter — "
    "reported as a hypothesis about the thread, not a verdict about any individual."
)


class LexiconPhrase(BaseModel):
    phrase: str
    weight: float = 1.0


class LexiconCategory(BaseModel):
    weight: float = 1.0
    phrases: list[LexiconPhrase] = Field(default_factory=list)


class Lexicon(BaseModel):
    version: int = 1
    categories: dict[str, LexiconCategory] = Field(default_factory=dict)


def load_lexicon(path: Optional[Path] = None) -> Lexicon:
    resolved = Path(path) if path else _DEFAULT_LEXICON_PATH
    with resolved.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return Lexicon.model_validate(raw)


def _score_message(text: str, lexicon: Lexicon) -> tuple[float, list[str]]:
    casefolded = text.casefold()
    total = 0.0
    matched: list[str] = []
    for category in lexicon.categories.values():
        for entry in category.phrases:
            count = casefolded.count(entry.phrase.casefold())
            if count:
                total += count * entry.weight * category.weight
                matched.append(entry.phrase)
    return total, matched


def _direction(slope: float, epsilon: float) -> Direction:
    if slope > epsilon:
        return "up"
    if slope < -epsilon:
        return "down"
    return "flat"


def compute_tone_metrics(
    matter_ref: MatterRef,
    comment_threads: list[CommentThread],
    settings: Settings,
    *,
    rounds: Optional[dict[int, int]] = None,
) -> list[Metric]:
    messages = sorted(
        (m for thread in comment_threads for m in thread.messages),
        key=lambda m: m.timestamp,
    )
    if not messages:
        return []

    lexicon = load_lexicon(Path(settings.tone_lexicon_path) if settings.tone_lexicon_path else None)

    round_of_message: dict[int, int] = {}
    for idx, message in enumerate(messages):
        round_of_message[id(message)] = (rounds or {}).get(id(message), idx)

    score_by_round: dict[int, list[float]] = {}
    length_by_round: dict[int, list[int]] = {}
    quotes: list[str] = []

    for message in messages:
        round_index = round_of_message[id(message)]
        score, matched_phrases = _score_message(message.text, lexicon)
        score_by_round.setdefault(round_index, []).append(score)
        length_by_round.setdefault(round_index, []).append(len(message.text.split()))
        for phrase in matched_phrases:
            if len(quotes) < _MAX_EVIDENCE_QUOTES:
                quotes.append(f"round {round_index} ({message.timestamp.date()}): '{phrase}'")

    round_indices = sorted(score_by_round.keys())
    round_scores = [sum(score_by_round[r]) for r in round_indices]
    round_lengths = [mean(length_by_round[r]) for r in round_indices]

    escalation_slope = linear_trend_slope([float(r) for r in round_indices], round_scores)
    length_slope = linear_trend_slope([float(r) for r in round_indices], round_lengths)

    latencies = [business_days_between(a.timestamp, b.timestamp) for a, b in zip(messages, messages[1:])]
    latency_slope = (
        linear_trend_slope([float(i) for i in range(len(latencies))], latencies) if latencies else 0.0
    )

    evidence = Evidence(doc_ids=[], timestamps=[m.timestamp for m in messages], quotes=quotes)

    return [
        Metric(
            name="tone_escalation_mean",
            value=round(mean(round_scores), 3),
            unit="lexicon_score",
            direction="flat",
            evidence=evidence,
            note=(
                f"Mean per-round escalation-lexicon score across {len(round_indices)} round(s) "
                f"of correspondence on {matter_ref.display_name}. {_HYPOTHESIS_NOTE_SUFFIX}"
            ),
        ),
        Metric(
            name="tone_escalation_trend",
            value=round(escalation_slope, 4),
            unit="lexicon_score_per_round",
            direction=_direction(escalation_slope, _ESCALATION_TREND_EPSILON),
            evidence=evidence,
            note=(
                "Rising escalation-lexicon density may reflect hardening negotiating posture "
                f"or routine deal cadence. {_HYPOTHESIS_NOTE_SUFFIX}"
            ),
        ),
        Metric(
            name="tone_message_length_trend",
            value=round(length_slope, 3),
            unit="tokens_per_round",
            direction=_direction(length_slope, _LENGTH_TREND_EPSILON),
            evidence=evidence,
            note=f"Trend in mean message length (tokens) per round. {_HYPOTHESIS_NOTE_SUFFIX}",
        ),
        Metric(
            name="tone_response_latency_trend",
            value=round(latency_slope, 3),
            unit="business_days_per_message",
            direction=_direction(latency_slope, _LATENCY_TREND_EPSILON),
            evidence=evidence,
            note=(
                "Trend in business-day gaps between consecutive correspondence messages. "
                f"{_HYPOTHESIS_NOTE_SUFFIX}"
            ),
        ),
    ]
