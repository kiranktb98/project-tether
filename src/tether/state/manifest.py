"""Session manifest — tracks the running session's metadata."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def generate_session_id() -> str:
    """Return a short unique session identifier."""
    return uuid.uuid4().hex[:12]


class SessionManifest:
    """Lightweight in-memory + on-disk session state."""

    def __init__(self, tether_dir: Path) -> None:
        self.tether_dir = tether_dir
        self.session_id: str = generate_session_id()
        self.started_at: datetime = datetime.now(timezone.utc)
        self.files_changed: int = 0
        self.checks_run: int = 0
        self.drift_events: dict[str, int] = {
            "none": 0, "soft": 0, "intentional": 0, "hard": 0, "critical": 0
        }
        self.total_cost_usd: float = 0.0
        self.ledger_version_start: int = 1
        self.ledger_version_end: int = 1
        self._path: Path = tether_dir / "session.yaml"

    def record_file_change(self) -> None:
        self.files_changed += 1

    def record_check(self) -> None:
        self.checks_run += 1

    def record_drift(self, severity: str) -> None:
        severity = severity.lower()
        if severity in self.drift_events:
            self.drift_events[severity] += 1

    def add_cost(self, cost_usd: float) -> None:
        self.total_cost_usd += cost_usd

    def save(self) -> None:
        data = {
            "session_id": self.session_id,
            "started_at": self.started_at.isoformat(),
            "files_changed": self.files_changed,
            "checks_run": self.checks_run,
            "drift_events": self.drift_events,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "ledger_version_start": self.ledger_version_start,
            "ledger_version_end": self.ledger_version_end,
        }
        self._path.write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, tether_dir: Path) -> "SessionManifest | None":
        path = tether_dir / "session.yaml"
        if not path.exists():
            return None
        manifest = cls(tether_dir)
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        manifest.session_id = data.get("session_id", manifest.session_id)
        manifest.files_changed = data.get("files_changed", 0)
        manifest.checks_run = data.get("checks_run", 0)
        manifest.drift_events = data.get("drift_events", manifest.drift_events)
        manifest.total_cost_usd = data.get("total_cost_usd", 0.0)
        manifest.ledger_version_start = data.get("ledger_version_start", 1)
        manifest.ledger_version_end = data.get("ledger_version_end", 1)
        return manifest
