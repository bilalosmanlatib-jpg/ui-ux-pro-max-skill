"""Clause re-argument detection — populates `MatterMetrics.clause_signals`.

Two modes, selected by `settings.embedding_provider`:
- MVP, no embeddings (default): flag clauses touched in >= a configured
  number of rounds ("ping-pong"), evidence = quoted snippets, no claim
  about *why* it kept changing.
- With embeddings: detect a clause edited, settled for >= 1 round, then
  reopened with a substantively different edit (low cosine similarity
  between the settled and reopened text) rather than a cosmetic tweak.

Both modes keep the same epistemic-humility framing as `metrics/volume.py`.
"""

from __future__ import annotations

from counsel_analytics.config import Settings
from counsel_analytics.embeddings.provider import EmbeddingProvider, build_embedding_provider, cosine_similarity
from counsel_analytics.models import ClauseHistory, ClauseHistoryEntry, DocumentRef, Evidence, Metric

_QUOTE_MAX_CHARS = 200


def _clause_title(history: ClauseHistory) -> str:
    for entry in reversed(history.entries):
        if entry.segment.title:
            return entry.segment.title
    return history.clause_id


def _mvp_pingpong_metric(document_ref: DocumentRef, history: ClauseHistory, settings: Settings) -> Metric | None:
    touched = [e for e in history.entries if e.was_changed]
    if len(touched) < settings.thresholds.reargument_ping_pong_rounds:
        return None

    title = _clause_title(history)
    versions = [e.version_no for e in touched]
    quotes = [f"v{e.version_no}: {e.segment.text[:_QUOTE_MAX_CHARS]}" for e in touched]

    return Metric(
        name="clause_reargument_pingpong",
        value=float(len(touched)),
        unit="rounds",
        direction="up",
        evidence=Evidence(
            doc_ids=[document_ref.document_id],
            clause_ids=[history.clause_id],
            version_pair=(versions[0], versions[-1]),
            quotes=quotes,
        ),
        note=(
            f"Clause '{title}' was edited in {len(touched)} of {len(history.entries)} tracked "
            f"versions (v{versions[0]}–v{versions[-1]}). Repeated edits may indicate an "
            f"unresolved negotiation point or routine iterative drafting — reported as a "
            f"hypothesis, not a verdict."
        ),
    )


def _find_settled_reopened(entries: list[ClauseHistoryEntry]) -> tuple[int, int] | None:
    n = len(entries)
    for i in range(n):
        if not entries[i].was_changed:
            continue
        k = i + 1
        settled_rounds = 0
        while k < n and not entries[k].was_changed:
            settled_rounds += 1
            k += 1
        if settled_rounds >= 1 and k < n and entries[k].was_changed:
            return i, k
    return None


def _embedding_reargument_metric(
    document_ref: DocumentRef, history: ClauseHistory, settings: Settings, provider: EmbeddingProvider
) -> Metric | None:
    pair = _find_settled_reopened(history.entries)
    if pair is None:
        return None
    i, j = pair
    settled_entry, reopened_entry = history.entries[i], history.entries[j]

    vectors = provider.embed([settled_entry.segment.text, reopened_entry.segment.text])
    similarity = cosine_similarity(vectors[0], vectors[1])
    if similarity >= settings.thresholds.reargument_similarity_threshold:
        return None  # similar enough to be polishing, not a substantive re-argument

    title = reopened_entry.segment.title or settled_entry.segment.title or history.clause_id
    threshold = settings.thresholds.reargument_similarity_threshold

    return Metric(
        name="clause_reargument_semantic",
        value=round(similarity, 3),
        unit="cosine_similarity",
        direction="down",
        evidence=Evidence(
            doc_ids=[document_ref.document_id],
            clause_ids=[history.clause_id],
            version_pair=(settled_entry.version_no, reopened_entry.version_no),
            quotes=[
                f"v{settled_entry.version_no} (settled): {settled_entry.segment.text[:_QUOTE_MAX_CHARS]}",
                f"v{reopened_entry.version_no} (reopened): {reopened_entry.segment.text[:_QUOTE_MAX_CHARS]}",
            ],
        ),
        note=(
            f"Clause '{title}' was settled after v{settled_entry.version_no} then substantively "
            f"reopened in v{reopened_entry.version_no} (similarity {similarity:.2f} < threshold "
            f"{threshold:.2f}). May indicate an unresolved negotiation point or routine iterative "
            f"drafting — reported as a hypothesis, not a verdict."
        ),
    )


def compute_reargument_metrics(
    document_ref: DocumentRef,
    clause_histories: list[ClauseHistory],
    settings: Settings,
    *,
    provider: EmbeddingProvider | None = None,
) -> list[Metric]:
    resolved_provider = provider
    if resolved_provider is None and settings.embedding_provider != "none":
        try:
            resolved_provider = build_embedding_provider(settings)
        except (ImportError, NotImplementedError):
            resolved_provider = None

    metrics = []
    for history in clause_histories:
        if resolved_provider is not None:
            metric = _embedding_reargument_metric(document_ref, history, settings, resolved_provider)
        else:
            metric = _mvp_pingpong_metric(document_ref, history, settings)
        if metric is not None:
            metrics.append(metric)
    return metrics
