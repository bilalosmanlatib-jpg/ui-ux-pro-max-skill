# Counsel Analytics

Aggregate turnaround, redline-volume, clause re-argument, and tone/
escalation pattern analytics for external counsel on private-markets
transactions — built to answer "is this firm getting slower / re-arguing
settled points / escalating tone" with evidence, not impressions. On top
of the analytics: a condensed review packet and an approve/flag/escalate
sign-off workflow, so a senior decision-maker can review and sign off on a
matter in minutes, not by reading raw version history.

**Guardrail, non-negotiable:** every analytics metric here is scoped to a
document, matter, or counterparty/firm — never to a named individual. This
is turnaround-time and redline-pattern analytics for legal-ops purposes,
not psychological profiling of counsel or staff. See the plan doc for the
reasoning (UK GDPR profiling / employment-monitoring exposure vs. marginal
insight gain). Sign-off *reviewer identity* (who internally approved
something) is a separate, ordinary accountability concern and never blurs
into that guardrail — it's recorded in `signoffs.jsonl`, never in the
analytics report/packet.

## Status: Phase 1 + Phase 2 + Phase 3 + Phase 3.5

Implemented:
- **Phase 1** — matter → document → version-timeline enumeration, text
  extraction/caching, version-to-version diffing, counsel turnaround-time
  metrics (with bottleneck attribution), redline volume/density metrics.
- **Phase 2** — clause segmentation + cross-version alignment, clause
  re-argument detection (ping-pong flagging by default; optional
  embedding-based semantic-similarity mode), correspondence ingestion via
  the Microsoft 365 MCP tools correlated to the version timeline, and
  thread-scoped tone/escalation scoring against a configurable lexicon.
- **Phase 3** — cross-matter counterparty (firm) rollup: groups
  already-computed matters by firm and trends each metric across the
  relationship over time (`counsel-analytics rollup`, plus automatic
  rollup at the end of `run` when 2+ matters processed together share a
  firm).
- **Phase 3.5** — a condensed review packet (`packet`) and an
  append-only, hash-chained sign-off audit log (`signoff`,
  `verify-signoffs`), independent of Phase 2/3.
- **Compliance domain (Phase 4, partial)** — a second, correspondence-only
  domain (`domain: compliance` in config) for regulatory-inquiry
  trend-spotting: no documents, tone/escalation scoring only. Proves the
  `sources/` boundary claim for real — `sources/compliance.py` plus one
  bug fix in `ingest/correspond.py` (see below) was the entire cost;
  `ingest/diff/metrics/report` didn't change at all.

Still deferred (see the plan doc for the full phase breakdown, and
"Extending" below for why each is a deliberate stop, not an oversight): an
Outlook add-in, and standalone (non-session) scheduled runs via
`DirectMCPClient` (both Phase 4).

## How data gets in: the MCP boundary

The iManage Work and Microsoft 365 tools this module depends on are
exposed to a **Claude session**, not as an importable Python SDK. So this
module doesn't call them itself — instead:

1. Inside a Claude Code session that has the iManage Work / Microsoft 365
   MCP tools connected, fetch the raw responses needed for your matter(s):
   `get_workspace_profile`, `get_container_children`, `get_document_versions`,
   `download_document` (looping the `cursor` until exhausted and
   concatenating chunks) for each version you need text for, and — for
   Phase 2 tone scoring — `outlook_email_search`/`chat_message_search`
   correspondence for the matter.
2. Assemble those responses into the JSON shape documented in
   `counsel_analytics/mcp/client.py` (`SessionMCPClient`'s `raw_data`
   shape) and write it to a file. `tests/fixtures/one_matter.json`
   (Phase 1 only) and `tests/fixtures/phase2_matter.json` (adds
   correspondence + a re-argued clause) are worked examples.
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
# Full analysis: turnaround, volume, clause re-argument, tone.
.venv/bin/counsel-analytics run --config config.yaml --raw-data path/to/fetched.json

# ~5-minute review packet from a report this produced.
.venv/bin/counsel-analytics packet --config config.yaml --report ./data/output/LIB_1000.json

# Record a decision against that exact evidence snapshot.
.venv/bin/counsel-analytics signoff --config config.yaml --report ./data/output/LIB_1000.json \
    --reviewer jane.doe@ninetyone.com --decision approve --reason "Turnaround improving, no open issues."

