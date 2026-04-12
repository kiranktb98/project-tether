"""Read, write, and version the feature ledger."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

from tether.ledger.schema import Ledger


def _serialize_ledger(ledger: Ledger) -> dict:
    """Convert ledger to a plain dict suitable for YAML serialization."""
    data = ledger.model_dump(mode="json")
    # Convert datetime strings to more readable ISO format
    return data


def _deserialize_ledger(data: dict) -> Ledger:
    """Build a Ledger from a plain dict (as loaded from YAML)."""
    return Ledger.model_validate(data)


def load_ledger(ledger_path: str | Path) -> Ledger:
    """Load and validate ledger.yaml. Returns empty Ledger if file absent."""
    path = Path(ledger_path)
    if not path.exists():
        return Ledger()
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if raw is None:
        return Ledger()
    return _deserialize_ledger(raw)


def save_ledger(
    ledger: Ledger,
    ledger_path: str | Path,
    history_dir: str | Path | None = None,
    *,
    snapshot: bool = True,
) -> Path:
    """Persist ledger to disk. Optionally snapshot to history_dir.

    Bumps version and last_updated before saving.
    """
    ledger.bump_version()

    path = Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = _serialize_ledger(ledger)
    with path.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)

    if snapshot and history_dir is not None:
        _snapshot(path, history_dir, ledger.version)

    return path


def _snapshot(ledger_path: Path, history_dir: str | Path, version: int) -> Path:
    """Copy ledger.yaml to history_dir/v<N>.yaml."""
    dest_dir = Path(history_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"v{version}.yaml"
    shutil.copy2(ledger_path, dest)
    return dest


def snapshot_ledger(
    ledger_path: str | Path,
    history_dir: str | Path,
    version: int,
) -> Path:
    """Public helper to take a manual snapshot (used by verify)."""
    return _snapshot(Path(ledger_path), history_dir, version)


def validate_ledger_file(ledger_path: str | Path) -> list[str]:
    """Validate a ledger YAML file. Returns a list of error strings (empty = valid)."""
    path = Path(ledger_path)
    if not path.exists():
        return [f"Ledger file not found: {path}"]
    try:
        with path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        if raw is None:
            return ["Ledger file is empty"]
        _deserialize_ledger(raw)
        return []
    except yaml.YAMLError as e:
        return [f"YAML parse error: {e}"]
    except Exception as e:
        return [f"Validation error: {e}"]
