"""CLI entry point & subcommand routing for model-bench.

Responsibilities:
- Parses CLI arguments via ``argparse``
- Routes to the appropriate subcommand handler
- Passes --export flag to the exporter when present
"""

from __future__ import annotations

import argparse
import sys

from model_bench import __version__
from model_bench.client import fetch_models, normalize_record
from model_bench.db import (
    get_connection,
    initialize_schema,
    is_db_empty,
    query_list,
    query_rank,
    query_simulate,
    query_stats,
    upsert_models,
)
from model_bench.display import (
    display_empty_db_warning,
    display_list,
    display_rank,
    display_simulate,
    display_stats,
    display_sync_summary,
)
from model_bench.exporter import export_results


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="model-bench",
        description="Local-first CLI analytics engine for Agentic AI models.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # ── sync ───────────────────────────────────────────────────────────
    subparsers.add_parser(
        "sync",
        help="Synchronize local database with live OpenRouter catalog",
    )

    # ── stats ──────────────────────────────────────────────────────────
    subparsers.add_parser(
        "stats",
        help="View market KPI overview & distributions",
    )

    # ── list ───────────────────────────────────────────────────────────
    list_parser = subparsers.add_parser(
        "list",
        help="List models with optional filters",
    )
    list_parser.add_argument("--provider", type=str, help="Filter by provider name")
    list_parser.add_argument("--min-context", type=int, help="Minimum context length")
    list_parser.add_argument(
        "--max-prompt", type=float, help="Maximum prompt price per 1M tokens"
    )
    list_parser.add_argument(
        "--modality",
        type=str,
        choices=["text", "image", "file", "video", "audio"],
        help="Filter by input modality",
    )
    list_parser.add_argument(
        "--tools", action="store_true", help="Require tool-calling support"
    )
    list_parser.add_argument(
        "--structured-outputs",
        action="store_true",
        help="Require structured outputs support",
    )
    list_parser.add_argument(
        "--open-weights",
        action="store_true",
        help="Only open-weight models (has Hugging Face ID)",
    )
    list_parser.add_argument(
        "--free-only", action="store_true", help="Only free models"
    )
    list_parser.add_argument(
        "--include-batch",
        action="store_true",
        help="Include :batch variant SKUs",
    )
    list_parser.add_argument(
        "--include-aliases",
        action="store_true",
        help="Include ~ alias SKUs",
    )
    list_parser.add_argument(
        "--limit", type=int, default=25, help="Max results (default: 25)"
    )
    list_parser.add_argument(
        "--sort",
        type=str,
        choices=["newest", "price", "context", "iq", "code", "agentic"],
        default="newest",
        help="Sort order (default: newest)",
    )
    list_parser.add_argument(
        "--export", type=str, metavar="FILEPATH", help="Export to .md or .csv file"
    )

    # ── simulate ───────────────────────────────────────────────────────
    sim_parser = subparsers.add_parser(
        "simulate",
        help="Simulate workload costs",
    )
    sim_parser.add_argument(
        "--input-tokens", type=int, required=True, help="Input tokens per call"
    )
    sim_parser.add_argument(
        "--output-tokens", type=int, required=True, help="Output tokens per call"
    )
    sim_parser.add_argument(
        "--calls-per-day", type=int, required=True, help="Number of calls per day"
    )
    sim_parser.add_argument(
        "--cache-hit-rate",
        type=float,
        default=0.0,
        help="Prompt cache hit rate 0.0-1.0 (default: 0.0)",
    )
    sim_parser.add_argument(
        "--tools", action="store_true", help="Require tool-calling support"
    )
    sim_parser.add_argument(
        "--min-intelligence",
        type=float,
        default=None,
        help="Minimum intelligence index score",
    )
    sim_parser.add_argument(
        "--include-batch",
        action="store_true",
        help="Include :batch variant SKUs",
    )
    sim_parser.add_argument(
        "--include-free",
        action="store_true",
        help="Include $0.00 free-tier models in results",
    )
    sim_parser.add_argument(
        "--limit", type=int, default=20, help="Max results (default: 20)"
    )
    sim_parser.add_argument(
        "--export", type=str, metavar="FILEPATH", help="Export to .md or .csv file"
    )

    # ── rank ───────────────────────────────────────────────────────────
    rank_parser = subparsers.add_parser(
        "rank",
        help="Rank models by capability-to-cost efficiency",
    )
    rank_parser.add_argument(
        "--metric",
        type=str,
        choices=["intelligence", "coding", "agentic", "context"],
        default="intelligence",
        help="Ranking metric (default: intelligence)",
    )
    rank_parser.add_argument(
        "--limit", type=int, default=20, help="Max results (default: 20)"
    )
    rank_parser.add_argument(
        "--export", type=str, metavar="FILEPATH", help="Export to .md or .csv file"
    )

    return parser


