"""Regression tests for pytest summary parsing."""

from tether.watch.checks.targeted_tests import TestRunResult as TargetedTestRunResult
from tether.watch.checks.targeted_tests import _parse_pytest_summary


def test_parse_pytest_summary_counts_skipped_only_runs() -> None:
    result = TargetedTestRunResult(feature_id="f1", feature_name="Feature one")
    result.output = "======================== 8 skipped in 0.12s ========================\n"

    _parse_pytest_summary(result)

    assert result.skipped == 8
    assert result.passed == 0
    assert result.failed == 0
    assert result.errors == 0
