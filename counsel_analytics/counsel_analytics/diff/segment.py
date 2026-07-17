"""Clause/section segmentation and cross-version alignment.

Segments a version's text into `ClauseSegment`s by heading, then links
matching clauses across versions into `ClauseHistory`s so
`metrics/reargument.py` can tell "this clause keeps getting reopened" from
"this is just a different clause."
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from counsel_analytics.models import ClauseHistory, ClauseHistoryEntry, ClauseSegment

_NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.*)$")
_KEYWORD_HEADING_RE = re.compile(
    r"^(?:Section|Clause|Article)\s+([0-9]+(?:\.\d+)*|[IVXLC]+)\.?\s*(.*)$", re.IGNORECASE
)
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
_ROMAN_RE = re.compile(r"^[IVXLCivxlc]+$")
_FUZZY_THRESHOLD = 82


def _roman_to_arabic(numeral: str) -> int:
    total = 0
    prev_value = 0
    for ch in reversed(numeral.upper()):
        value = _ROMAN_VALUES[ch]
        if value < prev_value:
            total -= value
        else:
            total += value
            prev_value = value
    return total


def _canonical_clause_id(raw: str) -> str:
    raw = raw.strip().rstrip(".")
    if _ROMAN_RE.match(raw):
        return str(_roman_to_arabic(raw))
    return raw


def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "untitled"


def _looks_like_all_caps_heading(stripped: str) -> bool:
    if not stripped or stripped.endswith("."):
        return False
    words = stripped.split()
    if not (1 <= len(words) <= 12):
        return False
    if sum(ch.isalpha() for ch in stripped) < 3:
        return False
    return stripped == stripped.upper() and stripped != stripped.lower()


def _match_heading(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped:
        return None

    m = _NUMBERED_HEADING_RE.match(stripped)
    if m:
        return _canonical_clause_id(m.group(1)), m.group(2).strip()

    m = _KEYWORD_HEADING_RE.match(stripped)
    if m:
        return _canonical_clause_id(m.group(1)), m.group(2).strip()

    if _looks_like_all_caps_heading(stripped):
        return f"h-{_slug(stripped)}", stripped

    return None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _paragraph_fallback_segments(text: str, version_no: int) -> list[ClauseSegment]:
    blocks = re.split(r"\n\s*\n", text.strip())
    segments = []
    for i, block in enumerate(blocks):
        block = block.strip()
        if block:
            segments.append(ClauseSegment(clause_id=f"para-{i}", title=None, text=block, version_no=version_no))
    return segments


def segment_text(text: str, version_no: int) -> list[ClauseSegment]:
    lines = text.split("\n")
    headings: list[tuple[int, str, str]] = []
    for i, line in enumerate(lines):
        match = _match_heading(line)
        if match:
            headings.append((i, match[0], match[1]))

    if not headings:
        return _paragraph_fallback_segments(text, version_no)

    segments = []
    for idx, (line_index, clause_id, title) in enumerate(headings):
        end = headings[idx + 1][0] if idx + 1 < len(headings) else len(lines)
        body = "\n".join(lines[line_index:end]).strip()
        segments.append(
            ClauseSegment(clause_id=clause_id, title=title or None, text=body, version_no=version_no)
        )
    return segments


def _is_fallback_id(clause_id: str) -> bool:
    return clause_id.startswith("h-") or clause_id.startswith("para-")


def _find_fuzzy_match(
    segment: ClauseSegment, histories: list[ClauseHistory], version_no: int
) -> int | None:
    best_idx, best_score = None, 0
    for idx, history in enumerate(histories):
        if not history.entries:
            continue
        last = history.entries[-1]
        if last.version_no == version_no:
            # Already matched to a segment from this same version during
            # this pass — never fuzzy-match a second, distinct clause from
            # the same version onto it.
            continue
        last = last.segment
        if segment.title and last.title:
            score = fuzz.token_set_ratio(segment.title, last.title)
        else:
            score = fuzz.token_set_ratio(_normalize(segment.text)[:200], _normalize(last.text)[:200])
        if score > best_score:
            best_idx, best_score = idx, score
    return best_idx if best_score >= _FUZZY_THRESHOLD else None


def align_clause_histories(segments_by_version: dict[int, list[ClauseSegment]]) -> list[ClauseHistory]:
    if not segments_by_version:
        return []

    first_version = min(segments_by_version.keys())
    histories: list[ClauseHistory] = []
    primary_index: dict[str, int] = {}

    for version_no in sorted(segments_by_version.keys()):
        for segment in segments_by_version[version_no]:
            target_idx = None
            if not _is_fallback_id(segment.clause_id) and segment.clause_id in primary_index:
                target_idx = primary_index[segment.clause_id]
            else:
                target_idx = _find_fuzzy_match(segment, histories, version_no)

            if target_idx is None:
                histories.append(ClauseHistory(clause_id=segment.clause_id, entries=[]))
                target_idx = len(histories) - 1
                if not _is_fallback_id(segment.clause_id):
                    primary_index[segment.clause_id] = target_idx

            history = histories[target_idx]
            if history.entries:
                was_changed = _normalize(history.entries[-1].segment.text) != _normalize(segment.text)
            else:
                was_changed = version_no != first_version

            history.entries.append(
                ClauseHistoryEntry(version_no=version_no, segment=segment, was_changed=was_changed)
            )

    return histories
