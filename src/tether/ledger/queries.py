"""Pure query functions over the feature ledger."""

from __future__ import annotations

from pathlib import Path

from tether.ledger.schema import EdgeCase, EdgeCaseStats, Feature, Ledger


def features_touching_file(ledger: Ledger, file_path: str | Path) -> list[Feature]:
    """Return features whose `files` list contains file_path.

    Comparison is done with normalized, forward-slash paths so that
    Windows and Unix paths compare correctly.
    """
    target = _norm(file_path)
    return [
        f for f in ledger.features
        if any(_norm(fp) == target for fp in f.files)
    ]


def feature_tests_dir(feature: Feature, tests_base_dir: str | Path) -> Path:
    """Return the directory that holds generated tests for a given feature."""
    return Path(tests_base_dir) / f"feature_{feature.id}"


def feature_has_generated_tests(feature: Feature, tests_base_dir: str | Path) -> bool:
    """Return True if the feature has any generated pytest files.

    This checks both ledger-linked edge cases and the on-disk feature test
    directory so verify can recover from interrupted bootstrap runs.
    """
    if any(ec.test_file for ec in feature.edge_cases):
        return True

    test_dir = feature_tests_dir(feature, tests_base_dir)
    return any(test_dir.glob("test_*.py"))


def must_handle_edge_cases(feature: Feature) -> list[EdgeCase]:
    """Return edge cases with must_handle=True for a feature."""
    return [ec for ec in feature.edge_cases if ec.must_handle]


def apply_must_handle_rule(edge_case: EdgeCase) -> bool:
    """Determine must_handle from frequency + rationale (never from model output).

    Rule:
      - high or medium frequency -> True
      - low + rationale mentions catastrophic/security/data-loss -> True
      - otherwise -> False
    """
    from tether.ledger.schema import EdgeCaseFrequency

    if edge_case.frequency in (EdgeCaseFrequency.high, EdgeCaseFrequency.medium):
        return True
    if edge_case.frequency == EdgeCaseFrequency.low:
        rationale_lower = edge_case.rationale.lower()
        catastrophic_keywords = [
            "catastrophic", "security", "data loss", "data-loss",
            "breach", "crash", "corruption", "irrecoverable",
        ]
        if any(kw in rationale_lower for kw in catastrophic_keywords):
            return True
    return False


def compute_edge_case_confidence(edge_case: EdgeCase) -> float:
    """Return a deterministic confidence score for an edge case."""
    from tether.ledger.schema import EdgeCaseFrequency

    base = {
        EdgeCaseFrequency.high: 0.95,
        EdgeCaseFrequency.medium: 0.8,
        EdgeCaseFrequency.low: 0.55,
        EdgeCaseFrequency.negligible: 0.25,
    }[edge_case.frequency]

    rationale_lower = edge_case.rationale.lower()
    if any(kw in rationale_lower for kw in ("catastrophic", "security", "data loss", "data-loss", "breach", "irrecoverable")):
        base = max(base, 0.85)

    if len(edge_case.description.strip()) < 12:
        base -= 0.08
    if len(edge_case.rationale.strip()) < 12:
        base -= 0.08

    return max(0.0, min(1.0, round(base, 2)))


def compute_feature_edge_case_stats(
    feature: Feature,
    *,
    confidence_gate: float = 0.8,
) -> EdgeCaseStats:
    """Aggregate edge-case counts and confidence stats for a feature."""
    stats = EdgeCaseStats()
    if not feature.edge_cases:
        return stats

    stats.total = len(feature.edge_cases)
    total_confidence = 0.0
    for ec in feature.edge_cases:
        total_confidence += ec.confidence
        if ec.must_handle:
            stats.must_handle += 1
        if ec.must_handle and ec.confidence >= confidence_gate:
            stats.gated += 1

        setattr(stats, ec.frequency.value, getattr(stats, ec.frequency.value) + 1)

    stats.average_confidence = round(total_confidence / stats.total, 2)
    return stats


def all_test_files_for_feature(feature: Feature) -> list[Path]:
    """Return all test file paths recorded on the feature's edge cases."""
    paths = []
    for ec in feature.edge_cases:
        if ec.test_file:
            paths.append(Path(ec.test_file))
    return paths


def features_by_status(ledger: Ledger, status: str) -> list[Feature]:
    """Return features with a given status string."""
    return [f for f in ledger.features if f.status.value == status]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _norm(path: str | Path) -> str:
    """Normalize a path to forward-slash string for comparison."""
    return str(path).replace("\\", "/")
