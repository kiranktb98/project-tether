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
from pathlib import Path


class PersistentFileCache:
    """On-disk cache of file contents keyed by absolute path.

    Not thread-safe for the same key. The watcher only writes from the
    debounced handler so concurrent writes to the same path don't occur.
    """

    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._mem: dict[str, str] = {}

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
