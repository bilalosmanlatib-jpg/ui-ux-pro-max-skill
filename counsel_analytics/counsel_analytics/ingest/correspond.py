"""Correlate matter correspondence to the version-event timeline.

Keeps tone scoring genuinely thread/matter-scoped to the actual
negotiation timeline: a message survives only if it falls within
`correspondence_window_days` of at least one version event; everything
else is out-of-scope chatter and is dropped. Each surviving message is
assigned to its nearest version event's round for per-round tone scoring.

A matter with correspondence but no document version events at all (the
compliance/correspondence-only domain — see `sources/compliance.py` — has
no documents to diff, ever) is a different case from "no message fell in
any window": there's no version timeline to correlate against, not a
timeline every message happened to miss. Everything passes through
unfiltered in that case, and `metrics/tone.py`'s own chronological-index
fallback (used whenever no round mapping is supplied) assigns rounds.
"""

from __future__ import annotations

from datetime import timedelta

from counsel_analytics.config import Settings
from counsel_analytics.models import CommentThread, Message, VersionEvent


def correlate_correspondence(
    threads: list[CommentThread],
    version_events: list[VersionEvent],
    settings: Settings,
) -> tuple[list[CommentThread], dict[int, int]]:
    """Returns (filtered_threads, round_by_message_id) where
    `round_by_message_id` maps `id(message)` -> the index (into version
    events sorted by timestamp) of the nearest version event. Callers must
    hold onto the same `Message` objects returned here to look up rounds.
    """
    if not threads:
        return [], {}
    if not version_events:
        # No document timeline to correlate against at all (e.g. the
        # compliance domain, which has no documents by design) — pass
        # everything through rather than treating it as "out of window."
        return threads, {}

    window = timedelta(days=settings.correspondence_window_days)
    sorted_versions = sorted(version_events, key=lambda v: v.timestamp)

    round_by_message_id: dict[int, int] = {}
    kept_by_source: dict[str, list[Message]] = {}
    matter_id = threads[0].matter_id

    for thread in threads:
        for message in thread.messages:
            nearest_round, nearest_delta, in_window = None, None, False
            for round_index, version in enumerate(sorted_versions):
                delta = abs(message.timestamp - version.timestamp)
                if delta <= window:
                    in_window = True
                if nearest_delta is None or delta < nearest_delta:
                    nearest_delta, nearest_round = delta, round_index
            if in_window:
                round_by_message_id[id(message)] = nearest_round
                kept_by_source.setdefault(thread.source, []).append(message)

    filtered_threads = [
        CommentThread(matter_id=matter_id, source=source, messages=messages)
        for source, messages in kept_by_source.items()
    ]
    return filtered_threads, round_by_message_id
