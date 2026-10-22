# System Architecture & Database Design: `model-bench`

**Document Version:** 2.0.0 (Final)  
**Status:** Approved for Implementation  

---

## 1. Architectural Pattern & Layer Responsibilities

`model-bench` uses a decoupled **3-Layer Architecture** so that HTTP ingestion, SQLite persistence, and CLI presentation can be tested and modified independently.

```text
+-----------------------------------------------------------------------+
|                        1. Presentation Layer                          |
|     (src/model_bench/cli.py, display.py, exporter.py)                 |
|  - Parses CLI arguments via `argparse`                                |
|  - Renders formatted terminal tables & KPI panels via `rich`          |
|  - Writes `.md` and `.csv` reports to local filesystem                |
+-----------------------------------+-----------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------+
|                    2. Ingestion & Normalization Layer                 |
|                      (src/model_bench/client.py)                      |
|  - Fetches raw JSON from OpenRouter REST API (`requests`)             |
|  - Sanitizes edge cases (~ aliases, :batch, empty strings, -1 prices) |
|  - Normalizes token pricing to USD per 1M tokens                      |
+-----------------------------------+-----------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------+
|                       3. Data Persistence Layer                       |
|                        (src/model_bench/db.py)                        |
|  - Manages SQLite3 connections & atomic transactions                  |
|  - Executes upserts and appends audit rows to `price_history`         |
|  - Runs analytical SQL queries (cost simulation, Pareto ranking, KPIs)|
+-----------------------------------------------------------------------+
```

---

## 2. Project Directory Structure

```text
model-bench-cli/
├── docs/
│   ├── REQUIREMENTS.md          # Software Requirements Specification
│   └── ARCHITECTURE.md          # System Architecture & DB Schema
├── src/
│   └── model_bench/
│       ├── __init__.py          # Package version metadata
│       ├── cli.py               # Entry point & subcommand routing
│       ├── client.py            # HTTP client & JSON record normalizer
│       ├── db.py                # SQLite schema & analytical SQL queries
│       ├── display.py           # Rich terminal tables & KPI dashboard
│       └── exporter.py          # Markdown & CSV file export utilities
├── tests/
│   ├── sample_payload.json      # Offline OpenRouter payload fixture
│   └── test_normalizer.py       # Unit tests for edge-case parsing
├── .gitignore
├── pyproject.toml               # Build & CLI entry-point configuration
└── README.md                    # User documentation & sample outputs
```

---

## 3. SQLite3 Relational Schema

**Default Database Path:** `~/.local/share/model-bench/models.db` (automatically created on first run; overridable via `MODEL_BENCH_DB_PATH` environment variable).

### 3.1 `models` Table
```sql
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
```

### 3.2 `price_history` Table
```sql
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
```

---

## 4. Field Mapping & Normalization Specification (`client.py`)

