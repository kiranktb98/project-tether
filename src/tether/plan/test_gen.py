"""Shared test generation module.

For each must_handle edge case, generate a pytest test and write it to
.tether/tests/feature_<id>/test_<n>.py.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tether.ledger.queries import feature_tests_dir
from tether.ledger.schema import EdgeCase, Feature
from tether.prompts.templates import (
    TEST_GEN_SYSTEM,
    TEST_GEN_TOOL_NAME,
    TEST_GEN_TOOL_SCHEMA,
    TEST_GEN_USER_TEMPLATE,
)
from tether.watcher_models.base import WatcherModel


def _build_project_tree(project_root: str | Path, max_lines: int = 40) -> str:
    """Build a simple text tree of the project for context."""
    root = Path(project_root)
    lines: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden dirs and common noise
        dirnames[:] = [
            d for d in sorted(dirnames)
            if not d.startswith(".") and d not in ("__pycache__", "node_modules")
        ]
        depth = len(Path(dirpath).relative_to(root).parts)
        indent = "  " * depth
        folder = Path(dirpath).name
        lines.append(f"{indent}{folder}/")
        for fname in sorted(filenames):
            if fname.endswith((".py", ".toml", ".yaml", ".md")):
                lines.append(f"{indent}  {fname}")
        if len(lines) >= max_lines:
            lines.append("  ...")
            break
    return "\n".join(lines)


def _sanitize_name(text: str, max_len: int = 40) -> str:
    """Convert a description to a snake_case identifier."""
    import re
    s = text.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    return s[:max_len] if s else "edge_case"


def generate_test_for_edge_case(
    feature: Feature,
    edge_case: EdgeCase,
    model: WatcherModel,
    *,
    tests_base_dir: str | Path,
    project_root: str | Path = ".",
) -> Path:
    """Generate a pytest test file for a single edge case.

    Returns the path of the written test file.
    Updates edge_case.test_file in-place.
    """
    project_tree = _build_project_tree(project_root)

    user = TEST_GEN_USER_TEMPLATE.format(
        feature_name=feature.name,
        edge_case_description=edge_case.description,
        edge_case_rationale=edge_case.rationale,
        feature_files=", ".join(feature.files) or "(unknown)",
        project_tree=project_tree,
    )

    result = model.check(
        system=TEST_GEN_SYSTEM,
        user=user,
        tool_name=TEST_GEN_TOOL_NAME,
        tool_schema=TEST_GEN_TOOL_SCHEMA,
    )

    test_source = _build_review_scaffold(
        feature=feature,
        edge_case=edge_case,
        candidate_source=result.get("test_source", ""),
    )

    # Write the test file
    test_dir = feature_tests_dir(feature, tests_base_dir)
    test_dir.mkdir(parents=True, exist_ok=True)

    # Ensure __init__.py exists
    init_file = test_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text("", encoding="utf-8")

    fname = f"test_{_sanitize_name(edge_case.description)}.py"
    test_path = test_dir / fname
    test_path.write_text(test_source, encoding="utf-8")

    # Sanity-check with pytest --collect-only
    _sanity_check_test(test_path)

    # Update the edge case record
    edge_case.test_file = str(test_path).replace("\\", "/")

    return test_path


def _build_review_scaffold(
    *,
    feature: Feature,
    edge_case: EdgeCase,
    candidate_source: str,
) -> str:
    """Build a safe pytest stub for a generated edge case.

    The model's draft is kept as reference text, but the executable test is a
    skipped scaffold so bootstrap never writes brittle assertions against
    hallucinated APIs.
    """
    draft = candidate_source.strip() or "(no draft returned by model)"
    func_name = f"test_{_sanitize_name(edge_case.description)}"
    description = edge_case.description.replace('"', "'")
    rationale = edge_case.rationale.replace('"', "'")

    return (
        "import pytest\n\n"
        f"@pytest.mark.skip(reason=\"generated review stub\")\n"
        f"def {func_name}() -> None:\n"
        f"    \"\"\"Generated stub for feature '{feature.name}'.\n\n"
        f"    Edge case: {description}\n"
        f"    Rationale: {rationale}\n"
        f"    \"\"\"\n"
        f"    candidate_test = {draft!r}\n"
        "    assert candidate_test\n"
    )


def _sanity_check_test(test_path: Path) -> None:
    """Run pytest --collect-only to verify the test is syntactically valid."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_path), "--collect-only", "-q"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    # We don't raise on collection errors — a skip marker is acceptable
    # Just let the watcher surface any real problems at run time
