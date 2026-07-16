from counsel_analytics.metrics.volume import compute_volume_metrics
from counsel_analytics.models import DiffResult, DocumentRef

DOC = DocumentRef(document_id="LIB!2001", name="Share Purchase Agreement.docx")


def _diff(from_v: int, to_v: int, changed_tokens: int, total_tokens: int) -> DiffResult:
    return DiffResult(
        from_version=from_v,
        to_version=to_v,
        insertions=changed_tokens,
        deletions=0,
        changed_tokens=changed_tokens,
        total_tokens=total_tokens,
        changed_char_ratio=changed_tokens / total_tokens,
    )


def test_compute_volume_metrics_rising_density_is_up():
    diffs = [_diff(1, 2, 1, 10), _diff(2, 3, 5, 10)]
    metrics = compute_volume_metrics(DOC, diffs)
    by_name = {m.name: m for m in metrics}

    assert by_name["redline_density_mean"].value == 0.3
    trend = by_name["redline_density_trend"]
    assert trend.direction == "up"
    assert trend.value > 0


def test_compute_volume_metrics_empty_diffs_returns_empty():
    assert compute_volume_metrics(DOC, []) == []
