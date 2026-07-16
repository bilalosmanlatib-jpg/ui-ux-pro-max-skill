"""Download + normalize + locally cache each version's extracted text.

Caching matters here for two reasons: `download_document` is a paginated
call per version, and re-running a matter during development shouldn't
re-fetch text that hasn't changed.
"""

from __future__ import annotations

import re
from pathlib import Path

from counsel_analytics.models import VersionEvent
from counsel_analytics.sources.base import SourceAdapter

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def normalize_text(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [line.rstrip() for line in lines]
    normalized = "\n".join(lines).strip("\n")
    return normalized + "\n" if normalized else ""


def _cache_path(cache_dir: Path, document_id_versioned: str) -> Path:
    safe_name = _UNSAFE_CHARS.sub("_", document_id_versioned)
    return cache_dir / f"{safe_name}.txt"


def extract_version_text(
    source: SourceAdapter, version_event: VersionEvent, cache_dir: Path
) -> str:
    cache_path = _cache_path(cache_dir, version_event.document_id_versioned)
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    text = normalize_text(source.get_text(version_event))
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text, encoding="utf-8")
    return text
