"""SQLite3 persistence layer for model-bench.

Responsibilities:
- Manages SQLite3 connections & atomic transactions
- Creates schema (models + price_history tables with indexes)
- Executes upserts and appends audit rows to price_history
- Runs analytical SQL queries (stats, list, simulate, rank)
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

# ── Database path resolution ───────────────────────────────────────────

DEFAULT_DB_DIR = Path.home() / ".local" / "share" / "model-bench"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "models.db"


def get_db_path() -> Path:
    """Return the database path, honouring ``MODEL_BENCH_DB_PATH`` env var."""
    env_path = os.environ.get("MODEL_BENCH_DB_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


# ── Connection management ──────────────────────────────────────────────


@contextmanager
def get_connection(db_path: Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    """Yield a SQLite connection with foreign keys enabled (NFR-02).

    Uses a context manager to guarantee the connection is closed on exit.
    """
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
    finally:
        conn.close()


# ── Schema ─────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS models (
    id TEXT PRIMARY KEY,
    canonical_slug TEXT,
    provider TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at INTEGER,
    context_length INTEGER NOT NULL DEFAULT 0,
    provider_context_length INTEGER NOT NULL DEFAULT 0,
    max_completion_tokens INTEGER,
    modality TEXT,
    input_modalities TEXT NOT NULL,
    output_modalities TEXT NOT NULL,
    tokenizer TEXT,
    hugging_face_id TEXT,
    prompt_price_per_m REAL NOT NULL,
    completion_price_per_m REAL NOT NULL,
    cache_read_price_per_m REAL,
    intelligence_index REAL,
    coding_index REAL,
    agentic_index REAL,
    supports_tools INTEGER NOT NULL DEFAULT 0,
    supports_structured_outputs INTEGER NOT NULL DEFAULT 0,
    mandatory_reasoning INTEGER NOT NULL DEFAULT 0,
    is_free INTEGER NOT NULL DEFAULT 0,
    is_batch INTEGER NOT NULL DEFAULT 0,
    is_alias INTEGER NOT NULL DEFAULT 0,
    last_synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_models_provider ON models(provider);
CREATE INDEX IF NOT EXISTS idx_models_context ON models(provider_context_length);
CREATE INDEX IF NOT EXISTS idx_models_pricing ON models(prompt_price_per_m, completion_price_per_m);
CREATE INDEX IF NOT EXISTS idx_models_benchmarks ON models(intelligence_index, coding_index, agentic_index);

CREATE TABLE IF NOT EXISTS price_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id TEXT NOT NULL,
    prompt_price_per_m REAL NOT NULL,
    completion_price_per_m REAL NOT NULL,
    cache_read_price_per_m REAL,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (model_id) REFERENCES models(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_history_model_id ON price_history(model_id);
"""


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Create tables and indexes if they don't already exist."""
    conn.executescript(_SCHEMA_SQL)


# ── Sync / Upsert ─────────────────────────────────────────────────────

_UPSERT_SQL = """
INSERT INTO models (
    id, canonical_slug, provider, name, created_at,
    context_length, provider_context_length, max_completion_tokens,
    modality, input_modalities, output_modalities, tokenizer,
    hugging_face_id,
    prompt_price_per_m, completion_price_per_m, cache_read_price_per_m,
    intelligence_index, coding_index, agentic_index,
    supports_tools, supports_structured_outputs, mandatory_reasoning,
    is_free, is_batch, is_alias,
    last_synced_at
) VALUES (
    :id, :canonical_slug, :provider, :name, :created_at,
    :context_length, :provider_context_length, :max_completion_tokens,
    :modality, :input_modalities, :output_modalities, :tokenizer,
    :hugging_face_id,
    :prompt_price_per_m, :completion_price_per_m, :cache_read_price_per_m,
    :intelligence_index, :coding_index, :agentic_index,
    :supports_tools, :supports_structured_outputs, :mandatory_reasoning,
    :is_free, :is_batch, :is_alias,
    CURRENT_TIMESTAMP
)
ON CONFLICT(id) DO UPDATE SET
    canonical_slug              = excluded.canonical_slug,
    provider                    = excluded.provider,
    name                        = excluded.name,
    created_at                  = excluded.created_at,
    context_length              = excluded.context_length,
    provider_context_length     = excluded.provider_context_length,
    max_completion_tokens       = excluded.max_completion_tokens,
    modality                    = excluded.modality,
    input_modalities            = excluded.input_modalities,
    output_modalities           = excluded.output_modalities,
    tokenizer                   = excluded.tokenizer,
    hugging_face_id             = excluded.hugging_face_id,
    prompt_price_per_m          = excluded.prompt_price_per_m,
    completion_price_per_m      = excluded.completion_price_per_m,
    cache_read_price_per_m      = excluded.cache_read_price_per_m,
    intelligence_index          = excluded.intelligence_index,
    coding_index                = excluded.coding_index,
    agentic_index               = excluded.agentic_index,
    supports_tools              = excluded.supports_tools,
    supports_structured_outputs = excluded.supports_structured_outputs,
    mandatory_reasoning         = excluded.mandatory_reasoning,
    is_free                     = excluded.is_free,
    is_batch                    = excluded.is_batch,
    is_alias                    = excluded.is_alias,
    last_synced_at              = CURRENT_TIMESTAMP;
"""


