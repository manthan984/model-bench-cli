"""Markdown & CSV file export utilities for model-bench.

Responsibilities:
- Writes query results to ``.md`` or ``.csv`` files
- Supports the ``--export <filepath>`` global option (FR-07)
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from rich.console import Console

console = Console()


def export_results(
    filepath: str,
    rows: list[dict[str, Any]],
    *,
    title: str = "model-bench Report",
) -> None:
    """Export query result rows to a file.

    Dispatches to Markdown or CSV based on file extension.

    Args:
        filepath: Target file path (must end with ``.md`` or ``.csv``).
        rows: List of row dicts to export.
        title: Title for Markdown report header.

    Raises:
        SystemExit: If the extension is unsupported or rows are empty.
    """
    if not rows:
        console.print("[yellow]No data to export.[/]")
        return

    path = Path(filepath)
    ext = path.suffix.lower()

    if ext not in (".md", ".csv"):
        raise SystemExit(
            f"[error] Unsupported export format '{ext}'. Use .md or .csv"
        )

    # Create parent directories if needed
    path.parent.mkdir(parents=True, exist_ok=True)

    if ext == ".csv":
        _export_csv(path, rows)
    else:
        _export_markdown(path, rows, title=title)

    console.print(f"\n[bold green]✓ Exported {len(rows)} rows to[/] {path}\n")


def _export_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write rows to a CSV file."""
    headers = list(rows[0].keys())

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _export_markdown(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    title: str,
) -> None:
    """Write rows to a Markdown table file."""
    headers = list(rows[0].keys())

    lines: list[str] = []
    lines.append(f"# {title}\n")
    lines.append(f"*{len(rows)} records*\n")

    # Header row
    lines.append("| " + " | ".join(headers) + " |")
    # Separator
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    # Data rows
    for row in rows:
        cells = []
        for h in headers:
            val = row.get(h)
            cells.append("—" if val is None else str(val))
        lines.append("| " + " | ".join(cells) + " |")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
