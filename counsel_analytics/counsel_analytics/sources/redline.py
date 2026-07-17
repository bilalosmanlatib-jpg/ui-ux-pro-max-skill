"""MVP source adapter: a private-markets matter's documents and their
version history in iManage Work, plus (Phase 2) its correspondence via
the M365 MCP tools.

`get_correspondence` is a thin translation boundary — it hands back
`CommentThread`s from whatever raw correspondence the session fetched;
correlating those to version-event time windows happens downstream in
`ingest/correspond.py`, not here.
"""

from __future__ import annotations

from typing import Any

from counsel_analytics.config import Settings
from counsel_analytics.mcp.client import MCPClient
from counsel_analytics.mcp.imanage import parse_version_events
from counsel_analytics.mcp.m365 import parse_comment_threads
from counsel_analytics.models import CommentThread, DocumentRef, MatterRef, VersionEvent

_DOC_ID_KEYS = ("documentId", "document_id", "id")
_DOC_NAME_KEYS = ("name", "documentName", "title")
_TYPE_KEYS = ("type", "itemType", "kind")
_NON_DOCUMENT_TYPES = {"folder", "email", "shortcut", "workspace"}


def _first(raw: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in raw and raw[key] is not None:
            return raw[key]
    return None


class RedlineSourceAdapter:
    def __init__(self, client: MCPClient, settings: Settings):
        self._client = client
        self._settings = settings

    def enumerate_threads(self) -> list[MatterRef]:
        matters = []
        for matter_id in self._settings.matter_ids:
            library = matter_id.split("!", 1)[0]
            profile = self._client.get_workspace_profile(matter_id)
            matters.append(
                MatterRef(
                    library=library,
                    workspace_id=matter_id,
                    client_id=profile.get("custom1"),
                    matter_id=profile.get("custom2"),
                    firm=None,  # resolved later, per-document, during rollup
                    display_name=profile.get("name") or profile.get("description") or matter_id,
                )
            )
        return matters

    def list_documents(self, matter_ref: MatterRef) -> list[DocumentRef]:
        children = self._client.get_container_children(matter_ref.workspace_id, "workspace")
        documents = []
        for raw in children:
            item_type = str(_first(raw, _TYPE_KEYS) or "document").lower()
            if item_type in _NON_DOCUMENT_TYPES:
                continue
            document_id = _first(raw, _DOC_ID_KEYS)
            if not document_id:
                continue
            documents.append(
                DocumentRef(
                    document_id=str(document_id),
                    name=str(_first(raw, _DOC_NAME_KEYS) or document_id),
                )
            )
        return documents

    def get_versions(self, matter_ref: MatterRef, document_ref: DocumentRef) -> list[VersionEvent]:
        raw_versions = self._client.get_document_versions(document_ref.document_id)
        return parse_version_events(
            document_ref.document_id,
            raw_versions,
            self._settings.internal_domains,
            self._settings.firm_domains,
        )

    def get_text(self, version_event: VersionEvent) -> str:
        return self._client.download_document_text(version_event.document_id_versioned)

    def get_correspondence(self, matter_ref: MatterRef) -> list[CommentThread]:
        raw = self._client.get_correspondence_raw(matter_ref.workspace_id)
        return parse_comment_threads(
            matter_ref.workspace_id,
            raw,
            self._settings.internal_domains,
            self._settings.firm_domains,
        )
