"""Tests for the watcher's path-handling helper.

Previously, _should_watch and _handle_file_change called Path.relative_to
unconditionally. On Windows that raises ValueError when the file is on a
different drive or reached via a symlink that doesn't resolve under cwd —
which would crash the watcher thread. The helper now falls back to the
absolute path instead.
"""

from __future__ import annotations

from pathlib import Path

from tether.watch.runner import _rel_path_or_abs


def test_relative_path_when_under_cwd() -> None:
    rel = Path("src") / "foo.py"
    abs_path = Path.cwd() / rel
    assert _rel_path_or_abs(str(abs_path)) == "src/foo.py"


def test_absolute_fallback_when_outside_cwd(tmp_path: Path) -> None:
    outside = tmp_path / "somewhere_else.py"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("# outside")
    result = _rel_path_or_abs(str(outside))
    # Must not raise. Result should contain a forward-slash path.
    assert "somewhere_else.py" in result
    assert "\\" not in result
