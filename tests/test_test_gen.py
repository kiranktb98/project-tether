"""Tests for generated pytest stubs."""

from tether.ledger.schema import EdgeCase, EdgeCaseFrequency, Feature
from tether.plan.test_gen import _build_review_scaffold


def test_build_review_scaffold_always_marks_generated_test_skipped() -> None:
    feature = Feature(id="f1", name="Env loading", files=["src/tether/env.py"])
    edge_case = EdgeCase(
        id="e1",
        description="missing env file",
        frequency=EdgeCaseFrequency.medium,
        rationale="common setup issue",
        must_handle=True,
    )

    source = _build_review_scaffold(
        feature=feature,
        edge_case=edge_case,
        candidate_source="from tether.env import load_env\n\ndef test_real():\n    assert load_env()\n",
    )

    assert '@pytest.mark.skip(reason="generated review stub")' in source
    assert "candidate_test" in source
    assert "from tether.env import load_env" in source


def test_build_review_scaffold_uses_python_safe_string_repr() -> None:
    feature = Feature(id="f1", name="Plan notes", files=["src/tether/plan/notes.py"])
    edge_case = EdgeCase(
        id="e2",
        description="windows path with unicode escape",
        frequency=EdgeCaseFrequency.low,
        rationale="backslashes can break triple-quoted literals",
        must_handle=False,
    )

    source = _build_review_scaffold(
        feature=feature,
        edge_case=edge_case,
        candidate_source="path = 'C:\\Users\\name\\notes'\n",
    )

    assert "candidate_test = " in source
    assert "C:\\\\Users\\\\name\\\\notes" in source
