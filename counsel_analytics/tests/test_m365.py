from counsel_analytics.mcp.m365 import parse_comment_threads, parse_messages

INTERNAL_DOMAINS = ["ninetyone.com"]
FIRM_DOMAINS = {"examplefirmllp.com": "Example Firm LLP"}


def test_parse_messages_handles_varied_key_shapes():
    raw = [
        {"from": "counsel@examplefirmllp.com", "sentDateTime": "2026-02-04T15:30:00Z", "subject": "RE: SPA", "body": "Hello there."},
        {"sender": "jane.doe@ninetyone.com", "timestamp": "2026-02-05T09:00:00Z", "title": "RE: SPA", "content": "Thanks, reviewing now."},
        {"senderEmailAddress": "counsel@examplefirmllp.com", "date": "2026-02-06T09:00:00Z", "bodyPreview": {"content": "Nested body dict."}},
    ]
    messages = parse_messages(raw, INTERNAL_DOMAINS, FIRM_DOMAINS)

    assert len(messages) == 3
    assert [m.sender_side for m in messages] == ["counsel", "internal", "counsel"]
    assert messages[0].text == "Hello there."
    assert messages[1].text == "Thanks, reviewing now."
    assert messages[2].text == "Nested body dict."
    # sorted chronologically
    assert messages[0].timestamp < messages[1].timestamp < messages[2].timestamp


def test_parse_messages_unmatched_domain_is_unknown():
    raw = [{"from": "someone@othercorp.com", "timestamp": "2026-02-04T15:30:00Z", "body": "hi"}]
    messages = parse_messages(raw, INTERNAL_DOMAINS, FIRM_DOMAINS)
    assert messages[0].sender_side == "unknown"


def test_parse_comment_threads_groups_by_source():
    raw = [
        {"source": "outlook", "from": "counsel@examplefirmllp.com", "timestamp": "2026-02-04T15:30:00Z", "body": "email 1"},
        {"source": "teams", "from": "jane.doe@ninetyone.com", "timestamp": "2026-02-05T09:00:00Z", "body": "chat 1"},
        {"source": "chat", "from": "jane.doe@ninetyone.com", "timestamp": "2026-02-05T10:00:00Z", "body": "chat 2"},
    ]
    threads = parse_comment_threads("LIB!3000", raw, INTERNAL_DOMAINS, FIRM_DOMAINS)

    by_source = {t.source: t for t in threads}
    assert set(by_source.keys()) == {"outlook", "teams"}
    assert len(by_source["outlook"].messages) == 1
    assert len(by_source["teams"].messages) == 2  # "chat" alias normalizes to "teams"
    assert all(t.matter_id == "LIB!3000" for t in threads)


def test_parse_comment_threads_defaults_missing_source_to_outlook():
    raw = [{"from": "counsel@examplefirmllp.com", "timestamp": "2026-02-04T15:30:00Z", "body": "no source key"}]
    threads = parse_comment_threads("LIB!3000", raw, INTERNAL_DOMAINS, FIRM_DOMAINS)
    assert len(threads) == 1
    assert threads[0].source == "outlook"


def test_parse_comment_threads_empty_input():
    assert parse_comment_threads("LIB!3000", [], INTERNAL_DOMAINS, FIRM_DOMAINS) == []