def upsert_models(
    conn: sqlite3.Connection,
    records: list[dict[str, Any]],
) -> dict[str, int]:
    """Upsert normalized model records inside an atomic transaction.

    Also inserts price_history rows for new models and price changes (FR-02).

    Returns:
        A dict with keys ``total``, ``new``, ``price_changes``.
    """
    cursor = conn.cursor()
    total = 0
    new_count = 0
    price_change_count = 0

    with conn:
        for record in records:
            # Check if model already exists and track price changes
            existing = cursor.execute(
                "SELECT prompt_price_per_m, completion_price_per_m, "
                "cache_read_price_per_m FROM models WHERE id = ?",
                (record["id"],),
            ).fetchone()

            cursor.execute(_UPSERT_SQL, record)
            total += 1

            if existing is None:
                # New model → insert initial price history record
                new_count += 1
                cursor.execute(
                    "INSERT INTO price_history "
                    "(model_id, prompt_price_per_m, completion_price_per_m, cache_read_price_per_m) "
                    "VALUES (:id, :prompt_price_per_m, :completion_price_per_m, :cache_read_price_per_m)",
                    record,
                )
            else:
                # Existing model → log if prices changed
                old_prompt = existing["prompt_price_per_m"]
                old_completion = existing["completion_price_per_m"]
                if (
                    old_prompt != record["prompt_price_per_m"]
                    or old_completion != record["completion_price_per_m"]
                ):
                    price_change_count += 1
                    cursor.execute(
                        "INSERT INTO price_history "
                        "(model_id, prompt_price_per_m, completion_price_per_m, cache_read_price_per_m) "
                        "VALUES (:id, :prompt_price_per_m, :completion_price_per_m, :cache_read_price_per_m)",
                        record,
                    )

    return {"total": total, "new": new_count, "price_changes": price_change_count}


# ── Analytical Queries ─────────────────────────────────────────────────


def is_db_empty(conn: sqlite3.Connection) -> bool:
    """Return True if the models table has zero rows."""
    row = conn.execute("SELECT COUNT(*) AS cnt FROM models").fetchone()
    return row["cnt"] == 0


