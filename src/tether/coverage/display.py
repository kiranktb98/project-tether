"""tether coverage — bell-curve view of edge case coverage across all features.

Shows the frequency distribution of edge cases (the "bell curve") for each
feature, alongside how much of the must-handle risk surface has test coverage.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from tether.config import load_config
from tether.ledger.schema import Feature, Ledger, EdgeCaseFrequency
from tether.ledger.store import load_ledger

console = Console()

# ── bar rendering ────────────────────────────────────────────────────────────

_FULL  = "█"
_EMPTY = "░"
_BAR_WIDTH = 8   # chars per frequency bucket bar


def _bar(count: int, max_count: int, width: int = _BAR_WIDTH) -> str:
    if max_count == 0:
        return _EMPTY * width
    filled = round(width * count / max_count)
    return _FULL * filled + _EMPTY * (width - filled)


# ── per-feature stats ─────────────────────────────────────────────────────────

@dataclass
class FeatureCoverage:
    feature: Feature
    counts: dict[str, int]       # frequency label → edge case count
    must_handle_total: int
    must_handle_tested: int

    @property
    def coverage_pct(self) -> float:
        if self.must_handle_total == 0:
            return 100.0
        return 100.0 * self.must_handle_tested / self.must_handle_total

    @property
    def total_edge_cases(self) -> int:
        return sum(self.counts.values())


def _compute_feature_coverage(feature: Feature) -> FeatureCoverage:
    counts: dict[str, int] = {
        EdgeCaseFrequency.high.value:       0,
        EdgeCaseFrequency.medium.value:     0,
        EdgeCaseFrequency.low.value:        0,
        EdgeCaseFrequency.negligible.value: 0,
    }
    must_handle_total = 0
    must_handle_tested = 0

    for ec in feature.edge_cases:
        freq = ec.frequency.value if hasattr(ec.frequency, "value") else str(ec.frequency)
        if freq in counts:
            counts[freq] += 1
        if ec.must_handle:
            must_handle_total += 1
            if ec.test_file and Path(ec.test_file).exists():
                must_handle_tested += 1

    return FeatureCoverage(
        feature=feature,
        counts=counts,
        must_handle_total=must_handle_total,
        must_handle_tested=must_handle_tested,
    )


# ── overall stats ─────────────────────────────────────────────────────────────

@dataclass
class OverallCoverage:
    total_features: int
    features_with_edge_cases: int
    total_edge_cases: int
    must_handle_total: int
    must_handle_tested: int
    freq_counts: dict[str, int]

    @property
    def overall_pct(self) -> float:
        if self.must_handle_total == 0:
            return 100.0
        return 100.0 * self.must_handle_tested / self.must_handle_total


def _compute_overall(feature_coverages: list[FeatureCoverage]) -> OverallCoverage:
    freq_counts: dict[str, int] = {
        EdgeCaseFrequency.high.value:       0,
        EdgeCaseFrequency.medium.value:     0,
        EdgeCaseFrequency.low.value:        0,
        EdgeCaseFrequency.negligible.value: 0,
    }
    total_ec = 0
    mh_total = 0
    mh_tested = 0
    features_with_ec = 0

    for fc in feature_coverages:
        if fc.total_edge_cases > 0:
            features_with_ec += 1
        for freq, cnt in fc.counts.items():
            freq_counts[freq] += cnt
        total_ec += fc.total_edge_cases
        mh_total += fc.must_handle_total
        mh_tested += fc.must_handle_tested

    return OverallCoverage(
        total_features=len(feature_coverages),
        features_with_edge_cases=features_with_ec,
        total_edge_cases=total_ec,
        must_handle_total=mh_total,
        must_handle_tested=mh_tested,
        freq_counts=freq_counts,
    )


# ── rendering helpers ─────────────────────────────────────────────────────────

def _coverage_color(pct: float) -> str:
    if pct >= 80:
        return "green"
    if pct >= 50:
        return "yellow"
    return "red"


def _freq_bar_cell(count: int, max_count: int) -> Text:
    t = Text()
    if count == 0:
        t.append("  —  ", style="dim")
    else:
        t.append(str(count).rjust(2) + " ", style="bold")
        t.append(_bar(count, max_count), style="cyan")
    return t


def _overall_bar(pct: float, width: int = 30) -> Text:
    filled = round(width * pct / 100)
    color = _coverage_color(pct)
    t = Text()
    t.append(_FULL * filled, style=color)
    t.append(_EMPTY * (width - filled), style="dim")
    t.append(f"  {pct:.0f}%", style=f"bold {color}")
    return t


# ── main display ──────────────────────────────────────────────────────────────

def show_coverage(config_path: str | None = None) -> None:
    """Print the bell-curve coverage view for all features."""
    cfg = load_config(config_path)
    ledger = load_ledger(cfg.ledger.path)

    if not ledger.features:
        console.print(
            "[yellow]Ledger is empty.[/yellow] "
            "Run [cyan]tether bootstrap[/cyan] first."
        )
        return

    feature_coverages = [_compute_feature_coverage(f) for f in ledger.features]
    overall = _compute_overall(feature_coverages)

    _render_header(overall, ledger)
    _render_bell_curve(overall)
    _render_feature_table(feature_coverages, overall)
    _render_legend()


def _render_header(overall: OverallCoverage, ledger: Ledger) -> None:
    pct = overall.overall_pct
    color = _coverage_color(pct)

    title = (
        f"[bold cyan]tether coverage[/bold cyan]  "
        f"[dim]v{ledger.version}[/dim]  "
        f"[white]{overall.total_features} features · "
        f"{overall.total_edge_cases} edge cases[/white]"
    )

    body = Text()
    body.append("  Must-handle coverage: ", style="dim")
    body.append(_overall_bar(pct))
    body.append(
        f"  ({overall.must_handle_tested}/{overall.must_handle_total} tested)",
        style="dim",
    )

    console.print(Panel(body, title=title, border_style="cyan", padding=(0, 1)))


def _render_bell_curve(overall: OverallCoverage) -> None:
    """Render the aggregate frequency distribution — the bell curve."""
    console.print("\n[bold]Frequency distribution (all features combined)[/bold]")
    console.print("[dim]This is the shape of your edge-case risk surface.[/dim]\n")

    max_count = max(overall.freq_counts.values()) or 1
    bar_max_width = 40

    labels = [
        (EdgeCaseFrequency.high.value,       "HIGH      ", "green"),
        (EdgeCaseFrequency.medium.value,      "MEDIUM    ", "yellow"),
        (EdgeCaseFrequency.low.value,         "LOW       ", "orange3"),
        (EdgeCaseFrequency.negligible.value,  "NEGLIGIBLE", "dim"),
    ]

    for freq, label, color in labels:
        count = overall.freq_counts.get(freq, 0)
        filled = round(bar_max_width * count / max_count) if max_count else 0
        bar = _FULL * filled + _EMPTY * (bar_max_width - filled)

        t = Text()
        t.append(f"  {label}  ", style=f"bold {color}")
        t.append(bar, style=color)
        t.append(f"  {count:3d} edge cases", style="dim")

        # Annotate the must-handle boundary
        if freq in (EdgeCaseFrequency.high.value, EdgeCaseFrequency.medium.value):
            t.append("  ← must-handle zone", style="dim italic")

        console.print(t)

    console.print()


def _render_feature_table(
    feature_coverages: list[FeatureCoverage],
    overall: OverallCoverage,
) -> None:
    max_per_freq = {
        freq: max((fc.counts.get(freq, 0) for fc in feature_coverages), default=1)
        for freq in [
            EdgeCaseFrequency.high.value,
            EdgeCaseFrequency.medium.value,
            EdgeCaseFrequency.low.value,
            EdgeCaseFrequency.negligible.value,
        ]
    }

    table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold dim",
        pad_edge=False,
        expand=False,
    )
    table.add_column("ID",      style="cyan bold", width=4)
    table.add_column("Feature", width=38, no_wrap=True)
    table.add_column("HIGH",    justify="left", width=12)
    table.add_column("MEDIUM",  justify="left", width=12)
    table.add_column("LOW",     justify="left", width=12)
    table.add_column("NEG",     justify="left", width=8)
    table.add_column("Coverage", justify="right", width=14)

    for fc in feature_coverages:
        pct = fc.coverage_pct
        color = _coverage_color(pct)

        cov_text = Text()
        if fc.must_handle_total == 0:
            cov_text.append("  no tests", style="dim")
        else:
            cov_bar = _bar(fc.must_handle_tested, fc.must_handle_total, width=6)
            cov_text.append(cov_bar, style=color)
            cov_text.append(
                f"  {fc.must_handle_tested}/{fc.must_handle_total}",
                style=f"bold {color}",
            )

        table.add_row(
            fc.feature.id,
            fc.feature.name[:38],
            _freq_bar_cell(fc.counts.get(EdgeCaseFrequency.high.value, 0),
                           max_per_freq[EdgeCaseFrequency.high.value]),
            _freq_bar_cell(fc.counts.get(EdgeCaseFrequency.medium.value, 0),
                           max_per_freq[EdgeCaseFrequency.medium.value]),
            _freq_bar_cell(fc.counts.get(EdgeCaseFrequency.low.value, 0),
                           max_per_freq[EdgeCaseFrequency.low.value]),
            _freq_bar_cell(fc.counts.get(EdgeCaseFrequency.negligible.value, 0),
                           max_per_freq[EdgeCaseFrequency.negligible.value]),
            cov_text,
        )

    console.print(table)


def _render_legend() -> None:
    console.print(
        "[dim]Coverage = must-handle edge cases with a test stub / total must-handle edge cases[/dim]"
    )
    console.print(
        "[dim]Must-handle = frequency HIGH or MEDIUM, "
        "or LOW with catastrophic rationale (data loss / security / crash)[/dim]\n"
    )
