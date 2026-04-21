"""JSONL cost/event log and tether directory bootstrapping."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Directory bootstrap
# ---------------------------------------------------------------------------

TETHER_SUBDIRS = [
    "ledger.history",
    "tests",
    "reports",
    "cache/files",
]


def ensure_tether_dir(tether_dir: str | Path = ".tether") -> Path:
    """Create .tether/ and all required sub-directories."""
    base = Path(tether_dir)
    for subdir in TETHER_SUBDIRS:
        (base / subdir).mkdir(parents=True, exist_ok=True)
    return base


# ---------------------------------------------------------------------------
# JSONL event log
# ---------------------------------------------------------------------------

class EventLog:
    """Append-only JSONL log for model calls, costs, and check events.

    Each line is a self-contained JSON object with at minimum:
      {"ts": "<iso>", "event": "<kind>", ...extra fields...}
    """

    def __init__(self, tether_dir: str | Path = ".tether") -> None:
        base = Path(tether_dir)
        base.mkdir(parents=True, exist_ok=True)
        self._path = base / "events.jsonl"

    def append(self, event: str, **kwargs: Any) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **kwargs,
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")

    def log_model_call(
        self,
        *,
        prompt_name: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        session_id: str = "",
    ) -> None:
        self.append(
            "model_call",
            prompt_name=prompt_name,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost_usd, 6),
            session_id=session_id,
        )

    def log_check(
        self,
        *,
        file_path: str,
        check_type: str,
        verdict: str,
        session_id: str = "",
    ) -> None:
        self.append(
            "check",
            file_path=file_path,
            check_type=check_type,
            verdict=verdict,
            session_id=session_id,
        )

    def total_cost_usd(self) -> float:
        """Sum all model_call costs from the log."""
        total = 0.0
        if not self._path.exists():
            return total
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("event") == "model_call":
                        total += entry.get("cost_usd", 0.0)
                except json.JSONDecodeError:
                    pass
        return total

    def session_cost_usd(self, session_id: str) -> float:
        """Sum costs for a specific session."""
        total = 0.0
        if not self._path.exists():
            return total
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if (entry.get("event") == "model_call"
                            and entry.get("session_id") == session_id):
                        total += entry.get("cost_usd", 0.0)
                except json.JSONDecodeError:
                    pass
        return total


# ---------------------------------------------------------------------------
# Cost calculation helpers
# ---------------------------------------------------------------------------

# Pricing per million tokens (USD) as of 2026-04
_MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
}

_DEFAULT_PRICING = {"input": 1.0, "output": 5.0}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for a model call."""
    pricing = _MODEL_PRICING.get(model, _DEFAULT_PRICING)
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost
