"""Watch runner — long-running file watcher."""

from __future__ import annotations

import fnmatch
import os
import signal
import sys
import threading
from pathlib import Path

from rich.console import Console
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from tether.config import load_config
from tether.ledger.store import load_ledger, save_ledger
from tether.state.file_cache import PersistentFileCache
from tether.state.store import EventLog, ensure_tether_dir
from tether.state.manifest import SessionManifest
from tether.watcher_models import create_watcher_model
from tether.watcher_models.anthropic_haiku import BudgetExceededError
from tether.watcher_models.base import WatcherModel
from tether.watch.debounce import Debouncer
from tether.watch.checks.targeted_tests import TestRunResult, run_targeted_tests
from tether.watch.checks.intent import IntentResult, compute_diff, run_intent_check
from tether.watch.checks.invariants import InvariantResult, check_invariants, take_snapshot
from tether.whisper.notes_writer import DriftNote, clear_drift_notes, compute_severity, write_drift_notes

console = Console()

# Previous test results per feature (for newly_failing detection)
_prev_test_results: dict[str, TestRunResult] = {}


class TetherEventHandler(FileSystemEventHandler):
    def __init__(
        self,
        tether_dir: Path,
        config,
        model: WatcherModel,
        event_log: EventLog,
        manifest: SessionManifest,
        debouncer: Debouncer,
        ledger_holder: list,   # mutable reference [ledger]
        file_cache: PersistentFileCache,
        verbose: bool = False,
    ) -> None:
        super().__init__()
        self._tether_dir = tether_dir
        self._config = config
        self._model = model
        self._event_log = event_log
        self._manifest = manifest
        self._debouncer = debouncer
        self._ledger_holder = ledger_holder
        self._file_cache = file_cache
        self._verbose = verbose
        self._ledger_path = str((Path.cwd() / config.ledger.path).resolve())

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        src = str(event.src_path)

        # Reload ledger if it changed
        if str(Path(src).resolve()) == self._ledger_path:
            self._reload_ledger()
            return

        if not self._should_watch(src):
            return

        self._debouncer.trigger(src, self._handle_file_change)

    on_created = on_modified

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        src = str(event.src_path)
        # Drop the cache entry so a future re-creation produces a clean diff
        # against an empty baseline rather than stale contents.
        self._file_cache.delete(src)

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        src = str(event.src_path)
        dest = str(getattr(event, "dest_path", "") or "")
        if not dest:
            self._file_cache.delete(src)
            return
        # Carry forward the cached contents under the new path so the next
        # edit produces a diff against the pre-rename version, not empty.
        self._file_cache.rename(src, dest)
        if self._should_watch(dest):
            self._debouncer.trigger(dest, self._handle_file_change)

    def _should_watch(self, file_path: str) -> bool:
        """Return True if this file should trigger checks."""
        # Extension whitelist
        if not any(file_path.endswith(ext) for ext in (".py", ".md", ".yaml", ".toml", ".json")):
            return False
        # Ignore globs
        rel = str(Path(file_path).relative_to(Path.cwd())).replace("\\", "/")
        for pattern in self._config.watch.ignore_globs:
            if fnmatch.fnmatch(rel, pattern):
                return False
        return True

    def _reload_ledger(self) -> None:
        try:
            new_ledger = load_ledger(self._config.ledger.path)
            self._ledger_holder[0] = new_ledger
            console.print(
                f"[dim]Ledger reloaded (v{new_ledger.version}, "
                f"{len(new_ledger.features)} features)[/dim]"
            )
        except Exception as e:
            console.print(f"[yellow]Ledger reload failed:[/yellow] {e}")

    def _handle_file_change(self, file_path: str) -> None:
        """Run all checks for a changed file."""
        ledger = self._ledger_holder[0]
        rel_path = str(Path(file_path).relative_to(Path.cwd())).replace("\\", "/")

        console.print(f"\n[dim]File changed:[/dim] [cyan]{rel_path}[/cyan]")
        self._manifest.record_file_change()

        try:
            # Compute diff from cache
            try:
                old_content = self._file_cache.get(file_path, "")
                new_content = Path(file_path).read_text(encoding="utf-8", errors="replace")
                self._file_cache.set(file_path, new_content)
                diff = compute_diff(old_content, new_content, rel_path)
            except OSError:
                diff = ""
                new_content = ""

            # Step 1: Targeted tests
            test_results = run_targeted_tests(
                rel_path,
                ledger,
                self._config.ledger.tests_dir,
                previous_results=_prev_test_results,
                max_runtime_seconds=self._config.verify.max_test_runtime_seconds,
            )
            for r in test_results:
                _prev_test_results[r.feature_id] = r

            # Step 2: Intent check (only for .py files with a non-trivial diff)
            intent_result: IntentResult | None = None
            if file_path.endswith(".py") and diff.strip():
                failing_names = [n for r in test_results for n in r.newly_failing]
                try:
                    intent_result = run_intent_check(
                        rel_path, diff, ledger, self._model,
                        failing_test_names=failing_names,
                    )
                except BudgetExceededError as e:
                    console.print(f"[red]Budget exceeded:[/red] {e}")
                    return
                except Exception as e:
                    console.print(f"[yellow]Intent check skipped:[/yellow] {e}")

            # Step 3: Invariant check
            invariant_result: InvariantResult | None = None
            if file_path.endswith(".py"):
                invariant_result = check_invariants(file_path)

            # Step 4: Verdict aggregation
            severity = compute_severity(intent_result, test_results, invariant_result)
            self._manifest.record_check()
            self._manifest.record_drift(severity)

            # Log the check
            self._event_log.log_check(
                file_path=rel_path,
                check_type="watch",
                verdict=severity,
                session_id=self._manifest.session_id,
            )

            if severity == "none":
                if self._verbose:
                    console.print(f"  [green]OK[/green] All checks pass.")
                return

            # Step 5: Write drift notes
            note = DriftNote(
                severity=severity,
                file_path=rel_path,
                intent_result=intent_result,
                test_results=test_results,
                invariant_result=invariant_result,
            )
            write_drift_notes(
                note,
                self._config.worker.drift_notes_file,
                claude_md_file=self._config.worker.notes_file,
            )

            # Console output per severity
            _print_severity_summary(severity, note)

        except Exception as e:
            console.print(f"[red]Watch check error:[/red] {e}")
            if self._verbose:
                import traceback
                traceback.print_exc()


