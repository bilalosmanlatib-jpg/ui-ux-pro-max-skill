from counsel_analytics.diff.segment import align_clause_histories, segment_text


def test_segment_text_numbered_heading():
    text = "1. Definitions\nSome text.\n\n2. Price\nMore text.\n"
    segments = segment_text(text, version_no=1)
    assert [s.clause_id for s in segments] == ["1", "2"]
    assert segments[0].title == "Definitions"
    assert segments[1].title == "Price"


def test_segment_text_keyword_heading_canonicalizes_with_numbered():
    text_numbered = "3. Warranties\nSeller warrants title.\n"
    text_keyword = "Section 3\nSeller warrants title.\n"
    numbered = segment_text(text_numbered, version_no=1)
    keyword = segment_text(text_keyword, version_no=2)
    assert numbered[0].clause_id == keyword[0].clause_id == "3"


def test_segment_text_keyword_heading_roman_numeral_canonicalizes():
    text = "Article III\nGoverning law is England and Wales.\n"
    segments = segment_text(text, version_no=1)
    assert segments[0].clause_id == "3"


def test_segment_text_all_caps_heading():
    text = "GOVERNING LAW\nThis agreement is governed by English law.\n"
    segments = segment_text(text, version_no=1)
    assert segments[0].clause_id == "h-governing-law"
    assert segments[0].title == "GOVERNING LAW"


def test_segment_text_paragraph_fallback_when_no_headings():
    text = "First paragraph of unstructured text.\n\nSecond paragraph here.\n\nThird one.\n"
    segments = segment_text(text, version_no=1)
    assert [s.clause_id for s in segments] == ["para-0", "para-1", "para-2"]
    assert all(s.title is None for s in segments)


def test_align_clause_histories_links_by_canonical_id_across_versions():
    v1 = segment_text("1. Definitions\nA.\n\n2. Price\nP1.\n", 1)
    v2 = segment_text("1. Definitions\nA.\n\n2. Price\nP2.\n", 2)
    histories = align_clause_histories({1: v1, 2: v2})

    price_history = next(h for h in histories if h.entries[0].segment.title == "Price")
    assert [e.version_no for e in price_history.entries] == [1, 2]
    assert price_history.entries[0].was_changed is False
    assert price_history.entries[1].was_changed is True


def test_align_clause_histories_keyword_and_numbered_link_by_canonical_id():
    v1 = segment_text("3. Warranties\nSeller warrants title to the shares.\n", 1)
    v2 = segment_text("Section 3\nSeller warrants title to the shares.\n", 2)
    histories = align_clause_histories({1: v1, 2: v2})

    assert len(histories) == 1
    assert [e.version_no for e in histories[0].entries] == [1, 2]


def test_align_clause_histories_fuzzy_matches_shifted_paragraph_fallback():
    # v2 inserts a new paragraph before the warranties block, shifting its
    # positional para-N id — fuzzy text matching must still link it to v1's
    # entry since exact-id matching is skipped for fallback ("para-*") ids.
    v1_text = (
        "First paragraph.\n\n"
        "Warranties: seller warrants title to the shares free of encumbrances.\n"
    )
    v2_text = (
        "First paragraph.\n\n"
        "New inserted paragraph here.\n\n"
        "Warranties: seller warrants title to the shares free of encumbrances and liens.\n"
    )
    v1 = segment_text(v1_text, 1)
    v2 = segment_text(v2_text, 2)
    histories = align_clause_histories({1: v1, 2: v2})

    warranties_history = next(
        h for h in histories if "Warranties" in h.entries[0].segment.text
    )
    assert [e.version_no for e in warranties_history.entries] == [1, 2]
    assert warranties_history.entries[1].was_changed is True

    inserted_history = next(h for h in histories if h.entries[0].version_no == 2 and "inserted" in h.entries[0].segment.text)
    assert len(inserted_history.entries) == 1


def test_align_clause_histories_new_clause_inserted_mid_thread_is_marked_changed():
    v1 = segment_text("1. Definitions\nA.\n", 1)
    v2 = segment_text("1. Definitions\nA.\n\n2. New Clause\nBrand new.\n", 2)
    histories = align_clause_histories({1: v1, 2: v2})

    new_clause_history = next(h for h in histories if h.clause_id == "2")
    assert len(new_clause_history.entries) == 1
    assert new_clause_history.entries[0].was_changed is True


def test_align_clause_histories_empty_input():
    assert align_clause_histories({}) == []
