from counsel_analytics.config import Settings
from counsel_analytics.diff.segment import align_clause_histories, segment_text
from counsel_analytics.metrics.reargument import compute_reargument_metrics
from counsel_analytics.models import ClauseHistory, ClauseHistoryEntry, ClauseSegment, DocumentRef

DOC = DocumentRef(document_id="LIB!4001", name="Framework Agreement.docx")

VERSIONS_TEXT = {
    1: "1. Definitions\nA.\n\n2. Price\nFixed at 500.\n\n3. Warranties\nSeller warrants title.\n",
    2: "1. Definitions\nA.\n\n2. Price\nFixed at 500.\n\n3. Warranties\nSeller warrants good title free of encumbrances.\n",
    3: "1. Definitions\nA.\n\n2. Price\nFixed at 500.\n\n3. Warranties\nSeller warrants good title free of encumbrances.\n",
    4: "1. Definitions\nA.\n\n2. Price\nFixed at 500.\n\n3. Warranties\nSeller warrants good and marketable title free of all encumbrances and liens.\n",
}


def _settings(**overrides) -> Settings:
    defaults = dict(matter_ids=["LIB!3000"])
    defaults.update(overrides)
    return Settings(**defaults)


def _clause_histories():
    segments_by_version = {v: segment_text(text, v) for v, text in VERSIONS_TEXT.items()}
    return align_clause_histories(segments_by_version)


def test_mvp_mode_flags_clause_touched_at_or_above_threshold():
    histories = _clause_histories()
    settings = _settings()
    settings.thresholds.reargument_ping_pong_rounds = 2

    metrics = compute_reargument_metrics(DOC, histories, settings)
    flagged_names = {m.evidence.clause_ids[0] for m in metrics}
    assert "3" in flagged_names  # Warranties touched in v2 and v4
    assert "2" not in flagged_names  # Price never changes


def test_mvp_mode_does_not_flag_below_threshold():
    histories = _clause_histories()
    settings = _settings()
    settings.thresholds.reargument_ping_pong_rounds = 5

    metrics = compute_reargument_metrics(DOC, histories, settings)
    assert metrics == []


def test_mvp_mode_evidence_has_doc_and_clause_ids_and_quotes():
    histories = _clause_histories()
    settings = _settings()
    settings.thresholds.reargument_ping_pong_rounds = 2

    metrics = compute_reargument_metrics(DOC, histories, settings)
    metric = next(m for m in metrics if m.evidence.clause_ids[0] == "3")
    assert metric.evidence.doc_ids == ["LIB!4001"]
    assert len(metric.evidence.quotes) == 2
    assert metric.direction == "up"
    assert "hypothesis" in metric.note


class _StubEmbeddingProvider:
    """Deterministic stub: returns pre-set vectors keyed by exact text
    match, so tests are fully offline with no real model."""

    def __init__(self, vectors_by_text: dict[str, list[float]]):
        self._vectors_by_text = vectors_by_text

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vectors_by_text[t] for t in texts]


def _history_with_settle_reopen(similar: bool) -> ClauseHistory:
    settled_text = "Clause settled text about indemnification obligations."
    reopened_text = (
        "Clause settled text about indemnification obligations, unchanged in substance."
        if similar
        else "Completely different limitation of liability language with new caps."
    )
    return ClauseHistory(
        clause_id="5",
        entries=[
            ClauseHistoryEntry(
                version_no=1,
                segment=ClauseSegment(clause_id="5", title="Indemnification", text="baseline text", version_no=1),
                was_changed=False,
            ),
            ClauseHistoryEntry(
                version_no=2,
                segment=ClauseSegment(clause_id="5", title="Indemnification", text=settled_text, version_no=2),
                was_changed=True,
            ),
            ClauseHistoryEntry(
                version_no=3,
                segment=ClauseSegment(clause_id="5", title="Indemnification", text=settled_text, version_no=3),
                was_changed=False,
            ),
            ClauseHistoryEntry(
                version_no=4,
                segment=ClauseSegment(clause_id="5", title="Indemnification", text=reopened_text, version_no=4),
                was_changed=True,
            ),
        ],
    )


def test_embedding_mode_flags_dissimilar_reopened_clause():
    history = _history_with_settle_reopen(similar=False)
    settings = _settings(embedding_provider="local")
    settings.thresholds.reargument_similarity_threshold = 0.55

    settled_text = history.entries[1].segment.text
    reopened_text = history.entries[3].segment.text
    provider = _StubEmbeddingProvider({settled_text: [1.0, 0.0], reopened_text: [0.0, 1.0]})  # orthogonal -> sim 0.0

    metrics = compute_reargument_metrics(DOC, [history], settings, provider=provider)
    assert len(metrics) == 1
    assert metrics[0].name == "clause_reargument_semantic"
    assert metrics[0].direction == "down"
    assert metrics[0].value == 0.0


def test_embedding_mode_does_not_flag_cosmetic_reopened_clause():
    history = _history_with_settle_reopen(similar=True)
    settings = _settings(embedding_provider="local")
    settings.thresholds.reargument_similarity_threshold = 0.55

    settled_text = history.entries[1].segment.text
    reopened_text = history.entries[3].segment.text
    provider = _StubEmbeddingProvider({settled_text: [1.0, 0.0], reopened_text: [0.99, 0.01]})  # near-identical

    metrics = compute_reargument_metrics(DOC, [history], settings, provider=provider)
    assert metrics == []


def test_embedding_mode_no_settle_reopen_pattern_returns_empty():
    settings = _settings(embedding_provider="local")
    history = ClauseHistory(
        clause_id="6",
        entries=[
            ClauseHistoryEntry(
                version_no=1,
                segment=ClauseSegment(clause_id="6", title=None, text="text", version_no=1),
                was_changed=False,
            )
        ],
    )
    metrics = compute_reargument_metrics(DOC, [history], settings, provider=_StubEmbeddingProvider({}))
    assert metrics == []