def _print_severity_summary(severity: str, note: DriftNote) -> None:
    color = {
        "soft": "yellow",
        "intentional": "yellow",
        "hard": "red",
        "critical": "bold red",
    }.get(severity, "white")

    console.print(f"  [{color}]{severity.upper()}[/{color}]", end=" ")

    if note.intent_result and note.intent_result.verdict not in ("aligned", "neutral"):
        console.print(f"intent={note.intent_result.verdict}", end=" ")

    failing = [r for r in note.test_results if not r.ok]
    if failing:
        names = ", ".join(r.feature_name for r in failing[:3])
        console.print(f"tests failed: {names}", end="")

    if note.invariant_result and not note.invariant_result.ok:
        console.print(f" ({len(note.invariant_result.violations)} invariant violations)", end="")

    console.print(f"\n  See [cyan].tether/DRIFT.md[/cyan]")


def run_watch(config_path: str | None = None, verbose: bool = False) -> None:
    """Start the long-running file watcher."""
    cfg = load_config(config_path)
    tether_dir = ensure_tether_dir(".tether")

    from tether.env import check_provider_ready
    err = check_provider_ready(cfg.watcher.provider)
    if err:
        console.print(f"[red]Error:[/red] {err}")
        return

    ledger = load_ledger(cfg.ledger.path)
    if not ledger.features:
        console.print(
            "[yellow]Warning:[/yellow] Ledger has no features. "
            "Run [cyan]tether bootstrap[/cyan] first."
        )

    event_log = EventLog(tether_dir)
    manifest = SessionManifest(tether_dir)
    manifest.ledger_version_start = ledger.version
    manifest.save()

    model = create_watcher_model(cfg, event_log=event_log, session_id=manifest.session_id)

    file_cache = PersistentFileCache(tether_dir / "cache" / "files")

    # Snapshot all feature files at startup. The persistent cache survives
    # across restarts, so only overwrite the cached content when the file
    # on disk is genuinely newer; otherwise keep the prior snapshot as the
    # diff baseline for the next edit.
    project_root = Path(cfg.project.root).resolve()
    for feature in ledger.features:
        for fpath in feature.files:
            abs_path = project_root / fpath
            if abs_path.exists():
                take_snapshot(abs_path, project_root)
                key = str(abs_path)
                if not file_cache.get(key):
                    try:
                        file_cache.set(
                            key,
                            abs_path.read_text(encoding="utf-8", errors="replace"),
                        )
                    except OSError:
                        pass

    debouncer = Debouncer(delay_ms=cfg.watch.debounce_ms)
    ledger_holder = [ledger]

    handler = TetherEventHandler(
        tether_dir=tether_dir,
        config=cfg,
        model=model,
        event_log=event_log,
        manifest=manifest,
        debouncer=debouncer,
        ledger_holder=ledger_holder,
        file_cache=file_cache,
        verbose=verbose,
    )

    observer = Observer()
    watch_root = str(project_root)
    observer.schedule(handler, watch_root, recursive=True)
    observer.start()

    console.print(
        f"\n[bold cyan]tether watch[/bold cyan] — "
        f"monitoring [cyan]{watch_root}[/cyan]\n"
        f"  Ledger: v{ledger.version} · {len(ledger.features)} features\n"
        f"  Budget: ${cfg.watcher.budget_usd_per_session:.2f}/session\n"
        f"  Press Ctrl+C to stop.\n"
    )

    def _shutdown(signum=None, frame=None):
        console.print("\n[dim]Stopping watcher...[/dim]")
        debouncer.cancel_all()
        observer.stop()
        manifest.ledger_version_end = ledger_holder[0].version
        manifest.add_cost(model.session_cost_usd)
        manifest.save()
        console.print(
            f"Session ended. Cost: [dim]${model.session_cost_usd:.4f}[/dim]  "
            f"Checks: [dim]{manifest.checks_run}[/dim]"
        )

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)

    try:
        observer.join()
    except KeyboardInterrupt:
        _shutdown()
