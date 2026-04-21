"""Tests for PersistentFileCache.prune()."""

from __future__ import annotations

import os
import time
from pathlib import Path

from tether.state.file_cache import PersistentFileCache


def test_prune_removes_entries_older_than_max_age(tmp_path: Path) -> None:
    cache = PersistentFileCache(
        tmp_path / "cache",
        max_entries=1000,
        max_age_days=7,
    )
    cache.set("/abs/a.py", "A")
    cache.set("/abs/b.py", "B")

    # Backdate a.py by 10 days. Touching mtime via os.utime is the
    # portable way — no OS-specific stat struct.
    a_path = cache._key_path("/abs/a.py")
    ten_days_ago = time.time() - (10 * 86400)
    os.utime(a_path, (ten_days_ago, ten_days_ago))

    removed = cache.prune()

    assert removed == 1
    assert cache.get("/abs/a.py") == ""
    assert cache.get("/abs/b.py") == "B"


def test_prune_caps_entry_count(tmp_path: Path) -> None:
    """Older entries get pruned first when we're over the cap."""
    cache = PersistentFileCache(
        tmp_path / "cache",
        max_entries=2,
        max_age_days=365,
    )
    cache.set("/abs/oldest.py", "1")
    cache.set("/abs/middle.py", "2")
    cache.set("/abs/newest.py", "3")

    # Backdate so sorting is deterministic (mtime resolution on some
    # filesystems is only 1s, and all three sets may land in the same tick).
    now = time.time()
    os.utime(cache._key_path("/abs/oldest.py"), (now - 30, now - 30))
    os.utime(cache._key_path("/abs/middle.py"), (now - 20, now - 20))
    os.utime(cache._key_path("/abs/newest.py"), (now - 10, now - 10))

    removed = cache.prune()
    assert removed == 1
    assert cache.get("/abs/oldest.py") == ""
    assert cache.get("/abs/middle.py") == "2"
    assert cache.get("/abs/newest.py") == "3"


def test_prune_with_nothing_to_remove_is_noop(tmp_path: Path) -> None:
    cache = PersistentFileCache(tmp_path / "cache", max_entries=100, max_age_days=30)
    cache.set("/abs/a.py", "A")
    assert cache.prune() == 0
    assert cache.get("/abs/a.py") == "A"


def test_prune_on_empty_directory_is_safe(tmp_path: Path) -> None:
    cache = PersistentFileCache(tmp_path / "cache")
    assert cache.prune() == 0