def query_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return KPI dashboard data for the ``stats`` subcommand (FR-03)."""
    # Core KPIs
    kpi_row = conn.execute("""
        SELECT
            COUNT(*) AS total_models,
            SUM(CASE WHEN is_free = 1 THEN 1 ELSE 0 END) AS free_models,
            SUM(CASE WHEN is_free = 0 AND prompt_price_per_m >= 0 THEN 1 ELSE 0 END) AS paid_models,
            COUNT(DISTINCT provider) AS total_providers,
            SUM(CASE WHEN intelligence_index IS NOT NULL
                       OR coding_index IS NOT NULL
                       OR agentic_index IS NOT NULL THEN 1 ELSE 0 END) AS benchmarked_models,
            SUM(CASE WHEN context_length <= 32768 THEN 1 ELSE 0 END) AS ctx_up_to_32k,
            SUM(CASE WHEN context_length > 32768  AND context_length <= 131072  THEN 1 ELSE 0 END) AS ctx_32k_to_128k,
            SUM(CASE WHEN context_length > 131072 AND context_length <= 262144  THEN 1 ELSE 0 END) AS ctx_128k_to_256k,
            SUM(CASE WHEN context_length > 262144 AND context_length <= 1000000 THEN 1 ELSE 0 END) AS ctx_256k_to_1m,
            SUM(CASE WHEN context_length > 1000000 THEN 1 ELSE 0 END) AS ctx_over_1m
        FROM models;
    """).fetchone()

    # Top 10 providers by model count
    top_providers = conn.execute("""
        SELECT provider, COUNT(*) AS model_count
        FROM models
        GROUP BY provider
        ORDER BY model_count DESC
        LIMIT 10;
    """).fetchall()

    # Input modality breakdown
    # Since input_modalities is a comma-joined string, we need to split
    modality_rows = conn.execute("""
        SELECT input_modalities FROM models;
    """).fetchall()

    modality_counts: dict[str, int] = {}
    for row in modality_rows:
        for mod in row["input_modalities"].split(","):
            mod = mod.strip()
            if mod:
                modality_counts[mod] = modality_counts.get(mod, 0) + 1

    return {
        "kpis": dict(kpi_row),
        "top_providers": [dict(r) for r in top_providers],
        "modality_breakdown": modality_counts,
    }


# Valid sort columns for the list query (whitelist to prevent SQL injection)
_LIST_SORT_COLUMNS = {
    "newest": "created_at DESC NULLS LAST",
    "price": "prompt_price_per_m ASC",
    "context": "provider_context_length DESC",
    "iq": "intelligence_index DESC NULLS LAST",
    "code": "coding_index DESC NULLS LAST",
    "agentic": "agentic_index DESC NULLS LAST",
}


def query_list(
    conn: sqlite3.Connection,
    *,
    provider: str | None = None,
    min_context: int | None = None,
    max_prompt: float | None = None,
    modality: str | None = None,
    tools: bool = False,
    structured_outputs: bool = False,
    open_weights: bool = False,
    free_only: bool = False,
    include_batch: bool = False,
    include_aliases: bool = False,
    sort_by: str = "newest",
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Execute a filtered model listing query (FR-04)."""
    conditions = [
        "prompt_price_per_m >= 0",
        "completion_price_per_m >= 0",
    ]
    params: dict[str, Any] = {}

    # Exclude batch and alias by default
    if not include_batch:
        conditions.append("is_batch = 0")
    if not include_aliases:
        conditions.append("is_alias = 0")

    if provider:
        conditions.append("provider = :provider")
        params["provider"] = provider
    if min_context is not None:
        conditions.append("provider_context_length >= :min_context")
        params["min_context"] = min_context
    if max_prompt is not None:
        conditions.append("prompt_price_per_m <= :max_prompt")
        params["max_prompt"] = max_prompt
    if modality:
        conditions.append("input_modalities LIKE :modality")
        params["modality"] = f"%{modality}%"
    if tools:
        conditions.append("supports_tools = 1")
    if structured_outputs:
        conditions.append("supports_structured_outputs = 1")
    if open_weights:
        conditions.append("hugging_face_id IS NOT NULL")
    if free_only:
        conditions.append("is_free = 1")

    where = " AND ".join(conditions)
    params["limit"] = limit

    # sort_by is from a static whitelist, safe to interpolate
    order_clause = _LIST_SORT_COLUMNS.get(sort_by, _LIST_SORT_COLUMNS["newest"])

    rows = conn.execute(
        f"""
        SELECT
            id, name, provider, modality,
            provider_context_length, max_completion_tokens,
            prompt_price_per_m, completion_price_per_m, cache_read_price_per_m,
            intelligence_index, coding_index, agentic_index,
            supports_tools, supports_structured_outputs,
            hugging_face_id, is_free, is_batch
        FROM models
        WHERE {where}
        ORDER BY {order_clause}, name ASC
        LIMIT :limit;
        """,
        params,
    ).fetchall()

    return [dict(r) for r in rows]


