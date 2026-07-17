"""Second domain: compliance/regulatory-correspondence trend-spotting.

A compliance "matter" is a regulatory inquiry/case tracked as an iManage
workspace with no documents to diff — there's no redline here, only
correspondence with a regulator. `list_documents`/`get_versions` are
therefore always empty and `get_text` is never called; `enumerate_threads`
and `get_correspondence` are otherwise identical to `RedlineSourceAdapter`
(both are already domain-agnostic: iManage workspace lookup + M365
correspondence, with nothing legal/redline-specific in them). This is
intentionally light duplication rather than a shared base class — two
~15-line methods across two adapters isn't worth extracting yet.

`internal_domains`/`firm_domains` are reused as-is: point `firm_domains`
at the regulator's email domain(s) (e.g. `{"fca.org.uk": "FCA"}`) instead
of a law firm's. Nothing in `ingest/diff/metrics/report` changes — this
file is the whole cost of adding this domain, which is the point of the
`SourceAdapter` boundary.
"""

from __future__ import annotations

from counsel_analytics.config import Settings
from counsel_analytics.mcp.client import MCPClient
from counsel_analytics.mcp.m365 import parse_comment_threads
from counsel_analytics.models import CommentThread, DocumentRef, MatterRef, VersionEvent


class ComplianceSourceAdapter:
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
                    firm=None,  # resolved later from correspondence, during rollup
                    display_name=profile.get("name") or profile.get("description") or matter_id,
                )
            )
        return matters

    def list_documents(self, matter_ref: MatterRef) -> list[DocumentRef]:
        return []  # compliance matters are correspondence-only; nothing to diff

    def get_versions(self, matter_ref: MatterRef, document_ref: DocumentRef) -> list[VersionEvent]:
        return []  # never called since list_documents is always empty

    def get_text(self, version_event: VersionEvent) -> str:
        raise NotImplementedError("Compliance domain has no document text — correspondence only.")

    def get_correspondence(self, matter_ref: MatterRef) -> list[CommentThread]:
        raw = self._client.get_correspondence_raw(matter_ref.workspace_id)
        return parse_comment_threads(
            matter_ref.workspace_id,
            raw,
            self._settings.internal_domains,
            self._settings.firm_domains,
        )
