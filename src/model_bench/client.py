"""HTTP client & JSON record normalizer for the OpenRouter API.

Responsibilities:
- Fetches raw JSON from GET https://openrouter.ai/api/v1/models
- Sanitizes edge cases (~aliases, :batch, empty strings, -1 prices)
- Normalizes token pricing from per-token strings to USD per 1M tokens
"""

from __future__ import annotations

from typing import Any

import requests

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/models"
HTTP_TIMEOUT_SECONDS = 10


def fetch_models() -> list[dict[str, Any]]:
    """Fetch the live model catalog from OpenRouter.

    Returns:
        A list of raw model dictionaries from the API ``data`` array.

    Raises:
        SystemExit: On any network/HTTP error (NFR-01).
    """
    try:
        response = requests.get(OPENROUTER_API_URL, timeout=HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SystemExit(
            f"[error] Failed to fetch models from OpenRouter: {exc}"
        ) from exc

    payload = response.json()
    return payload.get("data", [])


def normalize_record(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a single raw OpenRouter model record.

    Applies all sanitization rules from SRS Section 3.2 and the
    Architecture field-mapping specification.

    Args:
        raw: A single model dictionary from the API response.

    Returns:
        A normalized dict ready for SQLite upsert, or ``None`` if the
        record is missing a required ``id`` field and should be skipped.
    """
    model_id = raw.get("id")
    if not model_id:
        return None

    # --- Provider extraction (strip ~ prefix) ---
    provider = model_id.split("/")[0].lstrip("~")

    # --- Name fallback ---
    name = raw.get("name") or model_id

    # --- Timestamps ---
    created_at = raw.get("created")

    # --- Context lengths ---
    context_length = raw.get("context_length") or 0
    top_provider = raw.get("top_provider") or {}
    provider_context_length = top_provider.get("context_length")
    if provider_context_length is None:
        provider_context_length = context_length

    # --- Max completion tokens ---
    max_completion_tokens = top_provider.get("max_completion_tokens")

    # --- Architecture / modality ---
    architecture = raw.get("architecture") or {}
    modality = architecture.get("modality") or "unknown"

    input_modalities_raw = architecture.get("input_modalities") or ["text"]
    input_modalities = ",".join(sorted(input_modalities_raw))

    output_modalities_raw = architecture.get("output_modalities") or ["text"]
    output_modalities = ",".join(sorted(output_modalities_raw))

    tokenizer = architecture.get("tokenizer")

    # --- Hugging Face ID: empty string -> None ---
    hf_id = raw.get("hugging_face_id")
    if isinstance(hf_id, str):
        hf_id = hf_id.strip() or None

    # --- Pricing normalization: per-token string -> USD per 1M tokens ---
    pricing = raw.get("pricing") or {}
    prompt_price_per_m = _price_to_per_million(pricing.get("prompt"))
    completion_price_per_m = _price_to_per_million(pricing.get("completion"))
    cache_read_raw = pricing.get("input_cache_read")
    cache_read_price_per_m = (
        _price_to_per_million(cache_read_raw) if cache_read_raw is not None else None
    )

    # --- Benchmarks (sparse/nullable) ---
    benchmarks = raw.get("benchmarks") or {}
    aa = benchmarks.get("artificial_analysis") or {}
    intelligence_index = _safe_float(aa.get("intelligence_index"))
    coding_index = _safe_float(aa.get("coding_index"))
    agentic_index = _safe_float(aa.get("agentic_index"))

    # --- Supported parameters / capabilities ---
    supported_params = raw.get("supported_parameters") or []
    supports_tools = 1 if "tools" in supported_params else 0
    supports_structured_outputs = 1 if "structured_outputs" in supported_params else 0

    # --- Reasoning ---
    reasoning = raw.get("reasoning") or {}
    mandatory_reasoning = 1 if reasoning.get("mandatory") is True else 0

    # --- Derived flags ---
    is_free = 1 if (
        (prompt_price_per_m == 0 and completion_price_per_m == 0)
        or model_id.endswith(":free")
    ) else 0
    is_batch = 1 if model_id.endswith(":batch") else 0
    is_alias = 1 if (model_id.startswith("~") or "alias_target" in raw) else 0

    # --- Canonical slug ---
    canonical_slug = raw.get("canonical_slug")

    return {
        "id": model_id,
        "canonical_slug": canonical_slug,
        "provider": provider,
        "name": name,
        "created_at": created_at,
        "context_length": context_length,
        "provider_context_length": provider_context_length,
        "max_completion_tokens": max_completion_tokens,
        "modality": modality,
        "input_modalities": input_modalities,
        "output_modalities": output_modalities,
        "tokenizer": tokenizer,
        "hugging_face_id": hf_id,
        "prompt_price_per_m": prompt_price_per_m,
        "completion_price_per_m": completion_price_per_m,
        "cache_read_price_per_m": cache_read_price_per_m,
        "intelligence_index": intelligence_index,
        "coding_index": coding_index,
        "agentic_index": agentic_index,
        "supports_tools": supports_tools,
        "supports_structured_outputs": supports_structured_outputs,
        "mandatory_reasoning": mandatory_reasoning,
        "is_free": is_free,
        "is_batch": is_batch,
        "is_alias": is_alias,
    }


# ── Helpers ────────────────────────────────────────────────────────────


def _price_to_per_million(value: str | None) -> float:
    """Convert a per-token price string to USD per 1 Million tokens."""
    if value is None:
        return 0.0
    return round(float(value) * 1_000_000, 6)


def _safe_float(value: Any) -> float | None:
    """Return a float if the value is numeric, otherwise None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
