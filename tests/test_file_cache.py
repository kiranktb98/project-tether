"""Tests for the persistent file cache used by the watcher."""

from __future__ import annotations

from pathlib import Path

from tether.state.file_cache import PersistentFileCache


def test_set_and_get_roundtrip(tmp_path: Path) -> None:
    cache = PersistentFileCache(tmp_path / "cache")
    cache.set("/abs/path/foo.py", "contents v1")
    assert cache.get("/abs/path/foo.py") == "contents v1"


def test_get_unknown_returns_default(tmp_path: Path) -> None:
    cache = PersistentFileCache(tmp_path / "cache")
    assert cache.get("/unknown") == ""
    assert cache.get("/unknown", default="fallback") == "fallback"


def test_persistence_across_instances(tmp_path: Path) -> None:
    """A fresh PersistentFileCache pointed at the same dir should see
    previously-persisted entries. This is the whole reason the cache exists:
    surviving `tether watch` restarts."""
    cache_dir = tmp_path / "cache"
    first = PersistentFileCache(cache_dir)
    first.set("/abs/foo.py", "first-run contents")

    second = PersistentFileCache(cache_dir)
    assert second.get("/abs/foo.py") == "first-run contents"


def test_overwrite_replaces_content(tmp_path: Path) -> None:
    cache = PersistentFileCache(tmp_path / "cache")
    cache.set("/abs/foo.py", "v1")
    cache.set("/abs/foo.py", "v2")
    assert cache.get("/abs/foo.py") == "v2"

    # Re-open to prove the new value was persisted, not just memoized.
    reopened = PersistentFileCache(tmp_path / "cache")
    assert reopened.get("/abs/foo.py") == "v2"


def test_delete_removes_entry(tmp_path: Path) -> None:
    cache = PersistentFileCache(tmp_path / "cache")
    cache.set("/abs/foo.py", "v1")
    cache.delete("/abs/foo.py")
    assert cache.get("/abs/foo.py") == ""

    reopened = PersistentFileCache(tmp_path / "cache")
    assert reopened.get("/abs/foo.py") == ""


def test_rename_carries_content(tmp_path: Path) -> None:
    cache = PersistentFileCache(tmp_path / "cache")
    cache.set("/abs/old.py", "orig")
    cache.rename("/abs/old.py", "/abs/new.py")
    assert cache.get("/abs/old.py") == ""
    assert cache.get("/abs/new.py") == "orig"


def test_key_collision_safety(tmp_path: Path) -> None:
    """Different paths must map to different cache files."""
    cache = PersistentFileCache(tmp_path / "cache")
    cache.set("/abs/a.py", "content-a")
    cache.set("/abs/b.py", "content-b")
    assert cache.get("/abs/a.py") == "content-a"
    assert cache.get("/abs/b.py") == "content-b"


def test_unicode_content_preserved(tmp_path: Path) -> None:
    cache = PersistentFileCache(tmp_path / "cache")
    cache.set("/abs/x.py", "héllo — ünicode ✓")
    reopened = PersistentFileCache(tmp_path / "cache")
    assert reopened.get("/abs/x.py") == "héllo — ünicode ✓"
