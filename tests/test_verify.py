"""Regression tests for verify test discovery."""

from __future__ import annotations

from pathlib import Path

from tether.ledger.queries import feature_has_generated_tests
from tether.ledger.schema import EdgeCase, EdgeCaseFrequency, Feature
from tether.ledger.schema import FeatureStatus, Ledger
from tether.ledger.store import load_ledger, save_ledger
from tether.verify.verifier import run_verify


def test_feature_has_generated_tests_uses_edge_case_links(tmp_path) -> None:
    feature = Feature(
        id="f1",
        name="Feature one",
        edge_cases=[],
    )
    feature.edge_cases.append(EdgeCase(
        id="e1",
        description="x",
        frequency=EdgeCaseFrequency.high,
        must_handle=True,
        test_file=".tether/tests/feature_f1/test_x.py",
    ))

    assert feature_has_generated_tests(feature, tmp_path) is True


def test_feature_has_generated_tests_falls_back_to_disk(tmp_path) -> None:
    feature = Feature(id="f7", name="Feature seven")
    test_dir = tmp_path / "feature_f7"
    test_dir.mkdir(parents=True)
    (test_dir / "test_generated.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    assert feature_has_generated_tests(feature, tmp_path) is True


def test_verify_blocks_promotion_when_confident_must_handle_test_is_skipped(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    tether_dir = tmp_path / ".tether"
    (tether_dir / "tests" / "feature_f1").mkdir(parents=True)
    (tether_dir / "ledger.history").mkdir(parents=True)
    (tether_dir / "reports").mkdir(parents=True)

    test_file = tether_dir / "tests" / "feature_f1" / "test_blocker.py"
    test_file.write_text(
        "import pytest\n\n"
        "@pytest.mark.skip(reason='not implemented yet')\n"
        "def test_blocker() -> None:\n"
        "    assert True\n",
        encoding="utf-8",
    )

    ledger = Ledger(features=[
        Feature(
            id="f1",
            name="Feature one",
            status=FeatureStatus.building,
            edge_cases=[
                EdgeCase(
                    id="e1",
                    description="Must not regress",
                    frequency=EdgeCaseFrequency.high,
                    rationale="Common and important",
                    must_handle=True,
                    confidence=0.95,
                    test_file=".tether/tests/feature_f1/test_blocker.py",
                )
            ],
        )
    ])
    save_ledger(ledger, ".tether/ledger.yaml", history_dir=".tether/ledger.history", snapshot=False)

    run_verify(config_path=".tether/config.yaml")

    loaded = load_ledger(".tether/ledger.yaml")
    feature = loaded.get_feature("f1")
    assert feature is not None
    assert feature.status == FeatureStatus.building

    report_files = list((tether_dir / "reports").glob("*.md"))
    assert report_files
    report = report_files[0].read_text(encoding="utf-8")
    assert "blocking session completion" in report
