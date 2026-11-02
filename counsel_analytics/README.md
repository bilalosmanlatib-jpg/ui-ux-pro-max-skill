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

**Deliberate carve-out — billing integrity (`billing_signals`):** the one
part of this system that *does* name an individual, on purpose. Under the
engagement's contractual right to review a firm's billing breakdown against
the work it actually produced, `metrics/billing_integrity.py` cross-checks
named-timekeeper invoice line items against observable matter activity
(correspondence volume, redline/diff volume is a planned extension — see
"Extending" — and call attendance/transcripts, below) and flags
disproportionate entries for manual review — never a verdict of
overbilling. This is invoice/vendor-spend audit, a different category from
the behavioral-pattern guardrail above, and it's kept structurally
separate: `BillingSignal` is not a `Metric`, lives in its own
`MatterMetrics.billing_signals` list, is off by default
(`billing.enabled: false`), and is never affected by `anonymize_authors`.
It renders in its own report section with its own disclaimer, and it never
appears in the review packet, which stays scoped to the aggregate metrics.

**A second, sharper line inside that carve-out — calls (`billing.call_analysis`,
off by default, `"off"`/`"attendance"`/`"transcript"`/`"auto"`):** every
check above (rate caps, hours vs. correspondence) asks "does the matter
show evidence this work happened" — it never looks at what anyone actually
said or did. Call analysis is different in kind, not just degree, in its
`"transcript"` mode: `"attendance"` mode stays on the same footing as the
other checks (a timekeeper's calendar attendance is a hard fact; the
absence of correspondence afterward is still just a proxy, same caveat as
`no_matching_activity`) — but `"transcript"` mode reads a meeting
transcript and checks whether the named timekeeper actually spoke. That is
real conduct-in-a-meeting analysis, not invoice-vs-contract or
invoice-vs-output comparison, and it deserves to be turned on deliberately,
matter by matter, not defaulted on. `"auto"` picks per call based on
whether a transcript was actually fetched for it (most won't have one) —
it never fetches or requests one itself.

## Status: Phase 1 + Phase 2 + Phase 3 + Phase 3.5 + Billing Integrity

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
  `sources/` boundary claim for real — `sources/compliance.py` plus a fix
  in `ingest/correspond.py` (a `has_documents` flag so a domain with no
  documents by design, like this one, doesn't get the same "documents but
  no version events" warning as a redline matter whose documents produced
  zero version events) was the entire cost; `ingest/diff/metrics/report`
  didn't change at all.
- **Billing integrity** — named-timekeeper invoice-audit flags
  (`mcp/billing.py`, `metrics/billing_integrity.py`), off by default
  (`billing.enabled: false`). Invoice line items are itemized in-session
  into `raw_data["billing"]` the same way correspondence already is (no
  e-billing MCP connector exists — invoices are filed in iManage like any
  other document). Includes an optional, separately-gated call-attendance/
  transcript check (`billing.call_analysis`, off by default — `mcp/calls.py`).
  See the guardrail carve-out above.

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
   correspondence for the matter. For billing integrity (if enabled), find
   invoice documents filed in iManage and itemize them (timekeeper, date,
   hours, narrative) into `raw_data["billing"]`. For call analysis (if
   enabled), pull calendar events via the Microsoft 365 calendar tools
   (attendees are a hard fact) and, only where a transcript actually
   exists, a `meeting-transcript:///` resource for per-speaker seconds,
   into `raw_data["calls"]`.
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
(`firm_domains`) — no separate config needed. If that finds nothing (e.g.
compliance-domain matters, which have zero version events by design),
`run()` falls back to correspondence sender domains instead.

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

- `domain` — `redline` (default) or `compliance`. Selects the `SourceAdapter`
  (see "How data gets in" and "Extending" below): `redline` enumerates
  documents/versions and diffs them in addition to correspondence;
  `compliance` is correspondence-only (no documents, tone/escalation
  scoring only).
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
- `billing.enabled` (default `false`) — turns on named-timekeeper
  invoice-audit flags (see the guardrail carve-out above). `billing.window_days`
  (default 1) — calendar days either side of a billed date to search for
  matching correspondence. This only governs an ordinary daily
  `TimeEntry`; a period-level summary line (`TimeEntry.period_start` set —
  e.g. a single fee-earner total on an invoice with no day-by-day
  breakdown, `entry_date` as the period end) instead matches anything
  inside that billed period, since a tight day-window around the period's
  end date would miss nearly all of it. `billing.hours_min_to_flag` (default 0.5) — entries
  billed below this are too small to usefully flag. `billing.hours_per_100_words_threshold`
  (default 1.5) — flags an entry whose hours are disproportionate to the
  words of matching correspondence found. `billing.rate_caps` (a
  timekeeper-name-to-rate map, read off the engagement letter) — flags any
  invoiced rate above the contracted one for that name, unconditionally
  (not gated by `hours_min_to_flag`): a deterministic contract check, not a
  heuristic, and the most defensible of the billing-integrity checks for
  that reason. Unaffected by `anonymize_authors`.
- `billing.call_analysis` (default `"off"`) — `"attendance"` flags a
  confirmed call attendee with no correspondence around the call
  (`call_no_output`); `"transcript"` flags a confirmed attendee whose
  meeting transcript shows under `billing.call_min_speaking_seconds`
  (default 30.0) of speaking (`call_no_contribution`) — only fires when a
  transcript was actually fetched for that call; `"auto"` picks per call by
  what data exists. Read the guardrail carve-out above before turning on
  `"transcript"` or `"auto"` — it's a real step up in sensitivity over
  every other check here. Matching a `TimeEntry.timekeeper_name` to a
  `CallRecord` attendee identity is a name-token heuristic
  (`metrics/billing_integrity.py`'s `_name_matches_identity`), not exact —
  a miss is a silent non-match, never a wrong one.

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
