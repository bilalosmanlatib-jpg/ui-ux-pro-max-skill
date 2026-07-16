import json
from pathlib import Path

from counsel_analytics.config import load_settings
from counsel_analytics.ingest.enumerate import enumerate_all
from counsel_analytics.mcp.client import build_client
from counsel_analytics.sources.redline import RedlineSourceAdapter

FIXTURES = Path(__file__).parent / "fixtures"


def _load_source():
    settings = load_settings(FIXTURES / "test_config.yaml")
    raw_data = json.loads((FIXTURES / "one_matter.json").read_text())
    client = build_client(settings.mcp_client, raw_data)
    return RedlineSourceAdapter(client, settings), settings


def test_enumerate_all_builds_one_matter_timeline_with_five_versions():
    source, _ = _load_source()
    timelines = enumerate_all(source)

    assert len(timelines) == 1
    timeline = timelines[0]
    assert timeline.matter_ref.workspace_id == "LIB!1000"
    assert timeline.matter_ref.client_id == "CLIENT001"
    assert len(timeline.documents) == 1

    doc_timeline = timeline.documents[0]
    assert doc_timeline.document_ref.document_id == "LIB!2001"
    assert [v.version_no for v in doc_timeline.versions] == [1, 2, 3, 4, 5]
    assert [v.author_side for v in doc_timeline.versions] == [
        "internal",
        "counsel",
        "internal",
        "counsel",
        "internal",
    ]
