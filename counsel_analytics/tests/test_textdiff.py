from counsel_analytics.diff.textdiff import diff_versions


def test_diff_versions_counts_insertions_and_deletions():
    from_text = "the purchase price is 100"
    to_text = "the purchase price is 120 subject to adjustment"

    result = diff_versions(1, 2, from_text, to_text)

    assert result.from_version == 1
    assert result.to_version == 2
    assert result.deletions == 1  # "100" removed
    assert result.insertions == 4  # "120 subject to adjustment" added
    assert result.changed_tokens == result.insertions + result.deletions
    assert result.total_tokens == len(to_text.split())
    assert result.added_text == ["120 subject to adjustment"]
    assert result.removed_text == ["100"]


def test_diff_versions_identical_text_has_no_changes():
    text = "no changes here at all"
    result = diff_versions(1, 2, text, text)
    assert result.insertions == 0
    assert result.deletions == 0
    assert result.changed_char_ratio == 0.0
