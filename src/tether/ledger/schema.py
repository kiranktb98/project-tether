"""Pydantic models for the feature ledger."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class FeatureStatus(str, Enum):
    active = "active"
    building = "building"
    removing = "removing"
    deprecated = "deprecated"


class EdgeCaseFrequency(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"
    negligible = "negligible"


class EdgeCase(BaseModel):
    id: str                                # e.g. "e1"
    description: str
    frequency: EdgeCaseFrequency
    rationale: str = ""
    must_handle: bool = False
    confidence: float = 0.5
    test_file: str | None = None           # relative path to generated pytest file


class EdgeCaseStats(BaseModel):
    total: int = 0
    must_handle: int = 0
    gated: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    negligible: int = 0
    average_confidence: float = 0.0


class HistoryEntry(BaseModel):
    action: str                            # added|modified|marked_for_removal|removed
    at: datetime
    reason: str = ""


class Feature(BaseModel):
    id: str                                # e.g. "f1"
    name: str
    description: str = ""
    status: FeatureStatus = FeatureStatus.active
    files: list[str] = Field(default_factory=list)
    edge_cases: list[EdgeCase] = Field(default_factory=list)
    edge_case_stats: EdgeCaseStats = Field(default_factory=EdgeCaseStats)
    history: list[HistoryEntry] = Field(default_factory=list)

    def add_history(self, action: str, reason: str = "") -> None:
        self.history.append(HistoryEntry(
            action=action,
            at=datetime.now(timezone.utc),
            reason=reason,
        ))


class Ledger(BaseModel):
    version: int = 1
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    features: list[Feature] = Field(default_factory=list)

    def next_feature_id(self) -> str:
        """Return the next available feature ID (f1, f2, ...)."""
        existing = {f.id for f in self.features}
        n = 1
        while f"f{n}" in existing:
            n += 1
        return f"f{n}"

    def get_feature(self, feature_id: str) -> Feature | None:
        for f in self.features:
            if f.id == feature_id:
                return f
        return None

    def bump_version(self) -> None:
        self.version += 1
        self.last_updated = datetime.now(timezone.utc)
