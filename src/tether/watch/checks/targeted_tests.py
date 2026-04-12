"""Watch check: run tests for features affected by a file change."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from tether.ledger.queries import feature_tests_dir, features_touching_file
from tether.ledger.schema import Feature, Ledger


@dataclass
class TestRunResult:
    feature_id: str
    feature_name: str
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    newly_failing: list[str] = field(default_factory=list)
    output: str = ""

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.errors == 0


def run_single_test_file(
    feature: Feature,
    test_file: str | Path,
    max_runtime_seconds: int,
) -> TestRunResult:
    """Run pytest for a single generated test file."""
    result = TestRunResult(feature_id=feature.id, feature_name=feature.name)

    try:
        proc = subprocess.run(
            [
                sys.executable, "-m", "pytest",
                str(test_file),
                "-v", "--tb=short", "-q",
            ],
            capture_output=True,
            text=True,
            timeout=max_runtime_seconds + 5,
        )
        result.output = proc.stdout + proc.stderr
        _parse_pytest_summary(result)
        if proc.returncode not in (0, 1) and not result.failed and not result.errors:
            result.errors = 1
    except subprocess.TimeoutExpired:
        result.output = f"Timed out after {max_runtime_seconds}s"
        result.errors = 1
    except Exception as e:
        result.output = str(e)
        result.errors = 1

    return result


def run_targeted_tests(
    changed_file: str,
    ledger: Ledger,
    tests_base_dir: str | Path,
    previous_results: dict[str, TestRunResult] | None = None,
    max_runtime_seconds: int = 30,
) -> list[TestRunResult]:
    """Run tests for all features touching changed_file.

    Returns per-feature test results. Compares against previous_results
    to identify newly-failing tests.
    """
    affected = features_touching_file(ledger, changed_file)
    results: list[TestRunResult] = []

    for feature in affected:
        test_dir = feature_tests_dir(feature, tests_base_dir)
        if not test_dir.exists():
            continue

        result = _run_pytest_for_feature(feature, test_dir, max_runtime_seconds)

        # Identify newly-failing tests vs previous run
        if previous_results and feature.id in previous_results:
            prev = previous_results[feature.id]
            if prev.ok and not result.ok:
                # Extract failing test names from output
                result.newly_failing = _parse_failing_tests(result.output)
        elif not result.ok:
            result.newly_failing = _parse_failing_tests(result.output)

        results.append(result)

    return results


def _run_pytest_for_feature(
    feature: Feature,
    test_dir: Path,
    max_runtime_seconds: int,
) -> TestRunResult:
    """Run pytest on a single feature's test directory."""
    result = TestRunResult(feature_id=feature.id, feature_name=feature.name)

    try:
        proc = subprocess.run(
            [
                sys.executable, "-m", "pytest",
                str(test_dir),
                "-v", "--tb=short", "-q",
            ],
            capture_output=True,
            text=True,
            timeout=max_runtime_seconds + 5,
        )
        result.output = proc.stdout + proc.stderr
        _parse_pytest_summary(result)
        if proc.returncode not in (0, 1) and not result.failed and not result.errors:
            result.errors = 1
    except subprocess.TimeoutExpired:
        result.output = f"Timed out after {max_runtime_seconds}s"
        result.errors = 1
    except Exception as e:
        result.output = str(e)
        result.errors = 1

    return result


def _parse_pytest_summary(result: TestRunResult) -> None:
    """Parse pytest's short summary line into counts."""
    import re
    for line in reversed(result.output.splitlines()):
        # e.g. "3 passed, 1 failed, 2 error in 0.12s"
        m = re.search(r"(\d+) passed", line)
        if m:
            result.passed = int(m.group(1))
        m = re.search(r"(\d+) failed", line)
        if m:
            result.failed = int(m.group(1))
        m = re.search(r"(\d+) error", line)
        if m:
            result.errors = int(m.group(1))
        m = re.search(r"(\d+) skipped", line)
        if m:
            result.skipped = int(m.group(1))
        if result.passed or result.failed or result.errors or result.skipped:
            break


def _parse_failing_tests(output: str) -> list[str]:
    """Extract FAILED test names from pytest output."""
    import re
    failing = []
    for line in output.splitlines():
        m = re.match(r"FAILED (.+?) -", line)
        if m:
            failing.append(m.group(1).strip())
    return failing
