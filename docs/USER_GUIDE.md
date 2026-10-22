# User Guide — `model-bench`

This guide walks you through every command and option available in `model-bench`. If you can run `model-bench --help`, you already have everything you need — this document just explains each part in plain language.

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Global Options](#2-global-options)
3. [sync — Fetch Model Data](#3-sync--fetch-model-data)
4. [stats — Market Overview](#4-stats--market-overview)
5. [list — Browse & Filter Models](#5-list--browse--filter-models)
6. [simulate — Estimate Costs](#6-simulate--estimate-costs)
7. [rank — Find Best Value Models](#7-rank--find-best-value-models)
8. [Exporting Results](#8-exporting-results)
9. [Configuration](#9-configuration)
10. [Tips & Recipes](#10-tips--recipes)

---

## 1. Getting Started

Before you can browse or analyze models, you need to fetch the data once:

```bash
model-bench sync
```

This downloads the full model catalog from OpenRouter (no account or API key needed) and stores it in a local SQLite database on your machine. After this, every other command works **entirely offline**.

If you try to run any analysis command before syncing, you'll see:

```
⚠ Database is empty. Run model-bench sync first to fetch the model catalog.
```

Just run `sync` and you're good to go.

---

## 2. Global Options

These work with the base `model-bench` command:

| Option | What it does |
|---|---|
| `--help` or `-h` | Shows a summary of all available commands |
| `--version` | Prints the installed version number |

```bash
model-bench --help       # See all commands
model-bench --version    # e.g. "model-bench 0.1.0"
```

---

## 3. `sync` — Fetch Model Data

```bash
model-bench sync
```

**What it does:** Connects to the OpenRouter API, downloads the full catalog of models (460+), normalizes the data, and saves it to your local database.

**When to run it:** Whenever you want fresh data. Run it daily, weekly, or whenever you suspect models or prices have changed.

**What you'll see:**

```
╭────────────────────────── ✓ Sync Complete ───────────────────────────╮
│   Models Synced           468                                        │
│   New Models Added        12                                         │
│   Price Changes Logged    3                                          │
╰──────────────────────────────────────────────────────────────────────╯
```

- **Models Synced** — total number of models processed
- **New Models Added** — models that didn't exist in your database before
- **Price Changes Logged** — models whose pricing changed since your last sync (tracked in a history table for auditing)

**This is the only command that requires internet access.** Everything else works offline.

---

## 4. `stats` — Market Overview

```bash
model-bench stats
```

**What it does:** Shows you a bird's-eye view of the entire model market using the data from your last sync.

**What you'll see:**

- **Market Overview** — total models, free vs. paid counts, number of providers, how many models have benchmark scores
- **Context Window Distribution** — a bar chart showing how many models fall into each context window bucket (≤32K, 32K–128K, 128K–256K, 256K–1M, >1M)
- **Top 10 Providers** — the providers with the most models (e.g., OpenAI, Google, Anthropic)
- **Input Modality Support** — how many models accept text, images, files, video, or audio

No options or flags — just run it and read the dashboard.

---

## 5. `list` — Browse & Filter Models

```bash
model-bench list [OPTIONS]
```

**What it does:** Queries your local database and shows a filtered table of models. By default it excludes batch variants and alias redirects, showing you only "real" model SKUs.

### All Available Filters

| Option | What it does | Example |
|---|---|---|
| `--provider NAME` | Show only models from a specific provider | `--provider openai` |
| `--min-context N` | Only models with at least N tokens of context | `--min-context 128000` |
| `--max-prompt PRICE` | Only models where the prompt price per 1M tokens is at most this much | `--max-prompt 5.0` |
| `--modality TYPE` | Only models that accept this input type. Choices: `text`, `image`, `file`, `video`, `audio` | `--modality image` |
| `--tools` | Only models that support tool calling (function calling) | `--tools` |
| `--structured-outputs` | Only models that support structured/JSON output mode | `--structured-outputs` |
| `--open-weights` | Only open-weight models (those with a Hugging Face model ID) | `--open-weights` |
| `--free-only` | Only models that are completely free to use | `--free-only` |
| `--include-batch` | Also show `:batch` variant SKUs (async/cheaper versions). __Hidden by default.__ | `--include-batch` |
| `--include-aliases` | Also show `~` alias/redirect SKUs. __Hidden by default.__ | `--include-aliases` |
| `--sort ORDER` | Sort order for results. Choices: `iq` (default), `price`, `context`, `newest`, `code`, `agentic` | `--sort iq` |
| `--limit N` | Maximum number of results to show (default: 25) | `--limit 50` |
| `--export PATH` | Save the results to a file (see [Exporting Results](#8-exporting-results)) | `--export results.csv` |

### Examples

```bash
# Show all OpenAI models
model-bench list --provider openai

# Find open-weight models that support tool calling and image input
model-bench list --open-weights --tools --modality image --limit 15

# Find the cheapest models with at least 128K context
model-bench list --min-context 128000 --max-prompt 2.0

# Show all free models
model-bench list --free-only

# Find models that support both tools and structured outputs
model-bench list --tools --structured-outputs --limit 10
```

You can combine any number of filters — they all stack (AND logic).

---

## 6. `simulate` — Estimate Costs

```bash
model-bench simulate --input-tokens N --output-tokens N --calls-per-day N [OPTIONS]
```

**What it does:** Given a workload profile (how many tokens per call, how many calls per day), it calculates the estimated **daily** and **30-day** USD cost for every qualifying model, sorted cheapest first.

### Required Arguments

| Argument | What it means | Example |
|---|---|---|
| `--input-tokens N` | How many input (prompt) tokens per API call | `--input-tokens 10000` |
| `--output-tokens N` | How many output (completion) tokens per API call | `--output-tokens 1500` |
| `--calls-per-day N` | How many API calls you make per day | `--calls-per-day 500` |

### Optional Arguments

| Option | What it does | Default |
|---|---|---|
| `--cache-hit-rate RATE` | What fraction of your input tokens are served from prompt cache (0.0 = no caching, 1.0 = all cached). Models with a cache price will use it; models without one fall back to the full prompt price. | `0.0` |
| `--tools` | Only include models that support tool/function calling | Off |
| `--min-intelligence SCORE` | Only include models with at least this intelligence index score | No minimum |
| `--include-batch` | Also consider `:batch` variant SKUs (often 50% cheaper but async) | Off |
| `--include-free` | Include $0.00 free-tier models in the results. Excluded by default since simulating cost on rate-limited free endpoints is rarely useful. | Off |
| `--limit N` | Maximum number of results (default: 20) | `20` |
| `--export PATH` | Save the results to a file | — |

### How the Cost is Calculated

For each API call:
1. **Input cost** = your input tokens × blended price, where:
   - Uncached portion (`1 - cache_hit_rate`) uses the regular prompt price
   - Cached portion (`cache_hit_rate`) uses the cache read price (or falls back to prompt price if the model has no cache pricing)
2. **Output cost** = your output tokens × completion price
3. **Daily cost** = (input cost + output cost) × calls per day
4. **Monthly cost** = daily cost × 30

Models are automatically **excluded** if:
- Their context window is too small to fit your input + output tokens
- Their max completion token limit is smaller than your output tokens

### Examples

```bash
# Basic simulation: 10K input, 1.5K output, 500 calls/day
model-bench simulate --input-tokens 10000 --output-tokens 1500 --calls-per-day 500

# With 60% prompt cache hit rate (saves money on repeated prompts)
model-bench simulate --input-tokens 10000 --output-tokens 1500 --calls-per-day 500 \
  --cache-hit-rate 0.6

# Only tool-capable models with IQ ≥ 40
model-bench simulate --input-tokens 10000 --output-tokens 1500 --calls-per-day 500 \
  --tools --min-intelligence 40.0

# Include batch variants for cheaper async pricing
model-bench simulate --input-tokens 5000 --output-tokens 2000 --calls-per-day 1000 \
  --include-batch --limit 30
```

---

## 7. `rank` — Find Best Value Models

```bash
model-bench rank [OPTIONS]
```

**What it does:** Ranks paid models by how much capability you get per dollar. It computes a "value score" = benchmark score ÷ blended price, so models that are both cheap and capable rank highest.

### How the Value Score Works

- **Blended price** = `(prompt price × 0.75) + (completion price × 0.25)` — this reflects a typical agentic workload where input tokens outnumber output tokens roughly 3:1.
- **Value score** = your chosen metric ÷ blended price — higher is better.

### Options

| Option | What it does | Default |
|---|---|---|
| `--metric METRIC` | Which benchmark to rank by. Choices: `intelligence`, `coding`, `agentic`, `context` | `intelligence` |
| `--limit N` | Maximum number of results | `20` |
| `--export PATH` | Save the results to a file | — |

### Metric Choices Explained

| Metric | What it measures |
|---|---|
| `intelligence` | General intelligence index (broad reasoning, knowledge, comprehension) |
| `coding` | Coding benchmark score (code generation, debugging, understanding) |
| `agentic` | Agentic task performance (multi-step tool use, planning, execution) |
| `context` | Context window size (ranks by tokens-per-dollar — useful for RAG workloads) |

### Examples

```bash
# Best intelligence per dollar (default)
model-bench rank

# Best coding value
model-bench rank --metric coding --limit 15

# Best agentic value, exported to markdown
model-bench rank --metric agentic --limit 20 --export ./reports/agentic_ranking.md

# Most context window per dollar (great for RAG/retrieval)
model-bench rank --metric context --limit 10
```

---

## 8. Exporting Results

The `list`, `simulate`, and `rank` commands all support `--export` to save results to a file.

### Supported Formats

| Extension | Format |
|---|---|
| `.md` | Markdown table — great for GitHub, Notion, documentation |
| `.csv` | Comma-separated values — great for Excel, Google Sheets, further analysis |

### Usage

```bash
# Export to Markdown
model-bench list --tools --export ./reports/tool_models.md

# Export to CSV
model-bench simulate --input-tokens 5000 --output-tokens 1000 --calls-per-day 200 \
  --export ./data/cost_analysis.csv

# Export ranking to Markdown
model-bench rank --metric agentic --export ./reports/agentic_value.md
```

The tool will create any missing parent directories automatically. You'll see a confirmation message:

```
✓ Exported 20 rows to ./reports/agentic_value.md
```

---

## 9. Configuration

### Database Location

By default, `model-bench` stores its SQLite database at:

```
~/.local/share/model-bench/models.db
```

You can override this by setting the `MODEL_BENCH_DB_PATH` environment variable:

```bash
# Use a custom database location
export MODEL_BENCH_DB_PATH=~/my-data/models.db
model-bench sync
```

### No API Keys Needed

`model-bench` uses the **public, unauthenticated** OpenRouter catalog endpoint. No account, no API key, no configuration file. Just install and sync.

---

## 10. Tips & Recipes

### Keep your data fresh
```bash
# Add to your crontab or run weekly
model-bench sync
```

### Find the cheapest model for a specific job
```bash
# Cheapest model that can handle 256K context with tool calling
model-bench list --min-context 256000 --tools --limit 5
```

### Compare cost across caching strategies
```bash
# Without caching
model-bench simulate --input-tokens 20000 --output-tokens 2000 --calls-per-day 1000

# With 80% cache hits
model-bench simulate --input-tokens 20000 --output-tokens 2000 --calls-per-day 1000 \
  --cache-hit-rate 0.8
```

### Export for team review
```bash
# Generate a markdown report for your team
model-bench rank --metric agentic --limit 30 --export ./reports/monthly_model_review.md
```

### Quick "what's the market like?" check
```bash
model-bench stats
```

---

## Getting Help

Every command supports `--help` or `-h`:

```bash
model-bench --help           # Overview of all commands
model-bench list --help      # All options for the list command
model-bench simulate -h      # All options for simulate
model-bench rank -h          # All options for rank
```
