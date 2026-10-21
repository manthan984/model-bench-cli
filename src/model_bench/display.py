"""Rich terminal tables & KPI dashboard rendering for model-bench.

Responsibilities:
- Renders formatted terminal tables & KPI panels via ``rich``
- Each display function corresponds to a CLI subcommand
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


# ── Helpers ────────────────────────────────────────────────────────────


def _fmt_price(value: float | None) -> str:
    """Format a price value for display."""
    if value is None:
        return "—"
    return f"${value:,.4f}"


def _fmt_cost(value: float | None) -> str:
    """Format a cost value for display."""
    if value is None:
        return "—"
    return f"${value:,.2f}"


def _fmt_index(value: float | None) -> str:
    """Format a benchmark index value."""
    if value is None:
        return "—"
    return f"{value:.1f}"


def _fmt_int(value: int | None) -> str:
    """Format an integer with comma separators."""
    if value is None:
        return "—"
    return f"{value:,}"


def _truncate(text: str, max_len: int = 40) -> str:
    """Truncate text with ellipsis if too long."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


# ── Sync Summary ───────────────────────────────────────────────────────


def display_sync_summary(stats: dict[str, int]) -> None:
    """Print a summary panel after sync completes."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column(style="bold white")
    table.add_row("Models Synced", str(stats["total"]))
    table.add_row("New Models Added", str(stats["new"]))
    table.add_row("Price Changes Logged", str(stats["price_changes"]))

    console.print()
    console.print(Panel(table, title="[bold green]✓ Sync Complete[/]", border_style="green"))
    console.print()


# ── Stats Dashboard ────────────────────────────────────────────────────


def display_stats(data: dict[str, Any]) -> None:
    """Render the KPI dashboard for the ``stats`` subcommand (FR-03)."""
    kpis = data["kpis"]

    # -- Core KPI Panel --
    kpi_table = Table(show_header=False, box=None, padding=(0, 2))
    kpi_table.add_column(style="bold cyan", min_width=22)
    kpi_table.add_column(style="bold white", justify="right")
    kpi_table.add_row("Total Models", _fmt_int(kpis["total_models"]))
    kpi_table.add_row("Free Models", _fmt_int(kpis["free_models"]))
    kpi_table.add_row("Paid Models", _fmt_int(kpis["paid_models"]))
    kpi_table.add_row("Total Providers", _fmt_int(kpis["total_providers"]))
    kpi_table.add_row("Benchmarked Models", _fmt_int(kpis["benchmarked_models"]))

    console.print()
    console.print(Panel(kpi_table, title="[bold]📊 Market Overview[/]", border_style="blue"))

    # -- Context Window Distribution --
    ctx_table = Table(show_header=True, header_style="bold magenta", padding=(0, 1))
    ctx_table.add_column("Context Window", style="cyan")
    ctx_table.add_column("Count", justify="right", style="white")
    ctx_table.add_column("Bar", min_width=30)

    ctx_buckets = [
        ("≤ 32K", kpis["ctx_up_to_32k"]),
        ("32K – 128K", kpis["ctx_32k_to_128k"]),
        ("128K – 256K", kpis["ctx_128k_to_256k"]),
        ("256K – 1M", kpis["ctx_256k_to_1m"]),
        ("> 1M", kpis["ctx_over_1m"]),
    ]
    max_count = max((c for _, c in ctx_buckets), default=1) or 1
    for label, count in ctx_buckets:
        bar_len = int((count / max_count) * 30)
        bar = Text("█" * bar_len, style="green")
        ctx_table.add_row(label, str(count), bar)

    console.print(Panel(ctx_table, title="[bold]📐 Context Window Distribution[/]", border_style="blue"))

    # -- Top 10 Providers --
    prov_table = Table(show_header=True, header_style="bold magenta", padding=(0, 1))
    prov_table.add_column("#", style="dim", justify="right", width=3)
    prov_table.add_column("Provider", style="cyan")
    prov_table.add_column("Models", justify="right", style="white")

    for i, prov in enumerate(data["top_providers"], 1):
        prov_table.add_row(str(i), prov["provider"], str(prov["model_count"]))

    console.print(Panel(prov_table, title="[bold]🏢 Top 10 Providers[/]", border_style="blue"))

    # -- Input Modality Breakdown --
    mod_table = Table(show_header=True, header_style="bold magenta", padding=(0, 1))
    mod_table.add_column("Modality", style="cyan")
    mod_table.add_column("Models", justify="right", style="white")

    for mod, count in sorted(data["modality_breakdown"].items(), key=lambda x: -x[1]):
        mod_table.add_row(mod, str(count))

    console.print(Panel(mod_table, title="[bold]🔤 Input Modality Support[/]", border_style="blue"))
    console.print()


# ── List ───────────────────────────────────────────────────────────────


def display_list(rows: list[dict[str, Any]]) -> None:
    """Render the filtered model listing table (FR-04)."""
    if not rows:
        console.print("[yellow]No models match the given filters.[/]")
        return

    table = Table(
        show_header=True,
        header_style="bold magenta",
        title="[bold]Model Catalog[/]",
        padding=(0, 1),
    )
    table.add_column("#", style="dim", justify="right", width=4)
    table.add_column("Model ID", style="cyan", max_width=45)
    table.add_column("Provider", style="white")
    table.add_column("Context", justify="right")
    table.add_column("Prompt $/1M", justify="right", style="green")
    table.add_column("Comp $/1M", justify="right", style="green")
    table.add_column("IQ", justify="right")
    table.add_column("Code", justify="right")
    table.add_column("Agent", justify="right")
    table.add_column("Tools", justify="center")
    table.add_column("SO", justify="center")

    for i, row in enumerate(rows, 1):
        table.add_row(
            str(i),
            _truncate(row["id"], 45),
            row["provider"],
            _fmt_int(row["provider_context_length"]),
            _fmt_price(row["prompt_price_per_m"]),
            _fmt_price(row["completion_price_per_m"]),
            _fmt_index(row.get("intelligence_index")),
            _fmt_index(row.get("coding_index")),
            _fmt_index(row.get("agentic_index")),
            "✓" if row.get("supports_tools") else "✗",
            "✓" if row.get("supports_structured_outputs") else "✗",
        )

    console.print()
    console.print(table)
    console.print(f"\n[dim]Showing {len(rows)} model(s)[/]\n")


# ── Simulate ───────────────────────────────────────────────────────────


def display_simulate(
    rows: list[dict[str, Any]],
    *,
    input_tokens: int,
    output_tokens: int,
    calls_per_day: int,
    cache_hit_rate: float,
) -> None:
    """Render the cost simulation results table (FR-05)."""
    if not rows:
        console.print("[yellow]No models match the given simulation criteria.[/]")
        return

    # Summary header
    summary = (
        f"[bold]Workload:[/] {_fmt_int(input_tokens)} input + "
        f"{_fmt_int(output_tokens)} output tokens × "
        f"{_fmt_int(calls_per_day)} calls/day"
    )
    if cache_hit_rate > 0:
        summary += f"  |  Cache hit rate: {cache_hit_rate:.0%}"
    console.print(f"\n{summary}\n")

    table = Table(
        show_header=True,
        header_style="bold magenta",
        title="[bold]Cost Simulation[/]",
        padding=(0, 1),
    )
    table.add_column("#", style="dim", justify="right", width=4)
    table.add_column("Model ID", style="cyan", max_width=45)
    table.add_column("Provider", style="white")
    table.add_column("Context", justify="right")
    table.add_column("Prompt $/1M", justify="right", style="green")
    table.add_column("Comp $/1M", justify="right", style="green")
    table.add_column("Daily $", justify="right", style="bold yellow")
    table.add_column("Monthly $", justify="right", style="bold yellow")
    table.add_column("IQ", justify="right")

    for i, row in enumerate(rows, 1):
        table.add_row(
            str(i),
            _truncate(row["id"], 45),
            row["provider"],
            _fmt_int(row["provider_context_length"]),
            _fmt_price(row["prompt_price_per_m"]),
            _fmt_price(row["completion_price_per_m"]),
            _fmt_cost(row["daily_cost_usd"]),
            _fmt_cost(row["monthly_cost_usd"]),
            _fmt_index(row.get("intelligence_index")),
        )

    console.print(table)
    console.print(f"\n[dim]Showing {len(rows)} model(s)[/]\n")


# ── Rank ───────────────────────────────────────────────────────────────


def display_rank(rows: list[dict[str, Any]], *, metric: str) -> None:
    """Render the Pareto value ranking table (FR-06)."""
    if not rows:
        console.print("[yellow]No models have data for the selected metric.[/]")
        return

    table = Table(
        show_header=True,
        header_style="bold magenta",
        title=f"[bold]Value Ranking by {metric.title()} per Dollar[/]",
        padding=(0, 1),
    )
    table.add_column("#", style="dim", justify="right", width=4)
    table.add_column("Model ID", style="cyan", max_width=45)
    table.add_column("Provider", style="white")
    table.add_column("Blended $/1M", justify="right", style="green")
    table.add_column("IQ", justify="right")
    table.add_column("Code", justify="right")
    table.add_column("Agent", justify="right")
    table.add_column("Value Score", justify="right", style="bold yellow")

    for i, row in enumerate(rows, 1):
        table.add_row(
            str(i),
            _truncate(row["id"], 45),
            row["provider"],
            _fmt_price(row["blended_price_per_m"]),
            _fmt_index(row.get("intelligence_index")),
            _fmt_index(row.get("coding_index")),
            _fmt_index(row.get("agentic_index")),
            f"{row['value_score']:.2f}",
        )

    console.print()
    console.print(table)
    console.print(f"\n[dim]Showing {len(rows)} model(s)[/]\n")


# ── Empty DB Warning ───────────────────────────────────────────────────


def display_empty_db_warning() -> None:
    """Prompt the user to run sync when the database is empty (NFR-03)."""
    console.print(
        "\n[bold yellow]⚠ Database is empty.[/] "
        "Run [bold cyan]model-bench sync[/] first to fetch the model catalog.\n"
    )
