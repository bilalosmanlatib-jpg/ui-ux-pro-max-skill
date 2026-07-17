import json
from pathlib import Path

import pytest

from counsel_analytics.config import load_settings
from counsel_analytics.mcp.client import build_client
from counsel_analytics.sources.compliance import ComplianceSourceAdapter

FIXTURES = Path(__file__).parent / "fixtures"


def _adapter():
    settings = load_settings(FIXTURES / "compliance_config.yaml")
    raw_data = json.loads((FIXTURES / "compliance_matter.json").read_text())
    client = build_client(settings.mcp_client, raw_data)
    return ComplianceSourceAdapter(client, settings), settings


def test_enumerate_threads_builds_matter_ref_from_workspace_profile():
    adapter, _ = _adapter()
    matters = adapter.enumerate_threads()
    assert len(matters) == 1
    assert matters[0].workspace_id == "LIB!5000"
    assert matters[0].client_id == "CLIENT003"
    assert matters[0].display_name == "FCA Inquiry - Client Data Handling"


def test_list_documents_always_empty():
    adapter, _ = _adapter()
    matter_ref = adapter.enumerate_threads()[0]
    assert adapter.list_documents(matter_ref) == []


def test_get_versions_always_empty():
    adapter, _ = _adapter()
    matter_ref = adapter.enumerate_threads()[0]
    assert adapter.get_versions(matter_ref, document_ref=None) == []


def test_get_text_raises_not_implemented():
    adapter, _ = _adapter()
    with pytest.raises(NotImplementedError):
        adapter.get_text(version_event=None)


def test_get_correspondence_returns_regulator_thread():
    adapter, _ = _adapter()
    matter_ref = adapter.enumerate_threads()[0]
    threads = adapter.get_correspondence(matter_ref)
    assert len(threads) == 1
    assert threads[0].source == "outlook"
    assert len(threads[0].messages) == 4
    assert threads[0].messages[0].sender_side == "counsel"  # fca.org.uk resolved via firm_domains
