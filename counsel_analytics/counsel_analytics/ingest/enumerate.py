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


def enumerate_matter_timeline(source: SourceAdapter, matter_ref: MatterRef) -> MatterTimeline:
    documents = []
    for document_ref in source.list_documents(matter_ref):
        versions = source.get_versions(matter_ref, document_ref)
        if versions:
            documents.append(DocumentTimeline(document_ref=document_ref, versions=versions))
    return MatterTimeline(matter_ref=matter_ref, documents=documents)


def enumerate_all(source: SourceAdapter) -> list[MatterTimeline]:
    return [enumerate_matter_timeline(source, matter_ref) for matter_ref in source.enumerate_threads()]
