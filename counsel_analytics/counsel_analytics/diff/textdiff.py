"""Word-token diff between two consecutive version texts.

This is how the redline signal is reconstructed for the MVP: iManage's
`download_document` returns extracted text, not raw docx bytes, so there is
no `w:ins`/`w:del` markup to read. Diffing consecutive versions' plain text
is the fallback (see plan Phase 4 for the richer, raw-bytes path).
"""

from __future__ import annotations

import difflib

from counsel_analytics.models import DiffResult

_MAX_EVIDENCE_SNIPPETS = 20


def diff_versions(
    from_version: int, to_version: int, from_text: str, to_text: str
) -> DiffResult:
    from_tokens = from_text.split()
    to_tokens = to_text.split()

    matcher = difflib.SequenceMatcher(a=from_tokens, b=to_tokens, autojunk=False)
    insertions = 0
    deletions = 0
    added_text: list[str] = []
    removed_text: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag in ("delete", "replace"):
            deletions += i2 - i1
            if len(removed_text) < _MAX_EVIDENCE_SNIPPETS:
                removed_text.append(" ".join(from_tokens[i1:i2]))
        if tag in ("insert", "replace"):
            insertions += j2 - j1
            if len(added_text) < _MAX_EVIDENCE_SNIPPETS:
                added_text.append(" ".join(to_tokens[j1:j2]))

    changed_char_ratio = 1.0 - difflib.SequenceMatcher(
        a=from_text, b=to_text, autojunk=False
    ).ratio()

    return DiffResult(
        from_version=from_version,
        to_version=to_version,
        insertions=insertions,
        deletions=deletions,
        changed_tokens=insertions + deletions,
        total_tokens=len(to_tokens) or 1,
        changed_char_ratio=round(changed_char_ratio, 4),
        added_text=added_text,
        removed_text=removed_text,
    )