def query_simulate(
    conn: sqlite3.Connection,
    *,
    input_tokens: int,
    output_tokens: int,
    calls_per_day: int,
    cache_hit_rate: float = 0.0,
    require_tools: bool = False,
    min_intelligence: float | None = None,
    include_batch: bool = False,
    include_free: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Execute the cost simulation query (FR-05).

    Free models are excluded by default because simulating dollar spend
    on rate-limited $0.00 endpoints is rarely useful.
    """
    params: dict[str, Any] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "calls_per_day": calls_per_day,
        "cache_hit_rate": cache_hit_rate,
        "require_tools": 1 if require_tools else 0,
        "min_intelligence": min_intelligence,
        "include_batch": 1 if include_batch else 0,
        "include_free": 1 if include_free else 0,
        "limit": limit,
    }

    rows = conn.execute(
        """
        SELECT
            id,
            name,
            provider,
            provider_context_length,
            prompt_price_per_m,
            completion_price_per_m,
            cache_read_price_per_m,
            intelligence_index,
            agentic_index,
            ROUND(
                (
                    ((:input_tokens / 1000000.0) * (
                        ((1.0 - :cache_hit_rate) * prompt_price_per_m) +
                        (:cache_hit_rate * COALESCE(cache_read_price_per_m, prompt_price_per_m))
                    )) +
                    ((:output_tokens / 1000000.0) * completion_price_per_m)
                ) * :calls_per_day,
                4
            ) AS daily_cost_usd,
            ROUND(
                (
                    ((:input_tokens / 1000000.0) * (
                        ((1.0 - :cache_hit_rate) * prompt_price_per_m) +
                        (:cache_hit_rate * COALESCE(cache_read_price_per_m, prompt_price_per_m))
                    )) +
                    ((:output_tokens / 1000000.0) * completion_price_per_m)
                ) * :calls_per_day * 30,
                2
            ) AS monthly_cost_usd
        FROM models
        WHERE prompt_price_per_m >= 0
          AND completion_price_per_m >= 0
          AND is_alias = 0
          AND (:include_batch = 1 OR is_batch = 0)
          AND (:include_free = 1 OR is_free = 0)
          AND provider_context_length >= (:input_tokens + :output_tokens)
          AND (max_completion_tokens IS NULL OR max_completion_tokens >= :output_tokens)
          AND (:require_tools = 0 OR supports_tools = 1)
          AND (:min_intelligence IS NULL OR intelligence_index >= :min_intelligence)
        ORDER BY monthly_cost_usd ASC, intelligence_index DESC
        LIMIT :limit;
        """,
        params,
    ).fetchall()

    return [dict(r) for r in rows]


# Valid metric columns for the rank query (whitelist to prevent SQL injection)
_RANK_METRIC_COLUMNS = {
    "intelligence": "intelligence_index",
    "coding": "coding_index",
    "agentic": "agentic_index",
    "context": "provider_context_length",
}


def query_rank(
    conn: sqlite3.Connection,
    *,
    metric: str = "intelligence",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Execute the Pareto value ranking query (FR-06)."""
    metric_column = _RANK_METRIC_COLUMNS.get(metric)
    if metric_column is None:
        valid = ", ".join(_RANK_METRIC_COLUMNS.keys())
        raise ValueError(f"Invalid metric '{metric}'. Valid options: {valid}")

    # metric_column is from a static whitelist, safe to interpolate
    rows = conn.execute(
        f"""
        SELECT
            id,
            name,
            provider,
            prompt_price_per_m,
            completion_price_per_m,
            ROUND((prompt_price_per_m * 0.75) + (completion_price_per_m * 0.25), 4) AS blended_price_per_m,
            intelligence_index,
            coding_index,
            agentic_index,
            ROUND(
                {metric_column} / ((prompt_price_per_m * 0.75) + (completion_price_per_m * 0.25)),
                2
            ) AS value_score
        FROM models
        WHERE prompt_price_per_m > 0
          AND completion_price_per_m > 0
          AND is_alias = 0
          AND is_batch = 0
          AND {metric_column} IS NOT NULL
        ORDER BY value_score DESC
        LIMIT :limit;
        """,
        {"limit": limit},
    ).fetchall()

    return [dict(r) for r in rows]
