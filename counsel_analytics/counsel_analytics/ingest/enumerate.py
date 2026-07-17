"""Matter -> documents -> version timeline."""

from __future__ import annotations

from pydantic import BaseModel

from counsel_analytics.models import DocumentRef, MatterRef, VersionEvent
from counsel_analytics.sources.base import SourceAdapter


class DocumentTimeline(BaseModel):
    document_ref: DocumentRef
    versions: list[VersionEvent]


class MatterTimeline(BaseModel):
    matter_ref: MatterRef
    documents: list[DocumentTimeline]
    has_documents: bool = False
    """Whether `source.list_documents()` enumerated 1+ documents for this
    matter, independent of whether any of them went on to produce version
    events. `documents` above is filtered to only those with 1+ versions,
    so `bool(documents)` collapses "no documents" and "documents but zero
    version events" into the same falsy value — callers that need to tell
    those two cases apart (see `ingest/correspond.py`'s `has_documents`
    parameter) must use this field instead.
    """


def enumerate_matter_timeline(source: SourceAdapter, matter_ref: MatterRef) -> MatterTimeline:
    document_refs = source.list_documents(matter_ref)
    documents = []
    for document_ref in document_refs:
        versions = source.get_versions(matter_ref, document_ref)
        if versions:
            documents.append(DocumentTimeline(document_ref=document_ref, versions=versions))
    return MatterTimeline(
        matter_ref=matter_ref, documents=documents, has_documents=bool(document_refs)
    )


def enumerate_all(source: SourceAdapter) -> list[MatterTimeline]:
    return [enumerate_matter_timeline(source, matter_ref) for matter_ref in source.enumerate_threads()]
