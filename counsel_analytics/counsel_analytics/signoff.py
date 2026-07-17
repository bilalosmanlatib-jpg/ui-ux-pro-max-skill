"""Sign-off / audit-trail layer.

Deliberately separate from `models.py`: this module records *who
internally reviewed and approved something* — ordinary accountability
data — which is a different concern from the analytics domain models,
whose guardrail is "never profile a named individual." Keeping the two
apart is what makes it obvious `reviewer`/`reason` are about the reviewer's
own decision, never commentary about a named external person (e.g.
counsel).

Storage is an append-only JSONL log with a lightweight hash chain
(`prev_record_hash`/`record_hash`) so editing or deleting a past line is
detectable via `verify_chain()`. No external timestamping, no signatures,
no database — those are explicitly not needed at this stage.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel

from counsel_analytics.models import MatterMetrics

Decision = Literal["approve", "flag", "escalate"]


class SignOffRecord(BaseModel):
    schema_version: int = 1
    matter_workspace_id: str
    snapshot_hash: str
    decision: Decision
    reviewer: str
    reviewer_source: Literal["cli_flag", "mcp_user_info"] = "cli_flag"
    reason: str
    signed_at: datetime
    prev_record_hash: Optional[str] = None
    record_hash: Optional[str] = None


def snapshot_hash(matter_metrics: MatterMetrics) -> str:
    """Hash of the evidence a sign-off applies to. Excludes `generated_at`
    (a run timestamp, not evidence) so re-running on unchanged data
    reproduces the same hash — that's what makes staleness detection
    meaningful rather than trivially true on every re-run."""
    payload = matter_metrics.model_dump(mode="json", exclude={"generated_at"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_record_hash(record: SignOffRecord) -> str:
    payload = record.model_dump(mode="json", exclude={"record_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def read_signoffs(log_path: Path) -> list[SignOffRecord]:
    if not log_path.exists():
        return []
    records = []
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(SignOffRecord.model_validate_json(line))
    return records


def append_signoff(record: SignOffRecord, log_path: Path) -> SignOffRecord:
    existing = read_signoffs(log_path)
    prev_hash = existing[-1].record_hash if existing else None
    finalized = record.model_copy(update={"prev_record_hash": prev_hash})
    finalized = finalized.model_copy(update={"record_hash": compute_record_hash(finalized)})

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(finalized.model_dump_json() + "\n")
    return finalized


def latest_signoff_for_matter(log_path: Path, matter_workspace_id: str) -> Optional[SignOffRecord]:
    matching = [r for r in read_signoffs(log_path) if r.matter_workspace_id == matter_workspace_id]
    if not matching:
        return None
    return max(matching, key=lambda r: r.signed_at)


def verify_chain(log_path: Path) -> tuple[bool, Optional[int]]:
    """Recomputes each record's hash and checks the prev/record_hash
    linkage. Returns (True, None) for an intact (or absent/empty) log,
    else (False, index_of_first_bad_line)."""
    records = read_signoffs(log_path)
    prev_hash: Optional[str] = None
    for idx, record in enumerate(records):
        if record.prev_record_hash != prev_hash:
            return False, idx
        expected_hash = compute_record_hash(record)
        if record.record_hash != expected_hash:
            return False, idx
        prev_hash = record.record_hash
    return True, None
