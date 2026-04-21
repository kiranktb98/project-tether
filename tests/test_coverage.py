"""Tests for tether coverage display and ImpactResult confidence calculation."""

from __future__ import annotations

from tether.coverage.display import (
    FeatureCoverage,
    OverallCoverage,
    _bar,
    _compute_feature_coverage,
    _compute_overall,
)
from tether.ledger.schema import EdgeCase, EdgeCaseFrequency, Feature, FeatureStatus
from tether.plan.impact import FeatureRisk, ImpactResult


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_feature(
    fid: str = "f1",
    edge_cases: list[tuple[str, bool, str | None]] | None = None,
) -> Feature:
    """Build a Feature with edge cases. Each tuple: (frequency, must_handle, test_file)."""
    f = Feature(id=fid, name=f"Feature {fid}", status=FeatureStatus.active, files=[])
    for i, (freq, mh, tf) in enumerate(edge_cases or [], start=1):
        f.edge_cases.append(
            EdgeCase(
                id=f"e{i}",
                description=f"edge case {i}",
                frequency=EdgeCaseFrequency(freq),
                rationale="test",
                must_handle=mh,
                test_file=tf,
            )
        )
    return f


# ── _bar helper ───────────────────────────────────────────────────────────────


def test_bar_full():
    assert _bar(10, 10, width=10) == "██████████"


def test_bar_empty():
    assert _bar(0, 10, width=10) == "░░░░░░░░░░"


def test_bar_half():
    result = _bar(5, 10, width=10)
    assert result.count("█") == 5
    assert result.count("░") == 5


def test_bar_zero_max():
    result = _bar(0, 0, width=8)
    assert result == "░░░░░░░░"


# ── FeatureCoverage ───────────────────────────────────────────────────────────


def test_feature_coverage_all_tested(tmp_path):
    tf = str(tmp_path / "test_foo.py")
    (tmp_path / "test_foo.py").write_text("# stub")
    f = _make_feature("f1", [
        ("high",   True,  tf),
        ("medium", True,  tf),
        ("low",    False, None),
    ])
    fc = _compute_feature_coverage(f)
    assert fc.must_handle_total == 2
    assert fc.must_handle_tested == 2
    assert fc.coverage_pct == 100.0
    assert fc.counts["high"] == 1
    assert fc.counts["medium"] == 1
    assert fc.counts["low"] == 1


def test_feature_coverage_no_tests():
    f = _make_feature("f1", [
        ("high", True, None),
        ("medium", True, None),
    ])
    fc = _compute_feature_coverage(f)
    assert fc.must_handle_total == 2
    assert fc.must_handle_tested == 0
    assert fc.coverage_pct == 0.0


def test_feature_coverage_no_edge_cases():
    f = _make_feature("f1", [])
    fc = _compute_feature_coverage(f)
    assert fc.must_handle_total == 0
    assert fc.coverage_pct == 100.0  # vacuously 100%


def test_feature_coverage_partial(tmp_path):
    tf = str(tmp_path / "test_x.py")
    (tmp_path / "test_x.py").write_text("# stub")
    f = _make_feature("f1", [
        ("high",   True,  tf),
        ("high",   True,  None),   # missing test
        ("medium", True,  tf),
    ])
    fc = _compute_feature_coverage(f)
    assert fc.must_handle_total == 3
    assert fc.must_handle_tested == 2
    assert abs(fc.coverage_pct - 66.67) < 0.1


# ── OverallCoverage ───────────────────────────────────────────────────────────


def test_overall_aggregates_correctly(tmp_path):
    tf = str(tmp_path / "t.py")
    (tmp_path / "t.py").write_text("# stub")

    f1 = _make_feature("f1", [("high", True, tf), ("medium", True, None)])
    f2 = _make_feature("f2", [("low", False, None), ("high", True, tf)])

    fcs = [_compute_feature_coverage(f1), _compute_feature_coverage(f2)]
    overall = _compute_overall(fcs)

    assert overall.total_features == 2
    assert overall.total_edge_cases == 4
    assert overall.must_handle_total == 3    # f1:2 + f2:1
    assert overall.must_handle_tested == 2   # f1:1 + f2:1
    assert overall.freq_counts["high"] == 2
    assert overall.freq_counts["medium"] == 1
    assert overall.freq_counts["low"] == 1


# ── ImpactResult.confidence ───────────────────────────────────────────────────


def _make_result(*levels: str) -> ImpactResult:
    risks = [
        FeatureRisk(feature_id=f"f{i}", feature_name=f"F{i}", level=lvl, reason="r")
        for i, lvl in enumerate(levels, 1)
    ]
    return ImpactResult(
        file_path="x.py", intent="change", affected_features=[], risks=risks
    )


def test_confidence_high_all_same():
    r = _make_result("medium", "medium", "medium")
    assert r.confidence == "high"


def test_confidence_high_adjacent():
    r = _make_result("low", "medium", "low")
    assert r.confidence == "high"


def test_confidence_medium_span_two():
    # none(0) → medium(2): span = 2 → medium confidence
    r = _make_result("none", "none", "medium")
    assert r.confidence == "medium"


def test_confidence_low_none_to_high():
    # none(0) → high(3): span = 3 → low confidence
    r = _make_result("none", "medium", "high")
    assert r.confidence == "low"


def test_confidence_low_all_levels():
    r = _make_result("none", "low", "medium", "high")
    assert r.confidence == "low"


def test_confidence_no_risks():
    r = _make_result()
    assert r.confidence == "high"


# ── ImpactResult.risk_distribution ───────────────────────────────────────────


def test_risk_distribution_counts():
    r = _make_result("none", "low", "low", "medium", "high", "high", "high")
    dist = r.risk_distribution
    assert dist["none"] == 1
    assert dist["low"] == 2
    assert dist["medium"] == 1
    assert dist["high"] == 3


def test_risk_distribution_empty():
    r = _make_result()
    dist = r.risk_distribution
    assert all(v == 0 for v in dist.values())
