"""Core domain models.

These models are the contract between every layer (`ingest`, `diff`,
`metrics`, `report`) and never reference MCP tool names or payload shapes
directly — that translation lives entirely in `mcp/`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

AuthorSide = Literal["internal", "counsel", "unknown"]
Direction = Literal["up", "down", "flat"]
CorrespondenceSource = Literal["outlook", "imanage_email", "teams"]


class MatterRef(BaseModel):
    library: str
    workspace_id: str
    client_id: Optional[str] = None
    matter_id: Optional[str] = None
    firm: Optional[str] = None
    display_name: str


class DocumentRef(BaseModel):
    document_id: str
    name: str
    doc_type: Optional[str] = None


class VersionEvent(BaseModel):
    document_id_versioned: str
    version_no: int
    author_id: str
    author_side: AuthorSide
    timestamp: datetime
    size_bytes: Optional[int] = None
    imanage_comment: Optional[str] = None


class DiffResult(BaseModel):
    from_version: int
    to_version: int
    insertions: int
    deletions: int
    changed_tokens: int
    total_tokens: int
    changed_char_ratio: float
    added_text: list[str] = Field(default_factory=list)
    removed_text: list[str] = Field(default_factory=list)


class ClauseSegment(BaseModel):
    clause_id: str
    title: Optional[str] = None
    text: str
    version_no: int


class ClauseHistoryEntry(BaseModel):
    version_no: int
    segment: ClauseSegment
    was_changed: bool


class ClauseHistory(BaseModel):
    clause_id: str
    entries: list[ClauseHistoryEntry] = Field(default_factory=list)


class Message(BaseModel):
    timestamp: datetime
    sender_side: AuthorSide
    text: str
    subject: Optional[str] = None
    firm: Optional[str] = None


class CommentThread(BaseModel):
    matter_id: str
    source: CorrespondenceSource
    messages: list[Message] = Field(default_factory=list)


class Evidence(BaseModel):
    doc_ids: list[str] = Field(default_factory=list)
    version_pair: Optional[tuple[int, int]] = None
    timestamps: list[datetime] = Field(default_factory=list)
    clause_ids: list[str] = Field(default_factory=list)
    quotes: list[str] = Field(default_factory=list)


class Metric(BaseModel):
    """`note` carries the human-readable "because" sentence, e.g. bottleneck
    attribution or a hypothesis caveat (volume/tone metrics are labeled as
    hypotheses, not verdicts)."""

    name: str
    value: float
    unit: str
    direction: Direction
    evidence: Evidence
    note: Optional[str] = None


class TimeEntry(BaseModel):
    """One billed line item from an invoice filed against the matter.
    Extracted in-session (no e-billing MCP connector is connected) the same
    way document text/correspondence are: whoever assembles `raw_data`
    itemizes the invoice and writes it to `raw_data["billing"]`.

    `period_start` is only set for a period-level summary line (e.g. a
    fee-earner total on an invoice with no day-by-day breakdown) -- it
    marks the start of the billed period, with `entry_date` as the period
    end. Leave it unset for an ordinary daily entry; the observed-activity
    checks then match against a single day instead of a range."""

    matter_id: str
    source_document_id: Optional[str] = None
    timekeeper_name: str
    timekeeper_role: Optional[str] = None
    entry_date: datetime
    period_start: Optional[datetime] = None
    hours: float
    rate: Optional[float] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    narrative: str = ""


class CallRecord(BaseModel):
    """One calendar/Teams meeting on the matter. `attendees` is identities
    (usually emails) confirmed present — a hard fact from the calendar, not
    an invoice's say-so. `speaking_seconds` is populated only when a
    transcript was available and fetched for this call (most won't have
    one); its absence is the normal case, not a data-quality problem."""

    matter_id: str
    source_event_id: Optional[str] = None
    start: datetime
    end: datetime
    subject: Optional[str] = None
    attendees: list[str] = Field(default_factory=list)
    speaking_seconds: dict[str, float] = Field(default_factory=dict)


class BillingSignal(BaseModel):
    """Named-timekeeper billing/invoice-audit flag — deliberately NOT a
    `Metric`. Scoped to the engagement's contractual right to review billed
    work against observable matter activity (invoice audit, not behavioral
    profiling); kept in its own list so it can never be merged into the
    aggregate, never-individual `metrics`/`clause_signals`. See the README
    guardrail section."""

    timekeeper_name: str
    timekeeper_role: Optional[str] = None
    entry_date: datetime
    hours: float
    narrative: str
    flag: str
    observed_activity_words: int
    note: str
    evidence: Evidence


class MatterMetrics(BaseModel):
    matter_ref: MatterRef
    version_events: list[VersionEvent] = Field(default_factory=list)
    metrics: list[Metric] = Field(default_factory=list)
    clause_signals: list[Metric] = Field(default_factory=list)
    billing_signals: list[BillingSignal] = Field(default_factory=list)
    generated_at: datetime


class CounterpartyRollup(BaseModel):
    firm: str
    matters: list[MatterRef] = Field(default_factory=list)
    metrics: list[Metric] = Field(default_factory=list)
    generated_at: datetime