| SQLite Column | Source JSON Path | Normalization Rule |
| :--- | :--- | :--- |
| `id` | `raw["id"]` | Required string; skip record if missing. |
| `canonical_slug` | `raw.get("canonical_slug")` | Nullable string. |
| `provider` | `raw["id"]` | `raw["id"].split("/")[0].lstrip("~")` (e.g., `"~openai/..."` -> `"openai"`). |
| `name` | `raw.get("name")` | Fallback to `id` if missing. |
| `created_at` | `raw.get("created")` | Integer Unix timestamp or `None`. |
| `context_length` | `raw.get("context_length")` | Integer; default `0` if `None`. |
| `provider_context_length` | `raw.get("top_provider", {}).get("context_length")` | Integer; fallback to `context_length` if `None`. |
| `max_completion_tokens` | `raw.get("top_provider", {}).get("max_completion_tokens")` | Nullable integer (`None` if unspecified). |
| `modality` | `raw.get("architecture", {}).get("modality")` | String; default `"unknown"`. |
| `input_modalities` | `raw.get("architecture", {}).get("input_modalities")` | Sorted comma-joined string: `",".join(sorted(list))` (default `"text"`). |
| `output_modalities` | `raw.get("architecture", {}).get("output_modalities")` | Sorted comma-joined string: `",".join(sorted(list))` (default `"text"`). |
| `tokenizer` | `raw.get("architecture", {}).get("tokenizer")` | Nullable string. |
| `hugging_face_id` | `raw.get("hugging_face_id")` | `(val or "").strip() or None` (converts `""` to `None`). |
| `prompt_price_per_m` | `raw.get("pricing", {}).get("prompt")` | `round(float(val) * 1_000_000, 6)` (negative if `< 0`). |
| `completion_price_per_m` | `raw.get("pricing", {}).get("completion")` | `round(float(val) * 1_000_000, 6)` (negative if `< 0`). |
| `cache_read_price_per_m` | `raw.get("pricing", {}).get("input_cache_read")` | `round(float(val) * 1_000_000, 6)` if present and not `None`, else `None`. |
| `intelligence_index` | `raw["benchmarks"]["artificial_analysis"]["intelligence_index"]` | Nullable float via safe chained `.get()`. |
| `coding_index` | `raw["benchmarks"]["artificial_analysis"]["coding_index"]` | Nullable float via safe chained `.get()`. |
| `agentic_index` | `raw["benchmarks"]["artificial_analysis"]["agentic_index"]` | Nullable float via safe chained `.get()`. |
| `supports_tools` | `raw.get("supported_parameters")` | `1` if `"tools"` in list, else `0`. |
| `supports_structured_outputs` | `raw.get("supported_parameters")` | `1` if `"structured_outputs"` in list, else `0`. |
| `mandatory_reasoning` | `raw.get("reasoning", {}).get("mandatory")` | `1` if `True`, else `0`. |
| `is_free` | Derived | `1` if `(prompt_price_per_m == 0 and completion_price_per_m == 0)` or `id.endswith(":free")`, else `0`. |
| `is_batch` | Derived | `1` if `id.endswith(":batch")`, else `0`. |
| `is_alias` | Derived | `1` if `id.startswith("~")` or `"alias_target" in raw`, else `0`. |

---

## 5. Core Analytical SQL Queries (`db.py`)

### 5.1 KPI & Distribution Aggregation (`stats`)
```sql
SELECT
    COUNT(*) AS total_models,
    SUM(CASE WHEN is_free = 1 THEN 1 ELSE 0 END) AS free_models,
    SUM(CASE WHEN is_free = 0 AND prompt_price_per_m >= 0 THEN 1 ELSE 0 END) AS paid_models,
    COUNT(DISTINCT provider) AS total_providers,
    SUM(CASE WHEN intelligence_index IS NOT NULL OR coding_index IS NOT NULL OR agentic_index IS NOT NULL THEN 1 ELSE 0 END) AS benchmarked_models,
    SUM(CASE WHEN context_length <= 32768 THEN 1 ELSE 0 END) AS ctx_up_to_32k,
    SUM(CASE WHEN context_length > 32768 AND context_length <= 131072 THEN 1 ELSE 0 END) AS ctx_32k_to_128k,
    SUM(CASE WHEN context_length > 131072 AND context_length <= 262144 THEN 1 ELSE 0 END) AS ctx_128k_to_256k,
    SUM(CASE WHEN context_length > 262144 AND context_length <= 1000000 THEN 1 ELSE 0 END) AS ctx_256k_to_1m,
    SUM(CASE WHEN context_length > 1000000 THEN 1 ELSE 0 END) AS ctx_over_1m
FROM models;
```

### 5.2 Workload Cost Simulation with Prompt Caching (`simulate`)
Calculates effective input cost by blending uncached input tokens (`1.0 - :cache_hit_rate`) at `prompt_price_per_m` and cached input tokens (`:cache_hit_rate`) at `COALESCE(cache_read_price_per_m, prompt_price_per_m)`:

```sql
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
  AND provider_context_length >= (:input_tokens + :output_tokens)
  AND (max_completion_tokens IS NULL OR max_completion_tokens >= :output_tokens)
  AND (:require_tools = 0 OR supports_tools = 1)
  AND (:min_intelligence IS NULL OR intelligence_index >= :min_intelligence)
ORDER BY monthly_cost_usd ASC, intelligence_index DESC
LIMIT :limit;
```

### 5.3 Pareto Value Ranking (`rank`)
Computes capability score per dollar using a 3:1 input-to-output blended token price (`0.75 * prompt + 0.25 * completion`):

```sql
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
        metric_column / ((prompt_price_per_m * 0.75) + (completion_price_per_m * 0.25)),
        2
    ) AS value_score
FROM models
WHERE prompt_price_per_m > 0
  AND completion_price_per_m > 0
  AND is_alias = 0
  AND is_batch = 0
  AND metric_column IS NOT NULL
ORDER BY value_score DESC
LIMIT :limit;
```