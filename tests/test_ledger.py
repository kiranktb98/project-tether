"""Tests for ledger schema, store, and queries."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tether.ledger.queries import (
    apply_must_handle_rule,
    compute_edge_case_confidence,
    compute_feature_edge_case_stats,
    feature_tests_dir,
    features_touching_file,
    must_handle_edge_cases,
)
from tether.ledger.schema import (
    EdgeCase,
    EdgeCaseFrequency,
    Feature,
    FeatureStatus,
    Ledger,
)
from tether.ledger.store import load_ledger, save_ledger, validate_ledger_file


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def make_ledger() -> Ledger:
    ledger = Ledger()
    f1 = Feature(
        id="f1",
        name="Rate limiting",
        description="100 req/min per user",
        status=FeatureStatus.active,
        files=["src/ratelimiter.py", "src/middleware.py"],
    )
    f1.edge_cases.append(EdgeCase(
        id="e1",
        description="User exceeds limit",
        frequency=EdgeCaseFrequency.high,
        rationale="Common scenario",
        must_handle=True,
        test_file=".tether/tests/feature_f1/test_exceeds.py",
    ))
    f1.edge_cases.append(EdgeCase(
        id="e2",
        description="Clock skew",
        frequency=EdgeCaseFrequency.low,
        rationale="Rare but catastrophic data loss scenario",
        must_handle=True,
        test_file=".tether/tests/feature_f1/test_clock_skew.py",
    ))
    f1.add_history("added", "Initial implementation")

    f2 = Feature(
        id="f2",
        name="Admin override",
        description="Admins bypass rate limits",
        status=FeatureStatus.active,
        files=["src/ratelimiter.py", "src/auth.py"],
    )
    ledger.features.extend([f1, f2])
    return ledger


def test_ledger_version_starts_at_one() -> None:
    ledger = Ledger()
    assert ledger.version == 1


def test_next_feature_id() -> None:
    ledger = make_ledger()
    assert ledger.next_feature_id() == "f3"


def test_get_feature() -> None:
    ledger = make_ledger()
    assert ledger.get_feature("f1") is not None
    assert ledger.get_feature("f99") is None


# ---------------------------------------------------------------------------
# Store tests
# ---------------------------------------------------------------------------


def test_round_trip_empty_ledger(tmp_path: Path) -> None:
    ledger = Ledger()
    path = tmp_path / ".tether" / "ledger.yaml"
    save_ledger(ledger, path, snapshot=False)
    loaded = load_ledger(path)
    assert loaded.features == []


def test_round_trip_with_features(tmp_path: Path) -> None:
    ledger = make_ledger()
    path = tmp_path / "ledger.yaml"
    save_ledger(ledger, path, snapshot=False)
    loaded = load_ledger(path)
    assert len(loaded.features) == 2
    assert loaded.features[0].id == "f1"
    assert loaded.features[0].files == ["src/ratelimiter.py", "src/middleware.py"]


def test_save_bumps_version(tmp_path: Path) -> None:
    ledger = Ledger()
    assert ledger.version == 1
    path = tmp_path / "ledger.yaml"
    save_ledger(ledger, path, snapshot=False)
    assert ledger.version == 2


def test_snapshot_creates_history_file(tmp_path: Path) -> None:
    ledger = make_ledger()
    path = tmp_path / "ledger.yaml"
    history_dir = tmp_path / "history"
    save_ledger(ledger, path, history_dir=history_dir, snapshot=True)
    assert (history_dir / f"v{ledger.version}.yaml").exists()


def test_load_missing_ledger_returns_empty() -> None:
    loaded = load_ledger("/nonexistent/path/ledger.yaml")
    assert loaded.features == []


def test_validate_ledger_file_valid(tmp_path: Path) -> None:
    ledger = make_ledger()
    path = tmp_path / "ledger.yaml"
    save_ledger(ledger, path, snapshot=False)
    errors = validate_ledger_file(path)
    assert errors == []


def test_validate_ledger_file_missing(tmp_path: Path) -> None:
    errors = validate_ledger_file(tmp_path / "nonexistent.yaml")
    assert len(errors) == 1
    assert "not found" in errors[0]


# ---------------------------------------------------------------------------
# Query tests
# ---------------------------------------------------------------------------


def test_features_touching_file() -> None:
    ledger = make_ledger()
    hits = features_touching_file(ledger, "src/ratelimiter.py")
    assert len(hits) == 2
    ids = {f.id for f in hits}
    assert ids == {"f1", "f2"}


def test_features_touching_file_none() -> None:
    ledger = make_ledger()
    hits = features_touching_file(ledger, "src/unrelated.py")
    assert hits == []


def test_features_touching_file_windows_path() -> None:
    """Backslash paths should match forward-slash paths in ledger."""
    ledger = make_ledger()
    hits = features_touching_file(ledger, "src\\ratelimiter.py")
    assert len(hits) == 2


def test_feature_tests_dir() -> None:
    feature = Feature(id="f7", name="Test feature")
    result = feature_tests_dir(feature, ".tether/tests")
    assert str(result).replace("\\", "/") == ".tether/tests/feature_f7"


def test_must_handle_edge_cases() -> None:
    ledger = make_ledger()
    f1 = ledger.get_feature("f1")
    assert f1 is not None
    mh = must_handle_edge_cases(f1)
    assert len(mh) == 2  # both e1 and e2 are must_handle=True


def test_apply_must_handle_rule_high() -> None:
    ec = EdgeCase(id="e1", description="x", frequency=EdgeCaseFrequency.high, rationale="common")
    assert apply_must_handle_rule(ec) is True


def test_apply_must_handle_rule_medium() -> None:
    ec = EdgeCase(id="e1", description="x", frequency=EdgeCaseFrequency.medium, rationale="moderate")
    assert apply_must_handle_rule(ec) is True


def test_apply_must_handle_rule_low_catastrophic() -> None:
    ec = EdgeCase(id="e1", description="x", frequency=EdgeCaseFrequency.low,
                  rationale="rare but catastrophic data loss")
    assert apply_must_handle_rule(ec) is True


def test_apply_must_handle_rule_low_benign() -> None:
    ec = EdgeCase(id="e1", description="x", frequency=EdgeCaseFrequency.low,
                  rationale="minor inconvenience")
    assert apply_must_handle_rule(ec) is False


def test_apply_must_handle_rule_negligible() -> None:
    ec = EdgeCase(id="e1", description="x", frequency=EdgeCaseFrequency.negligible,
                  rationale="astronomically unlikely")
    assert apply_must_handle_rule(ec) is False


def test_compute_edge_case_confidence_high_common_case() -> None:
    ec = EdgeCase(
        id="e1",
        description="User exceeds limit under normal traffic",
        frequency=EdgeCaseFrequency.high,
        rationale="Common in production traffic",
    )
    assert compute_edge_case_confidence(ec) >= 0.9


def test_compute_edge_case_confidence_low_catastrophic_case() -> None:
    ec = EdgeCase(
        id="e1",
        description="Rare token corruption",
        frequency=EdgeCaseFrequency.low,
        rationale="Rare but catastrophic data loss event",
    )
    assert compute_edge_case_confidence(ec) >= 0.85


def test_compute_feature_edge_case_stats() -> None:
    feature = Feature(id="f1", name="Rate limiting")
    feature.edge_cases.extend([
        EdgeCase(
            id="e1",
            description="Common burst",
            frequency=EdgeCaseFrequency.high,
            rationale="Common",
            must_handle=True,
            confidence=0.95,
        ),
        EdgeCase(
            id="e2",
            description="Rare corruption",
            frequency=EdgeCaseFrequency.low,
            rationale="Rare but catastrophic data loss",
            must_handle=True,
            confidence=0.88,
        ),
        EdgeCase(
            id="e3",
            description="Astronomical case",
            frequency=EdgeCaseFrequency.negligible,
            rationale="extremely unlikely",
            must_handle=False,
            confidence=0.2,
        ),
    ])

    stats = compute_feature_edge_case_stats(feature, confidence_gate=0.8)
    assert stats.total == 3
    assert stats.must_handle == 2
    assert stats.gated == 2
    assert stats.high == 1
    assert stats.low == 1
    assert stats.negligible == 1
