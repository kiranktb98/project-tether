"""Regression tests for impact-analysis parsing."""

from __future__ import annotations

from tether.ledger.schema import Feature, Ledger
from tether.plan.impact import run_impact_analysis


class _FakeModel:
    def __init__(self, response: dict) -> None:
        self._response = response

    def check(self, **kwargs) -> dict:
        return self._response


def test_run_impact_analysis_ignores_non_dict_risks() -> None:
    ledger = Ledger(features=[
        Feature(id="f1", name="Env loading", files=["src/tether/env.py"]),
    ])
    model = _FakeModel({
        "risks": [
            "bad-shape",
            {"feature_id": "f1", "level": "medium", "reason": "Touches shared setup"},
        ],
        "overall_risk": "medium",
    })

    result = run_impact_analysis(
        file_path="src/tether/env.py",
        intent="improve env loading",
        ledger=ledger,
        model=model,
    )

    assert len(result.risks) == 1
    assert result.risks[0].feature_id == "f1"
    assert result.risks[0].level == "medium"
    assert result.overall_risk == "medium"
