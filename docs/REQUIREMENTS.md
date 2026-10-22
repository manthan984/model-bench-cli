# Software Requirements Specification (SRS): `model-bench`

**Document Version:** 2.0.0 (Final)  
**Status:** Approved for Implementation  
**Target Environment:** Linux / POSIX Terminal (Python 3.10+)  

---;

## 1. Purpose & Problem Statement
Builders of Agentic AI systems face rapid model churn, complex pricing tiers (base prompt, completion, cache reads, and batch queues), and varying capability support (tool calling, structured outputs, reasoning) across 460+ models and 50+ providers. `model-bench` is a local-first CLI analytics engine that ingests live LLM market and benchmark data from the public OpenRouter API, persists historical snapshots in a local SQLite database, and executes SQL-driven cost simulations and capability-per-dollar rankings offline.

---

## 2. Project Scope

### 2.1 In-Scope (v1.0)
* Unauthenticated HTTP ingestion from `GET [https://openrouter.ai/api/v1/models](https://openrouter.ai/api/v1/models)`.
* Data normalization, edge-case sanitization, and relational persistence in SQLite3.
* Historical price change auditing across synchronization runs.
* Offline CLI subcommands for market statistics (`stats`), multi-criteria filtering (`list`), workload cost simulation with prompt-caching support (`simulate`), Pareto value ranking (`rank`), and file exporting (`export`).

### 2.2 Out-of-Scope (v1.0)
* Live LLM inference or prompt completion requests.
* Time-of-day or prompt-length tier override simulation (`pricing.overrides` array).
* Web UI, GUI, or hosted database servers.

---

## 3. Upstream Data Contract & Empirical Edge Cases

**Endpoint:** `GET [https://openrouter.ai/api/v1/models](https://openrouter.ai/api/v1/models)`  
**Authentication:** None required.  

### 3.1 Representative Upstream Payload Structure
```json
{
  "data": [
    {
      "id": "openai/gpt-6-astra",
      "canonical_slug": "openai/gpt-6-astra-20260903",
      "hugging_face_id": null,
      "name": "OpenAI: GPT-6 Astra",
      "created": 1788552838,
      "context_length": 1050000,
      "architecture": {
        "modality": "text+image+file->text",
        "input_modalities": ["file", "image", "text"],
        "output_modalities": ["text"],
        "tokenizer": "GPT"
      },
      "pricing": {
        "prompt": "0.00001",
        "completion": "0.00005",
        "input_cache_read": "0.000001"
      },
      "top_provider": {
        "context_length": 1050000,
        "max_completion_tokens": 128000,
        "is_moderated": true
      },
      "supported_parameters": [
        "include_reasoning",
        "max_completion_tokens",
        "reasoning",
        "structured_outputs",
        "tool_choice",
        "tools"
      ],
      "benchmarks": {
        "artificial_analysis": {
          "intelligence_index": 52.7,
          "coding_index": 76.9,
          "agentic_index": 51.0
        }
      },
      "reasoning": {
        "mandatory": true,
        "default_effort": "medium"
      }
    }
  ]
}
```

### 3.2 Mandatory Data Sanitization Rules
1. **String-to-Float Price Normalization:** Upstream prices (`prompt`, `completion`, `input_cache_read`) are strings representing USD *per single token* (e.g., `"0.00001"`). The parser must cast these to `float` and multiply by `1_000_000` to store **USD per 1 Million (1M) tokens** (e.g., `10.0`). If `input_cache_read` is absent, store `NULL`.
2. **Dynamic Router Negative Pricing:** Routing meta-models (e.g., `typesafe/jev-router`, `nvidia/switchyard`) return `"-1"` for prompt and completion pricing. Multiplied by 1M, these become `-1000000.0`. All analytical and cost queries must filter `WHERE prompt_price_per_m >= 0 AND completion_price_per_m >= 0`.
3. **Tilde (`~`) Alias SKUs:** Auto-redirecting aliases (e.g., `~openai/gpt-astra-latest`, `~deepseek/deepseek-pro-latest`) prefix `id` with `~` and include an `alias_target` object. The parser must strip leading `~` when extracting `provider` (`id.split("/")[0].lstrip("~")`) and set `is_alias = 1`.
4. **SKU Variants (`:batch` and `:free`):** Many models have asynchronous `:batch` variants (50% cheaper, e.g., `anthropic/claude-opus-5.5:batch`) and `:free` variants (`minimax/minimax-m3.1-flash:free`). The parser must set `is_batch = 1` if `id.endswith(":batch")` and `is_free = 1` if both prompt and completion prices equal `0` (or `id.endswith(":free")`).
5. **Empty String vs. Null `hugging_face_id`:** Some closed models return `"hugging_face_id": ""` instead of `null` (e.g., `z-ai/glm-5.3-flashx`). The parser must strip whitespace and convert empty strings to `None` (`NULL` in SQLite) so open-weight filtering remains accurate.
6. **Provider vs. Advertised Context Length:** Some models advertise `context_length: 1000000` at the top level while `top_provider.context_length` is only `262144` (e.g., `nvidia/nemotron-3.5-super-vl`), whereas routers set `top_provider.context_length` to `null`. The parser must store both `context_length` and `provider_context_length` (falling back to top-level `context_length` if `top_provider.context_length` is `null`).
7. **Sparse Benchmark & Capability Keys:** `benchmarks`, `benchmarks.artificial_analysis`, `reasoning`, and `supported_parameters` may be missing, empty, or partially `null`. The parser must safely extract:
   * `intelligence_index`, `coding_index`, `agentic_index` (`REAL` or `NULL`).
   * `supports_tools` (`1` if `"tools"` in `supported_parameters`, else `0`).
   * `supports_structured_outputs` (`1` if `"structured_outputs"` in `supported_parameters`, else `0`).
   * `mandatory_reasoning` (`1` if `reasoning.mandatory` is `True`, else `0`).

