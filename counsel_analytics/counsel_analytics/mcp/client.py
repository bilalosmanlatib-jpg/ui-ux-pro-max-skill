"""The MCP I/O boundary.

The iManage Work and Microsoft 365 tools this module depends on are exposed
to a Claude session as MCP tools, not as a plain Python SDK. This module can
run two ways:

- `SessionMCPClient`: an orchestrating Claude session calls the MCP tools
  itself and hands the raw JSON responses to this client. This is the
  supported path today (in-session runs) and needs no extra credentials.
- `DirectMCPClient`: this module acts as its own MCP client, authenticating
  to the iManage Work / Microsoft 365 MCP servers directly (org OAuth).
  Deferred to Phase 4 for standalone/scheduled runs; see README for the
  credential provisioning this would require.

Every other layer (`ingest`, `diff`, `metrics`, `report`) only ever calls
methods on an `MCPClient` — never a raw tool name — so swapping
implementations never touches pipeline code.
"""

from __future__ import annotations

from typing import Protocol


class MCPClient(Protocol):
    """Raw data access needed by `ingest/`. Returns provider-shaped dicts;
    translating those into domain models happens in `imanage.py`/`m365.py`.
    """

    def get_workspace_profile(self, workspace_id: str) -> dict: ...

    def get_container_children(self, container_id: str, container_type: str) -> list[dict]: ...

    def get_document_versions(self, document_id: str) -> list[dict]: ...

    def download_document_text(self, document_id_versioned: str) -> str: ...

    def get_correspondence_raw(self, matter_id: str) -> list[dict]: ...


class SessionMCPClient:
    """Looks up pre-fetched MCP responses supplied by the orchestrating
    session, keyed the same way the real tool calls are: by workspace/
    document ID. Raises `KeyError` with a clear message if the caller
    forgot to fetch something the pipeline needs — that's a signal to fetch
    more data via the session's iManage/M365 tools, not a bug in this class.

    `raw_data` shape (JSON-serializable — this is what gets written to the
    file passed via `--raw-data`):
        {
          "workspaces": {workspace_id: <get_workspace_profile response>},
          "container_children": {"<container_id>|<container_type>": [<child>, ...]},
          "document_versions": {document_id: [<version>, ...]},
          "document_text": {document_id_versioned: "<extracted text>"},
          "correspondence": {matter_id: [<raw email/chat message>, ...]},
        }
    """

    def __init__(self, raw_data: dict):
        self._workspaces: dict[str, dict] = raw_data.get("workspaces", {})
        self._container_children: dict[str, list[dict]] = raw_data.get("container_children", {})
        self._document_versions: dict[str, list[dict]] = raw_data.get("document_versions", {})
        self._document_text: dict[str, str] = raw_data.get("document_text", {})
        self._correspondence: dict[str, list[dict]] = raw_data.get("correspondence", {})

    def get_workspace_profile(self, workspace_id: str) -> dict:
        try:
            return self._workspaces[workspace_id]
        except KeyError as exc:
            raise KeyError(
                f"No pre-fetched workspace profile for {workspace_id!r}. "
                "Fetch it via the iManage Work MCP tool get_workspace_profile "
                "and add it to raw_data['workspaces']."
            ) from exc

    def get_container_children(self, container_id: str, container_type: str) -> list[dict]:
        return self._container_children.get(f"{container_id}|{container_type}", [])

    def get_document_versions(self, document_id: str) -> list[dict]:
        try:
            return self._document_versions[document_id]
        except KeyError as exc:
            raise KeyError(
                f"No pre-fetched version history for {document_id!r}. Fetch "
                "it via get_document_versions and add it to "
                "raw_data['document_versions']."
            ) from exc

    def download_document_text(self, document_id_versioned: str) -> str:
        try:
            return self._document_text[document_id_versioned]
        except KeyError as exc:
            raise KeyError(
                f"No pre-fetched text for {document_id_versioned!r}. Fetch "
                "it via download_document (looping the cursor until "
                "exhausted, concatenating chunks) and add it to "
                "raw_data['document_text']."
            ) from exc

    def get_correspondence_raw(self, matter_id: str) -> list[dict]:
        # Empty is legitimate here (unlike the getters above): a matter may
        # genuinely have no correspondence fetched, or none at all — that's
        # not an error the pipeline needs to stop for.
        return self._correspondence.get(matter_id, [])


class DirectMCPClient:
    """Phase 4: connect to the iManage Work / M365 MCP servers directly as
    this module's own MCP client, for standalone/scheduled runs outside a
    Claude session. Requires the `direct-mcp` extra and org OAuth
    credentials — see README. Not implemented in the MVP.
    """

    def __init__(self, *_args, **_kwargs):
        raise NotImplementedError(
            "DirectMCPClient is a Phase 4 item. Use mcp_client: session in "
            "config.yaml and run this module from within a Claude session "
            "that has the iManage Work / Microsoft 365 MCP tools connected."
        )


def build_client(mcp_client: str, raw_data: dict | None = None) -> MCPClient:
    if mcp_client == "session":
        return SessionMCPClient(raw_data or {})
    if mcp_client == "direct":
        return DirectMCPClient()
    raise ValueError(f"Unknown mcp_client setting: {mcp_client!r}")
