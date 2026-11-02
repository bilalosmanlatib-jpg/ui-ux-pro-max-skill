---
name: counsel-analytics
description: "Run the counsel-analytics pipeline (turnaround, redline-volume, clause re-argument, tone/escalation, and named-timekeeper billing-integrity analysis) for one or more iManage matters, and refresh the live Counsel Analytics dashboard with the results. Triggers: 'run counsel analytics on <matter>', 'analyze legal fees for <matter>', 'update the counsel analytics dashboard', 'check in on <matter>'s turnaround/tone', 'audit the invoice for <matter>'."
---

# Counsel Analytics

Packages the manual procedure used to analyze a matter (search iManage →
fetch documents/correspondence/invoices → run the `counsel-analytics` CLI →
refresh the live dashboard) into one repeatable playbook. Repo:
`/home/user/ui-ux-pro-max-skill/counsel_analytics` (Python, venv at
`.venv`). Dashboard: `https://claude.ai/artifact/5XARJwshKRGQAyogEyPTvx`
(a Dashboard-type Artifact — always update this one in place, never create
a new dashboard for a routine run).

**Read `counsel_analytics/README.md` first** if anything below is unclear
about domains, config fields, or the billing-integrity guardrail carve-out.
This skill does not restate that reasoning — only the mechanics.

## Prerequisites

- iManage Work and Microsoft 365 MCP tools connected in this session
  (`search_workspaces`, `get_workspace_profile`, `get_container_children`,
  `get_document_versions`, `download_document`, `outlook_email_search`).
- `.venv/bin/counsel-analytics` exists. If not: `cd counsel_analytics &&
  python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`.

## One matter, inline (the common case)

1. **Resolve**: if given a name not an id, call `search_workspaces` and
   take `topMatchingId`.
2. **Profile**: `get_workspace_profile(workspace_id)`.
3. **Enumerate documents**: `get_container_children(workspace_id,
   "workspace")` → top folders → one level of `get_container_children` on
   each → for any document with 2+ versions, `get_document_versions` +
   `download_document` (loop the cursor) for every version's text. Zero
   multi-version documents is a legitimate, common outcome — don't treat it
   as an error, and don't over-search for documents that aren't there.
4. **Enumerate correspondence**: `outlook_email_search` with a query from
   the matter's distinctive name, limit 25, up to 2 pages. Drop generic
   firm-wide digests (recurring internal reports, daily digest emails,
   admin/travel lists) — keep only messages substantively about this
   matter. Aim for ~30-50 relevant messages, not an exhaustive pull.
5. **Enumerate billing (only if asked, or an invoice is named/attached)**:
   find the invoice document (PDF/Excel, usually filed under a
   "Reporting"/"Invoices"-named folder, or point you directly at an email
   with it attached), `download_document` it, and itemize each line into
   `{timekeeper, role, date, hours, rate, amount, currency, narrative}` —
   use your own judgment reading the invoice text/table; don't invent a
   name or hours for a line you can't read cleanly, just skip it.
5b. **Enumerate calls (only if the user has explicitly asked for call
   analysis — never turn this on by inference from "audit the invoice")**:
   pull calendar events for the matter window via the Microsoft 365
   calendar tools into `{start, end, subject, attendees}` per event —
   attendees are a hard fact, itemize them as given. Only where a Teams
   transcript actually exists for that event (most won't — don't go
   looking hard for one), read it via a `meeting-transcript:///` resource
   and sum seconds spoken per identifiable speaker into
   `speakingSeconds: {identity: seconds}`. If the user asked for
   `"transcript"` mode specifically but no transcript exists for a call,
   say so rather than silently falling back — `"auto"` mode is the one
   that's meant to fall back quietly.
6. **Classify**: `internal_domains: ["ninetyone.com"]`. For `firm_domains`,
   identify which external sender domain(s) are law firms (cues: "LLP",
   "Partner/Director, Legal" signature blocks) vs. counterparty/other
   business domains (leave those unmapped → classified `unknown`). Domain:
   `redline` if step 3 found a multi-version document, else `compliance`.
7. **Assemble** `raw_data.json` (see `mcp/client.py`'s `SessionMCPClient`
   docstring for the exact shape — `workspaces`/`container_children`/
   `document_versions`/`document_text`/`correspondence`/`billing`/`calls`,
   the last only if step 5b ran) and `config.yaml` (`matter_ids`, `domain`,
   `mcp_client: session`, `internal_domains`, `firm_domains`,
   `correspondence_window_days: 3`, `anonymize_authors: false`,
   `output_dir: "./data/output/<slug>"` where slug = workspace id with `!`
   → `_`, `billing.enabled: true` only if step 5 ran, and
   `billing.call_analysis` set to `"attendance"`/`"transcript"`/`"auto"`
   only if step 5b ran and the user specified which — never default it to
   anything but `"off"`). Write both under
   `counsel_analytics/data/output/<slug>/_inputs/`.
