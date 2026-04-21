"""Tests that the invariant check handles JS/TS sources, not just Python."""

from __future__ import annotations

from pathlib import Path

from tether.watch.checks.invariants import (
    check_invariants,
    clear_snapshots,
    take_snapshot,
)


def test_js_signature_change_detected(tmp_path: Path) -> None:
    clear_snapshots()
    f = tmp_path / "m.js"
    f.write_text("export function add(a, b) { return a + b; }\n", encoding="utf-8")

    take_snapshot(f, tmp_path)

    f.write_text("export function add(a, b, c) { return a + b + c; }\n", encoding="utf-8")
    result = check_invariants(f, tmp_path)

    assert not result.ok
    kinds = {v.kind for v in result.violations}
    assert "signature_changed" in kinds
    assert any(v.symbol == "add" for v in result.violations)


def test_ts_symbol_removal_detected(tmp_path: Path) -> None:
    clear_snapshots()
    f = tmp_path / "s.ts"
    f.write_text(
        "export function keep(): void {}\nexport function drop(): void {}\n",
        encoding="utf-8",
    )
    take_snapshot(f, tmp_path)

    f.write_text("export function keep(): void {}\n", encoding="utf-8")
    result = check_invariants(f, tmp_path)

    assert not result.ok
    removed = [v for v in result.violations if v.kind == "symbol_removed"]
    assert any(v.symbol == "drop" for v in removed)


def test_js_class_method_signature_change_detected(tmp_path: Path) -> None:
    clear_snapshots()
    f = tmp_path / "c.js"
    f.write_text(
        "export class Calc { add(a, b) { return a + b; } }\n",
        encoding="utf-8",
    )
    take_snapshot(f, tmp_path)

    f.write_text(
        "export class Calc { add(a, b, c) { return a + b + c; } }\n",
        encoding="utf-8",
    )
    result = check_invariants(f, tmp_path)

    assert not result.ok
    assert any(
        v.kind == "signature_changed" and v.symbol == "Calc.add"
        for v in result.violations
    )
