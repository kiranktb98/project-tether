"""Tests for the intent-check diff pipeline."""

from __future__ import annotations

from tether.watch.checks.intent import (
    IntentResult,
    _aggregate_chunk_results,
    _split_diff_by_boundary,
    compute_diff,
)


def test_compute_diff_empty_old_content_returns_empty() -> None:
    """Brand-new files (no prior cache) should produce no diff. An all-new
    dump would blow up Haiku's context and always be noise."""
    assert compute_diff("", "new\ncontents\n", "foo.py") == ""


def test_compute_diff_unchanged_returns_empty() -> None:
    assert compute_diff("same", "same", "foo.py") == ""


def test_compute_diff_produces_unified_diff() -> None:
    out = compute_diff("a\nb\n", "a\nc\n", "foo.py")
    assert "a/foo.py" in out
    assert "b/foo.py" in out
    assert "-b" in out
    assert "+c" in out


def test_split_small_diff_returns_single_chunk() -> None:
    diff = "\n".join(f"+ line {i}" for i in range(10))
    chunks = _split_diff_by_boundary(diff, max_lines=300)
    assert len(chunks) == 1


def test_split_prefers_function_boundary() -> None:
    """When the buffer crosses max_lines, the next function boundary is
    the preferred split point; the boundary line begins the next chunk
    so Haiku sees the function header alongside its body."""
    lines = []
    # 200 lines of + body, then a def at 201, then 100 more lines, then
    # another def, then 50 more lines.
    for i in range(200):
        lines.append(f"+    line_{i}")
    lines.append("+def second_function():")
    for i in range(100):
        lines.append(f"+    body_{i}")
    lines.append("+def third_function():")
    for i in range(50):
        lines.append(f"+    tail_{i}")
    diff = "\n".join(lines) + "\n"

    chunks = _split_diff_by_boundary(diff, max_lines=150)
    # Should split: at/after second_function (past soft limit of 150),
    # and again at third_function.
    assert len(chunks) >= 2
    assert "def second_function" in chunks[1]


def test_split_hard_caps_when_no_boundary() -> None:
    """A huge diff with zero function/class boundaries (e.g. a YAML blob)
    must still get chunked — otherwise a 10 000-line diff would ship to
    Haiku as one payload."""
    diff = "\n".join(f"+ data_{i}" for i in range(1000)) + "\n"
    chunks = _split_diff_by_boundary(diff, max_lines=100)
    assert len(chunks) > 1, "expected hard-cap to force chunking"
    # Each chunk must be under the hard cap (max_lines * 1.5)
    for chunk in chunks:
        assert chunk.count("\n") <= int(100 * 1.5) + 1


def test_split_always_returns_at_least_one_chunk() -> None:
    # Empty input should still return [""] per the implementation contract
    # so callers don't need a nullability check.
    chunks = _split_diff_by_boundary("", max_lines=300)
    assert chunks == [""]


def test_aggregate_picks_highest_severity() -> None:
    results = [
        IntentResult(verdict="aligned", reason="a"),
        IntentResult(verdict="drifted", reason="b"),
        IntentResult(verdict="neutral", reason="c"),
    ]
    agg = _aggregate_chunk_results(results)
    assert agg.verdict == "drifted"
    assert "a" in agg.reason and "b" in agg.reason and "c" in agg.reason
    assert len(agg.chunk_verdicts) == 3


def test_aggregate_deduplicates_feature_ids() -> None:
    results = [
        IntentResult(verdict="aligned", reason="", affected_feature_ids=["f1", "f2"]),
        IntentResult(verdict="neutral", reason="", affected_feature_ids=["f2", "f3"]),
    ]
    agg = _aggregate_chunk_results(results)
    assert set(agg.affected_feature_ids) == {"f1", "f2", "f3"}


def test_aggregate_looks_intentional_beats_neutral() -> None:
    results = [
        IntentResult(verdict="aligned", reason=""),
        IntentResult(verdict="looks_intentional", reason=""),
        IntentResult(verdict="neutral", reason=""),
    ]
    agg = _aggregate_chunk_results(results)
    assert agg.verdict == "looks_intentional"
