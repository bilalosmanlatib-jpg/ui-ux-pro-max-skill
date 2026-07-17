"""What a "thread" is, abstracted from where it comes from.

`sources/redline.py` is the MVP implementation: a thread is a private-markets
matter and its document versions in iManage Work. A later `sources/compliance.py`
would implement the same protocol over regulator correspondence, letting
`ingest/diff/metrics/report` stay untouched.
"""

from __future__ import annotations

from typing import Protocol

from counsel_analytics.models import CommentThread, DocumentRef, MatterRef, VersionEvent


class SourceAdapter(Protocol):
    def enumerate_threads(self) -> list[MatterRef]: ...

    def list_documents(self, matter_ref: MatterRef) -> list[DocumentRef]: ...

    def get_versions(self, matter_ref: MatterRef, document_ref: DocumentRef) -> list[VersionEvent]: ...

    def get_text(self, version_event: VersionEvent) -> str: ...

    def get_correspondence(self, matter_ref: MatterRef) -> list[CommentThread]: ...
