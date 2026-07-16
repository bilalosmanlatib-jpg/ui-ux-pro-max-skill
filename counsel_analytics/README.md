# Counsel Analytics

Aggregate turnaround, redline-volume, and (Phase 2+) clause/tone pattern
analytics for external counsel on private-markets transactions — built to
answer "is this firm getting slower / re-arguing settled points /
escalating tone" with evidence, not impressions.

**Guardrail, non-negotiable:** every metric here is scoped to a document,
matter, or counterparty/firm — never to a named individual. This is
turnaround-time and redline-pattern analytics for legal-ops purposes, not
psychological profiling of counsel or staff. See the plan doc for the
reasoning (UK GDPR profiling / employment-monitoring exposure vs. marginal
insight gain).

## Status: Phase 1 MVP

Implemented: matter → document → version-timeline enumeration, text
extraction/caching, version-to-version diffing, counsel turnaround-time
metrics (with bottleneck attribution), redline volume/density metrics, and
JSON/CSV/Markdown reporting — for a single matter, no NLP or correspondence
yet.

Deferred (see the plan doc for the full phase breakdown): clause-level
re-argument detection, tone/escalation scoring, cross-matter counterparty
rollup, a compliance/regulatory-correspondence domain, an Outlook add-in,
and standalone (non-session) scheduled runs.

## How data gets in: the MCP boundary

The iManage Work and Microsoft 365 tools this module depends on are
exposed to a **Claude session**, not as an importable Python SDK. So this
module doesn't call them itself — instead:

1. Inside a Claude Code session that has the iManage Work MCP tools
   connected, fetch the raw responses needed for your matter(s):
   `get_workspace_profile`, `get_container_children`, `get_document_versions`,
   and `download_document` (looping the `cursor` until exhausted and
   concatenating chunks) for each version you need text for.
2. Assemble those responses into the JSON shape documented in
   `counsel_analytics/mcp/client.py` (`SessionMCPClient`'s `raw_data`
   shape) and write it to a file. `tests/fixtures/one_matter.json` is a
   worked example.
3. Run the CLI against that file — see below.

A `DirectMCPClient` (this module authenticates to the MCP servers itself,
for standalone/scheduled runs with the org's OAuth credentials) is a
documented Phase 4 item, not implemented yet.

## Setup

```bash
cd counsel_analytics
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp config/config.example.yaml config.yaml   # fill in real matter_ids, domains
```

## Running

```bash
.venv/bin/counsel-analytics run --config config.yaml --raw-data path/to/fetched.json
```

Outputs land in `output_dir` (from `config.yaml`): a canonical JSON file, a
Markdown report, and `version_events.csv` / `turnaround_rounds.csv` /
`matter_metrics.csv` for BI tools. `--matter LIB!xxxx` can be repeated to
override `matter_ids` from the config for a one-off run.

## Tests

```bash
.venv/bin/pytest -q
```

Tests run entirely offline against the fixture in `tests/fixtures/` — no
live MCP calls or credentials needed.

## Config notes (`config.yaml`)

- `internal_domains` / `firm_domains` — how author email domains are
  classified into `internal` / `counsel` (and which firm), for turnaround
  hand-off detection. Unmatched domains are classified `unknown` rather
  than guessed.
- `anonymize_authors` — when `true`, author identities are hashed in every
  output file, so a report can be shared with the firm being measured
  without exposing named individuals.
- `output_dir` — where JSON/CSV/Markdown reports (and the local text
  cache) are written.

## Extending

- **A second domain (compliance/regulatory correspondence):** implement
  `sources/compliance.py` against the `SourceAdapter` protocol in
  `sources/base.py`. `ingest/diff/metrics/report` never reference iManage
  or a specific domain directly, so they don't change.
- **An Outlook add-in:** wrap this engine with a new transport; the engine
  itself has no UI/transport assumptions baked in.
- **Richer redline (Word tracked-changes, not just text diff):** blocked
  today because `download_document` returns extracted text, not raw docx
  bytes. If a raw-bytes download path becomes available, add
  `python-docx`/lxml parsing in `diff/` — this is a Phase 4 item.
