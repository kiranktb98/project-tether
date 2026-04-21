"""Persistent file-content cache for the watcher.

The watcher needs the *previous* contents of a file to compute a diff when
the file changes. An in-memory dict works within a single watch session,
but restarting `tether watch` loses all history — the next edit then looks
like a full-file rewrite and produces a useless diff.

This module persists the cache under `.tether/cache/files/` as plain text
files, keyed by a hash of the absolute path. On startup the watcher can
rebuild the in-memory dict from disk; on every update the entry for the
changed file is rewritten atomically.

Design notes:
- One file per cached entry. Avoids the "rewrite a 50 MB pickle on every
  keystroke" failure mode of a single-blob cache.
- Plain text, not pickle: cached contents are just the file's text, so
  pickle buys nothing and makes the cache opaque.
- Atomic write via temp file + os.replace so a crash mid-write leaves the
  previous contents intact rather than a half-written blob.
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

# Sensible defaults — a typical Python project has well under 1000 tracked
# files, and even with 2 MB per file the cache stays under 2 GB. A cache
# entry older than 30 days almost certainly belongs to a file that has been
# deleted or renamed to something the watcher didn't catch; pruning it
# keeps the directory tidy without risking useful state.
_DEFAULT_MAX_ENTRIES = 1000
_DEFAULT_MAX_AGE_DAYS = 30


class PersistentFileCache:
    """On-disk cache of file contents keyed by absolute path.

    Not thread-safe for the same key. The watcher only writes from the
    debounced handler so concurrent writes to the same path don't occur.
    """

    def __init__(
        self,
        cache_dir: Path,
        *,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
        max_age_days: int = _DEFAULT_MAX_AGE_DAYS,
    ) -> None:
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._mem: dict[str, str] = {}
        self._max_entries = max_entries
        self._max_age_seconds = max_age_days * 86400

    def _key_path(self, abs_path: str) -> Path:
        # sha1 is fine here — not security-sensitive, just a filename hash.
        digest = hashlib.sha1(abs_path.encode("utf-8")).hexdigest()
        return self._dir / f"{digest}.txt"

    def get(self, abs_path: str, default: str = "") -> str:
        if abs_path in self._mem:
            return self._mem[abs_path]
        kp = self._key_path(abs_path)
        if kp.exists():
            try:
                content = kp.read_text(encoding="utf-8", errors="replace")
                self._mem[abs_path] = content
                return content
            except OSError:
                return default
        return default

    def set(self, abs_path: str, content: str) -> None:
        self._mem[abs_path] = content
        kp = self._key_path(abs_path)
        tmp = kp.with_suffix(".tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            os.replace(tmp, kp)
        except OSError:
            # If we can't persist, keep the in-memory value so the current
            # session still gets correct diffs — just no cross-restart
            # continuity for this one file.
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def delete(self, abs_path: str) -> None:
        self._mem.pop(abs_path, None)
        kp = self._key_path(abs_path)
        if kp.exists():
            try:
                kp.unlink()
            except OSError:
                pass

    def rename(self, old_abs_path: str, new_abs_path: str) -> None:
        content = self.get(old_abs_path)
        self.delete(old_abs_path)
        if content:
            self.set(new_abs_path, content)

    def prune(self) -> int:
        """Drop stale entries: anything older than max_age_days, and the
        oldest entries past max_entries. Returns the number of files
        removed. Safe to call on startup — the in-memory state is lazily
        repopulated on next get().

        Pruning only touches the on-disk files. The in-memory dict is
        cleared for pruned keys so a subsequent get() correctly sees the
        cache miss rather than returning stale content.
        """
        try:
            entries = [
                (p, p.stat().st_mtime)
                for p in self._dir.glob("*.txt")
            ]
        except OSError:
            return 0

        now = time.time()
        to_remove: list[Path] = []

        for path, mtime in entries:
            if now - mtime > self._max_age_seconds:
                to_remove.append(path)

        # After age-based pruning, if we're still over the entry cap,
        # remove the oldest survivors until we're at cap. Newest entries
        # are most likely to match an active file.
        survivors = [(p, m) for p, m in entries if p not in to_remove]
        if len(survivors) > self._max_entries:
            survivors.sort(key=lambda pm: pm[1])  # oldest first
            overflow = len(survivors) - self._max_entries
            to_remove.extend(p for p, _ in survivors[:overflow])

        removed = 0
        for path in to_remove:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass

        if removed:
            # Invalidate in-memory entries whose backing file is gone.
            # Cheaper to drop the whole dict than recompute each hash.
            self._mem.clear()

        return removed
