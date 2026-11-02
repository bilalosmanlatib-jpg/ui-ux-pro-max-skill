"""Load and validate `config.yaml` into a `Settings` object."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field


class Thresholds(BaseModel):
    reargument_similarity_threshold: float = 0.55
    reargument_ping_pong_rounds: int = 3


class PacketSettings(BaseModel):
    max_highlights: int = 8
    min_abs_value: float = 0.0


class BillingSettings(BaseModel):
    """Named-timekeeper invoice audit — off by default. Only takes effect
    when `raw_data["billing"]` has entries for the matter (invoices filed in
    iManage, itemized in-session the same way correspondence is). See the
    README guardrail section for why this is a deliberate, separate carve-out
    from the matter/firm-level analytics, not an extension of them."""

    enabled: bool = False
    window_days: int = 1
    hours_min_to_flag: float = 0.5
    hours_per_100_words_threshold: float = 1.5
    # Contracted hourly rate per timekeeper, read off the engagement letter
    # (e.g. a Supplemental Engagement Letter's rate-card section). Checked
    # unconditionally against every invoiced rate for that name, regardless
    # of hours_min_to_flag -- a wrong rate is a contract breach at any
    # volume, not a noisy signal to filter out.
    rate_caps: dict[str, float] = Field(default_factory=dict)
    # "off" (default): no call-based checks. "attendance": a timekeeper who
    # attended a call on the matter but produced no observable output
    # (correspondence) around it is flagged -- same proxy caveats as the
    # hours-vs-correspondence check, since attendance alone doesn't prove
    # idleness. "transcript": requires speaking_seconds (only present when a
    # transcript was fetched for that call) -- flags a confirmed attendee who
    # didn't speak; a real step up in sensitivity (see README). "auto": use
    # transcript where a call has one, fall back to attendance otherwise --
    # picks per call based on what data actually exists, never guesses.
    call_analysis: Literal["off", "attendance", "transcript", "auto"] = "off"
    call_min_speaking_seconds: float = 30.0


class Settings(BaseModel):
    matter_ids: list[str]
    domain: Literal["redline", "compliance"] = "redline"
    mcp_client: Literal["session", "direct"] = "session"
    internal_domains: list[str] = Field(default_factory=list)
    firm_domains: dict[str, str] = Field(default_factory=dict)
    correspondence_window_days: int = 3
    business_calendar: Literal["weekdays_only"] = "weekdays_only"
    thresholds: Thresholds = Field(default_factory=Thresholds)
    embedding_provider: Literal["none", "local", "api"] = "none"
    anonymize_authors: bool = False
    output_dir: str = "./data/output"
    packet: PacketSettings = Field(default_factory=PacketSettings)
    tone_lexicon_path: Optional[str] = None
    billing: BillingSettings = Field(default_factory=BillingSettings)


def load_settings(path: str | Path) -> Settings:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}. Copy config.example.yaml to "
            "config.yaml and fill in real values."
        )
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return Settings.model_validate(raw)