# Check the sign-off audit log's hash chain is intact.
.venv/bin/counsel-analytics verify-signoffs --config config.yaml

# Roll up 2+ already-run matters that share a firm (run() does this
# automatically for matters processed together in one call; use this to
# combine matters that were run() separately, e.g. analyzed on different days).
.venv/bin/counsel-analytics rollup --config config.yaml \
    --report ./data/output/LIB_1000.json --report ./data/output/LIB_3000.json
```

`run` outputs land in `output_dir` (from `config.yaml`): a canonical JSON
file, a Markdown report, and `version_events.csv` / `turnaround_rounds.csv`
/ `clause_signals.csv` / `matter_metrics.csv` for BI tools, plus
`counterparty_rollups.json` / `firm_period_metrics.csv` /
`counterparty_rollups.md` if 2+ matters processed in that call share a
resolvable firm. `--matter LIB!xxxx` can be repeated to override
`matter_ids` from the config for a one-off run. A matter's firm is
resolved automatically from its counsel-side authors' email domains
(`firm_domains`) — no separate config needed.

`signoff` appends to `output_dir/signoffs.jsonl` (never mutates or
deletes). `packet` looks up the latest sign-off for the matter and flags
itself `stale` if the report has moved on since — re-running `packet`
after a fresh `run` will show a re-review banner if the evidence changed.

## Tests

```bash
.venv/bin/pytest -q
```

Tests run entirely offline against the fixture in `tests/fixtures/` — no
live MCP calls or credentials needed.

## Config notes (`config.yaml`)

- `internal_domains` / `firm_domains` — how author/sender email domains
  are classified into `internal` / `counsel` (and which firm), for
  turnaround hand-off detection and tone's side-level bucketing. Unmatched
  domains are classified `unknown` rather than guessed.
- `anonymize_authors` — when `true`, author identities are hashed in every
  output file, so a report can be shared with the firm being measured
  without exposing named individuals.
- `correspondence_window_days` — how many calendar days either side of a
  version event to keep correspondence for tone scoring; anything outside
  every window is dropped as out-of-scope chatter.
- `thresholds.reargument_ping_pong_rounds` (default 3) — a clause touched
  in at least this many versions is flagged, in the default no-embeddings
  mode. `thresholds.reargument_similarity_threshold` (default 0.55) — used
  only when `embedding_provider` is `local`/`api`.
- `embedding_provider` — `none` (default, ping-pong mode only), `local`
  (`sentence-transformers`, needs the `embeddings` extra), or `api`
  (not yet implemented — see `embeddings/provider.py`).
- `tone_lexicon_path` — override for `config/lexicons/escalation_terms.yaml`.
- `packet.max_highlights` / `packet.min_abs_value` — how many non-flat
  metrics the review packet surfaces, and a coarse magnitude floor.
- `output_dir` — where JSON/CSV/Markdown reports, the sign-off log, the
  counterparty rollup, and the local text cache are written.

A firm needs 2+ matters with a resolvable firm before `metrics/aggregate.py`
will roll it up at all (a single matter has nothing to trend against) —
this and the trend-direction epsilon are fixed constants in
`metrics/aggregate.py`, not config, since they're a coarse default rather
than something a matter-specific config should tune.

## Extending

- **A third domain:** implement a new `SourceAdapter` (see
  `sources/base.py`; `sources/compliance.py` is a small, fully-built
  worked example — correspondence-only, no documents). `ingest/diff/
  metrics/report` never reference iManage or a specific domain directly,
  so they don't change — and neither does `report/packet.py`/`signoff.py`,
  since those only ever touch the generic `MatterMetrics`/`Metric` types.
- **An Outlook add-in:** wrap this engine with a new transport; the engine
  itself has no UI/transport assumptions baked in. Genuinely out of scope
  for this Python module — a real add-in is JS/TypeScript + an Office.js
  manifest, a different tech stack entirely, not a Python change.
- **Richer redline (Word tracked-changes, not just text diff):** blocked
  today because `download_document` returns extracted text, not raw docx
  bytes. If a raw-bytes download path becomes available, add
  `python-docx`/lxml parsing in `diff/` — this is a Phase 4 item.
- **A real embeddings API for `embedding_provider: api`:** Anthropic's API
  doesn't expose text embeddings; `ApiEmbeddingProvider` in
  `embeddings/provider.py` is a documented placeholder, not a real
  backend. Wire in a real embeddings provider there if this mode is
  needed before Phase 4.
