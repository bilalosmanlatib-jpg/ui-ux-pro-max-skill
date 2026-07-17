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


class Settings(BaseModel):
    matter_ids: list[str]
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