---

## 4. Functional Requirements (FR)

| ID | Subcommand | Description & Acceptance Criteria |
| :--- | :--- | :--- |
| **FR-01** | `sync` | Fetches the live catalog from OpenRouter, normalizes all records per Section 3.2, and upserts them into SQLite inside an atomic transaction. Prints summary metrics: total models synced, new models added, and price changes logged. |
| **FR-02** | *(Internal)* | **Price History Audit:** During `sync`, if a model is newly inserted or its `prompt_price_per_m` / `completion_price_per_m` differs from the stored value in `models`, inserts a timestamped record into `price_history`. |
| **FR-03** | `stats` | Queries SQLite to render a terminal KPI dashboard: Total Models, Free vs. Paid count, Total Providers, Benchmarked Models count, Top 10 Providers by model count, Input Modality support breakdown, and Context Window distribution (`<=32K`, `32K-128K`, `128K-256K`, `256K-1M`, `>1M`). |
| **FR-04** | `list` | Queries local SQLite catalog with optional filters: `--provider <str>`, `--min-context <int>`, `--max-prompt <float>`, `--modality <text\|image\|file\|video\|audio>`, `--tools`, `--structured-outputs`, `--open-weights`, `--free-only`, `--include-batch`, `--include-aliases`, and `--limit <int>`. Excludes batch and alias SKUs by default. |
| **FR-05** | `simulate` | Accepts `--input-tokens <int>`, `--output-tokens <int>`, `--calls-per-day <int>`, optional `--cache-hit-rate <float 0.0-1.0>` (default `0.0`), `--tools`, `--min-intelligence <float>`, and `--limit <int>`. Filters out models where `provider_context_length < (input + output)` or `max_completion_tokens < output`. Computes daily and 30-day USD spend using base prompt price and `cache_read_price_per_m` (falling back to base prompt price when cache price is `NULL`). |
| **FR-06** | `rank` | Ranks paid models by capability-to-cost efficiency. Supports `--metric <intelligence\|coding\|agentic\|context>` (default `intelligence`). Computes `score / blended_price_per_m` where `blended_price_per_m = (prompt_price_per_m * 0.75) + (completion_price_per_m * 0.25)` (standard 3:1 input-to-output agentic token ratio). |
| **FR-07** | `--export` | Global/subcommand option `--export <filepath>` (supports `.md` and `.csv` extensions) on `list`, `simulate`, and `rank` to write query results cleanly to disk. |

---

## 5. Non-Functional Requirements (NFR)

1. **NFR-01 (Network Resilience):** HTTP requests must use a 10-second timeout (`timeout=10`), check `response.raise_for_status()`, and catch `requests.RequestException` to print a clean user-facing error message with exit code `1` rather than a raw traceback.
2. **NFR-02 (Database Safety):** All SQLite queries must use parameterized placeholders (`?` or `:name`). Connections must use context managers and enforce `PRAGMA foreign_keys = ON;`.
3. **NFR-03 (Offline Execution):** `stats`, `list`, `simulate`, and `rank` must never make network calls. If the database is empty, prompt the user to run `model-bench sync` first.
4. **NFR-04 (Packaging & Portability):** Must be configured via `pyproject.toml` inside a Python virtual environment (`venv`) and expose the `model-bench` entry point.

---

## 6. CLI User Interface Contract

```bash
# 1. Synchronize local SQLite database with live OpenRouter catalog
model-bench sync

# 2. View market KPI overview & distributions
model-bench stats

# 3. Find open-weight models supporting tool-calling and image input
model-bench list --open-weights --tools --modality image --limit 15

# 4. Simulate an agent workflow (10k input, 1.5k output, 500 calls/day, 60% prompt cache hit rate)
model-bench simulate --input-tokens 10000 --output-tokens 1500 --calls-per-day 500 --cache-hit-rate 0.6 --tools --min-intelligence 40.0

# 5. Rank top models by Agentic Index per Dollar and export to Markdown
model-bench rank --metric agentic --limit 20 --export ./reports/agentic_value_ranking.md
```