# ── Subcommand Handlers ────────────────────────────────────────────────


def _handle_sync() -> None:
    """Handle the ``sync`` subcommand (FR-01, FR-02)."""
    raw_models = fetch_models()

    records = []
    for raw in raw_models:
        normalized = normalize_record(raw)
        if normalized is not None:
            records.append(normalized)

    with get_connection() as conn:
        initialize_schema(conn)
        stats = upsert_models(conn, records)

    display_sync_summary(stats)


def _handle_stats() -> None:
    """Handle the ``stats`` subcommand (FR-03)."""
    with get_connection() as conn:
        initialize_schema(conn)
        if is_db_empty(conn):
            display_empty_db_warning()
            sys.exit(1)
        data = query_stats(conn)

    display_stats(data)


def _handle_list(args: argparse.Namespace) -> None:
    """Handle the ``list`` subcommand (FR-04)."""
    with get_connection() as conn:
        initialize_schema(conn)
        if is_db_empty(conn):
            display_empty_db_warning()
            sys.exit(1)

        rows = query_list(
            conn,
            provider=args.provider,
            min_context=args.min_context,
            max_prompt=args.max_prompt,
            modality=args.modality,
            tools=args.tools,
            structured_outputs=args.structured_outputs,
            open_weights=args.open_weights,
            free_only=args.free_only,
            include_batch=args.include_batch,
            include_aliases=args.include_aliases,
            sort_by=args.sort,
            limit=args.limit,
        )

    display_list(rows)

    if args.export:
        export_results(args.export, rows, title="Model Catalog")


def _handle_simulate(args: argparse.Namespace) -> None:
    """Handle the ``simulate`` subcommand (FR-05)."""
    # Validate cache-hit-rate range
    if not 0.0 <= args.cache_hit_rate <= 1.0:
        raise SystemExit(
            "[error] --cache-hit-rate must be between 0.0 and 1.0"
        )

    with get_connection() as conn:
        initialize_schema(conn)
        if is_db_empty(conn):
            display_empty_db_warning()
            sys.exit(1)

        rows = query_simulate(
            conn,
            input_tokens=args.input_tokens,
            output_tokens=args.output_tokens,
            calls_per_day=args.calls_per_day,
            cache_hit_rate=args.cache_hit_rate,
            require_tools=args.tools,
            min_intelligence=args.min_intelligence,
            include_batch=args.include_batch,
            include_free=args.include_free,
            limit=args.limit,
        )

    display_simulate(
        rows,
        input_tokens=args.input_tokens,
        output_tokens=args.output_tokens,
        calls_per_day=args.calls_per_day,
        cache_hit_rate=args.cache_hit_rate,
    )

    if args.export:
        export_results(args.export, rows, title="Cost Simulation Report")


def _handle_rank(args: argparse.Namespace) -> None:
    """Handle the ``rank`` subcommand (FR-06)."""
    with get_connection() as conn:
        initialize_schema(conn)
        if is_db_empty(conn):
            display_empty_db_warning()
            sys.exit(1)

        rows = query_rank(conn, metric=args.metric, limit=args.limit)

    display_rank(rows, metric=args.metric)

    if args.export:
        export_results(
            args.export, rows, title=f"Value Ranking by {args.metric.title()}"
        )


# ── Main ───────────────────────────────────────────────────────────────


def main() -> None:
    """Parse arguments and dispatch to the correct subcommand."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "sync":
        _handle_sync()
    elif args.command == "stats":
        _handle_stats()
    elif args.command == "list":
        _handle_list(args)
    elif args.command == "simulate":
        _handle_simulate(args)
    elif args.command == "rank":
        _handle_rank(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
