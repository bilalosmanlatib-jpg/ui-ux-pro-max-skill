from datetime import datetime

from counsel_analytics.config import Settings
from counsel_analytics.ingest.correspond import correlate_correspondence
from counsel_analytics.mcp.imanage import parse_version_events
from counsel_analytics.mcp.m365 import parse_messages
from counsel_analytics.models import CommentThread, Message, VersionEvent


def _settings(window_days: int = 3) -> Settings:
    s = Settings(matter_ids=["LIB!3000"])
    s.correspondence_window_days = window_days
    return s


def _version(version_no: int, ts: str) -> VersionEvent:
    return VersionEvent(
        document_id_versioned=f"LIB!4001.{version_no}",
        version_no=version_no,
        author_id="jane.doe@ninetyone.com",
        author_side="internal",
        timestamp=datetime.fromisoformat(ts),
    )


def _message(ts: str, text: str = "hi") -> Message:
    return Message(timestamp=datetime.fromisoformat(ts), sender_side="counsel", text=text)


VERSIONS = [_version(1, "2026-02-02T09:00:00+00:00"), _version(2, "2026-02-12T09:00:00+00:00")]


def test_correlate_correspondence_keeps_in_window_drops_out_of_window():
    in_window_msg = _message("2026-02-03T09:00:00+00:00", text="near v1")
    out_of_window_msg = _message("2026-03-01T09:00:00+00:00", text="far from anything")
    thread = CommentThread(matter_id="LIB!3000", source="outlook", messages=[in_window_msg, out_of_window_msg])

    filtered, rounds = correlate_correspondence([thread], VERSIONS, _settings(window_days=3))

    kept_texts = {m.text for t in filtered for m in t.messages}
    assert kept_texts == {"near v1"}
    assert id(in_window_msg) in rounds
    assert id(out_of_window_msg) not in rounds


def test_correlate_correspondence_assigns_nearest_round():
    near_v1 = _message("2026-02-01T09:00:00+00:00")
    near_v2 = _message("2026-02-13T09:00:00+00:00")
    thread = CommentThread(matter_id="LIB!3000", source="outlook", messages=[near_v1, near_v2])

    _, rounds = correlate_correspondence([thread], VERSIONS, _settings(window_days=3))

    assert rounds[id(near_v1)] == 0  # nearest to VERSIONS[0] (v1)
    assert rounds[id(near_v2)] == 1  # nearest to VERSIONS[1] (v2)


def test_correlate_correspondence_no_version_events_passes_everything_through():
    # No document timeline at all (e.g. the compliance domain, which never
    # has documents) is not the same as "every message missed every
    # window" -- there's no window to miss, so nothing should be dropped.
    message = _message("2026-02-01T09:00:00+00:00")
    thread = CommentThread(matter_id="LIB!3000", source="outlook", messages=[message])
    filtered, rounds = correlate_correspondence([thread], [], _settings())
    assert len(filtered) == 1
    assert filtered[0].messages == [message]
    assert rounds == {}


def test_correlate_correspondence_no_version_events_compliance_domain_no_warning(caplog):
    # has_documents=False (the default, e.g. the compliance domain) is the
    # intentional case -- no warning, since there's no document timeline by
    # design, not because every document happened to enumerate zero events.
    message = _message("2026-02-01T09:00:00+00:00")
    thread = CommentThread(matter_id="LIB!3000", source="outlook", messages=[message])
    with caplog.at_level("WARNING"):
        correlate_correspondence([thread], [], _settings(), has_documents=False)
    assert caplog.records == []


def test_correlate_correspondence_no_version_events_with_documents_warns(caplog):
    # has_documents=True but version_events is still empty means a
    # redline-domain matter whose documents all enumerated zero version
    # events (e.g. get_document_versions came back empty for every one) --
    # correspondence-window filtering is silently disabled, so this should
    # be flagged even though the pass-through behavior is the same.
    message = _message("2026-02-01T09:00:00+00:00")
    thread = CommentThread(matter_id="LIB!3000", source="outlook", messages=[message])
    with caplog.at_level("WARNING"):
        filtered, rounds = correlate_correspondence([thread], [], _settings(), has_documents=True)
    assert len(filtered) == 1
    assert rounds == {}
    assert len(caplog.records) == 1
    assert "LIB!3000" in caplog.records[0].message


def test_correlate_correspondence_empty_threads_returns_empty():
    filtered, rounds = correlate_correspondence([], VERSIONS, _settings())
    assert filtered == []
    assert rounds == {}


def test_correlate_correspondence_handles_naive_version_and_aware_message_timestamps():
    # Realistic shape: iManage-derived VersionEvent timestamps are often
    # timezone-naive (on-prem `modifiedDate` with no offset), while M365
    # Message timestamps are always aware ('Z'-suffixed Graph `sentDateTime`).
    # This must not raise TypeError on `message.timestamp - version.timestamp`.
    naive_versions = parse_version_events(
        "LIB!4001",
        [{"version": 1, "author": "jane.doe@ninetyone.com", "modifiedDate": "2026-02-02T09:00:00"}],
        internal_domains=["ninetyone.com"],
        firm_domains={},
    )
    aware_messages = parse_messages(
        [{"from": "counsel@examplefirmllp.com", "sentDateTime": "2026-02-03T09:00:00Z", "body": "near v1"}],
        internal_domains=["ninetyone.com"],
        firm_domains={"examplefirmllp.com": "Example Firm LLP"},
    )
    thread = CommentThread(matter_id="LIB!3000", source="outlook", messages=aware_messages)

    filtered, rounds = correlate_correspondence([thread], naive_versions, _settings(window_days=3))

    assert {m.text for t in filtered for m in t.messages} == {"near v1"}
    assert rounds[id(aware_messages[0])] == 0


def test_correlate_correspondence_preserves_source_grouping():
    msg_email = _message("2026-02-03T09:00:00+00:00", text="email")
    msg_chat = _message("2026-02-03T10:00:00+00:00", text="chat")
    threads = [
        CommentThread(matter_id="LIB!3000", source="outlook", messages=[msg_email]),
        CommentThread(matter_id="LIB!3000", source="teams", messages=[msg_chat]),
    ]
    filtered, _ = correlate_correspondence(threads, VERSIONS, _settings(window_days=3))
    assert {t.source for t in filtered} == {"outlook", "teams"}