8. **Run**: from `counsel_analytics/`, `.venv/bin/counsel-analytics run
   --config data/output/<slug>/_inputs/config.yaml --raw-data
   data/output/<slug>/_inputs/raw_data.json`, then `.venv/bin/counsel-analytics
   packet --config ... --report data/output/<slug>/<slug>.json --out
   data/output/<slug>/<slug>_packet.md`.
9. Report back: what the report/packet actually found, in plain language —
   not just "done." If billing flags fired, name them (they're the one
   place a timekeeper name is meant to appear).

## Several matters at once

Use the `counsel-analytics-pipeline` Workflow instead of repeating the
inline procedure serially — it fans the per-matter fetch+run out in
parallel and does the rollup step automatically when 2+ matters resolve to
the same firm. Author it with the Workflow tool using the same step
1–9 logic above as the per-matter agent prompt (see the live run in this
session's history for a worked example), passing `args: {matters: [{name,
workspaceId}, ...]}`.

## Refreshing the live dashboard

The dashboard reads three datasets (`matters`, `metrics`, `pipeline_log`),
each an uploaded JSON file the dashboard's own `dash` runtime reads — it is
**not** auto-live from iManage; it only updates when you push a refresh
after a run. The canonical, accumulating copies of these three arrays live
at `counsel_analytics/data/dashboard/{matters,metrics,pipeline_log}.json`
(already seeded with the real Grand Bara Djibouti run as of 2026-11-02 —
`data/` is gitignored, so if a fresh checkout is missing them, initialize
each as `[]` and expect the dashboard to briefly disagree with the running
session's memory until the next refresh repopulates them). A fourth
dataset, `billing_signals`, carries the named-timekeeper flags from
`MatterMetrics.billing_signals` — it's already live on the dashboard
(`data/dashboard/billing_signals.json`) and follows the exact same
upsert/upload/update loop below; only populate it when billing was enabled
for the run (step 5), and never let it anywhere near the
matter/firm-scoped `metrics` dataset.

**Do not overwrite dashboard history.** Each refresh must *upsert*, not
replace:
- `matters.json`: one row per `workspace_id` — update in place if the
  workspace_id already exists, append if new.
- `metrics.json`: one row per `(workspace_id, metric_name)` — replace that
  row with the latest value (the most recent run's number), keep every
  other matter's rows untouched.
- `pipeline_log.json`: append the new run's stage rows (`run_id`,
  `workspace_id`, `display_name`, `seq`, `stage`, `status`, `detail`) —
  never delete prior runs' rows; this is the audit trail the process
  visualization reads.
- `billing_signals.json` (only if billing ran): one row per
  `(workspace_id, timekeeper_name, entry_date, flag)` — replace that row if
  it already exists (a re-run may refine a note/evidence), append if new;
  never delete prior runs' rows.

Then:
1. Load Artifact `action: "publish"`, `url:
   "https://claude.ai/artifact/5XARJwshKRGQAyogEyPTvx"`, `asset: true`,
   `file_path` set to each updated JSON file **one call per file**
   (JSON/CSV/text assets upload one at a time, not via `file_paths`) —
   note each returned `/_blob/<id>` url.
2. `ArtifactData` `action: "update"` on `collection: "datasets"`,
   `doc_id`: `"matters"` / `"metrics"` / `"pipeline_log"` /
   `"billing_signals"` for whichever file(s) changed, setting `source.url`
   to the new blob id and `updated: {at: "<ISO timestamp>", by:
   "counsel-analytics skill"}`. Use `if_version` from the dataset doc's
   last-read `version` (read it first if you don't already have it from
   this session).
3. Confirm with one `ArtifactData` `list` of `datasets` — don't open or
   screenshot the page; the type's own runtime renders it.

## Guardrails (binding, not optional)

- Turnaround/volume/clause-reargument/tone metrics are matter/document/firm
  level only — never a named individual. Billing-integrity signals are the
  one deliberate, separate exception (see README) — keep them in their own
  dataset/section, never merged into the metrics above.
- This touches real client/matter data. Confirm scope with the user before
  pulling a *new* matter that hasn't already been discussed in the
  conversation — don't silently expand to matters nobody asked about.
- Never set `billing.call_analysis` to anything but `"off"` unless the user
  has explicitly asked for call analysis in this conversation —
  `"attendance"` and `"transcript"` are a sharper line than the rest of the
  billing carve-out (see README) and must never be inferred from a plain
  "audit the invoice" request.
- Correspondence pulls stay bounded (~30-50 relevant messages) — this is a
  review tool, not a bulk export.
