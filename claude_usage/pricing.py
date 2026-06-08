"""Imputed-cost computation from token counts using a static price table.

The prices.json file is hand-maintained at ~/.claude/usage/prices.json. Prices
are USD per 1M tokens. Cache creation tokens are split into 1h and 5m ephemeral
tiers using cache_creation_1h_tokens (stored by the parser from the JSONL
sub-breakdown). Rows without that field (older DB entries) fall back to 5m pricing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .paths import PRICES_PATH


@dataclass
class Cost:
    input_usd: float
    output_usd: float
    cache_write_usd: float
    cache_read_usd: float

    @property
    def total_usd(self) -> float:
        return self.input_usd + self.output_usd + self.cache_write_usd + self.cache_read_usd


def load_prices() -> dict:
    with open(PRICES_PATH) as f:
        data = json.load(f)
    return data.get("models", {})


def price_for(model: str | None, prices: dict) -> dict:
    if not model:
        return prices.get("unknown", {})
    if model in prices:
        return prices[model]
    # Try family alias match: e.g. claude-haiku-4-5-20251001 -> claude-haiku-4-5
    if model.count("-") >= 3:
        family = "-".join(model.split("-")[:4])
        if family in prices:
            return prices[family]
    return prices.get("unknown", {})


def impute_cost(row: dict, prices: dict) -> Cost:
    """row has keys: model, input_tokens, cache_creation_tokens, cache_creation_1h_tokens,
    cache_read_tokens, output_tokens.

    cache_creation_tokens is the total; cache_creation_1h_tokens is the 1h subset.
    The remainder (total - 1h) is 5m ephemeral.
    """
    p = price_for(row.get("model"), prices)
    M = 1_000_000.0
    cc_total = row.get("cache_creation_tokens", 0) or 0
    cc_1h = row.get("cache_creation_1h_tokens", 0) or 0
    cc_5m = max(0, cc_total - cc_1h)
    return Cost(
        input_usd=(row.get("input_tokens", 0) or 0) * p.get("input", 0) / M,
        output_usd=(row.get("output_tokens", 0) or 0) * p.get("output", 0) / M,
        cache_write_usd=(cc_5m * p.get("cache_write_5m", 0) + cc_1h * p.get("cache_write_1h", 0)) / M,
        cache_read_usd=(row.get("cache_read_tokens", 0) or 0) * p.get("cache_read", 0) / M,
    )


COST_MODES: dict[str, dict[str, float]] = {
    "api":          {"cache_write": 1.00, "cache_read": 1.00},
    "conservative": {"cache_write": 0.15, "cache_read": 0.05},
    "subscription": {"cache_write": 0.08, "cache_read": 0.01},
}


def impute_cost_all_modes(row: dict, prices: dict) -> dict[str, Cost]:
    """Return Cost for all 3 modes from one token row.

    Input/output tokens are always at full API rate. Only cache tokens are
    discounted — by the per-mode multipliers in COST_MODES.
    """
    p = price_for(row.get("model"), prices)
    M = 1_000_000.0
    cc_total = row.get("cache_creation_tokens", 0) or 0
    cc_1h = row.get("cache_creation_1h_tokens", 0) or 0
    cc_5m = max(0, cc_total - cc_1h)
    input_usd = (row.get("input_tokens", 0) or 0) * p.get("input", 0) / M
    output_usd = (row.get("output_tokens", 0) or 0) * p.get("output", 0) / M
    cr_tokens = row.get("cache_read_tokens", 0) or 0

    result: dict[str, Cost] = {}
    for mode, mults in COST_MODES.items():
        cw = mults["cache_write"]
        cr_m = mults["cache_read"]
        result[mode] = Cost(
            input_usd=input_usd,
            output_usd=output_usd,
            cache_write_usd=(cc_5m * p.get("cache_write_5m", 0) * cw
                             + cc_1h * p.get("cache_write_1h", 0) * cw) / M,
            cache_read_usd=cr_tokens * p.get("cache_read", 0) * cr_m / M,
        )
    return result


def total_cost_all_modes(per_model_rows: list[dict], prices: dict | None = None) -> dict[str, Cost]:
    """Sum impute_cost_all_modes across a list of per-model rows."""
    if prices is None:
        prices = load_prices()
    acc = {mode: Cost(0.0, 0.0, 0.0, 0.0) for mode in COST_MODES}
    for r in per_model_rows:
        costs = impute_cost_all_modes(r, prices)
        for mode in COST_MODES:
            c = costs[mode]
            acc[mode] = Cost(
                input_usd=acc[mode].input_usd + c.input_usd,
                output_usd=acc[mode].output_usd + c.output_usd,
                cache_write_usd=acc[mode].cache_write_usd + c.cache_write_usd,
                cache_read_usd=acc[mode].cache_read_usd + c.cache_read_usd,
            )
    return acc


_LITELLM_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
_CACHE_TTL_DAYS = 7
_FETCH_TIMEOUT_S = 5


def _fetch_litellm_prices() -> dict:
    """Fetch the raw LiteLLM pricing JSON via stdlib urllib (no extra deps)."""
    import urllib.request
    req = urllib.request.Request(
        _LITELLM_URL,
        headers={"User-Agent": "claude-usage-analytics/1.0"},
    )
    with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _map_litellm_to_schema(raw: dict) -> dict:
    """Filter to anthropic entries and convert cost-per-token to USD-per-million.

    Models missing any required cost field are skipped entirely. The 1h cache
    write tier is derived as cache_write_5m * 1.6 (fixed Anthropic ratio).
    """
    required = [
        "input_cost_per_token",
        "output_cost_per_token",
        "cache_creation_input_token_cost",
        "cache_read_input_token_cost",
    ]
    result: dict = {}
    for name, info in raw.items():
        if info.get("litellm_provider") != "anthropic":
            continue
        if not all(k in info and info[k] is not None for k in required):
            continue
        cw5m = info["cache_creation_input_token_cost"] * 1_000_000
        result[name] = {
            "input": info["input_cost_per_token"] * 1_000_000,
            "output": info["output_cost_per_token"] * 1_000_000,
            "cache_write_5m": cw5m,
            "cache_write_1h": round(cw5m * 1.6, 6),
            "cache_read": info["cache_read_input_token_cost"] * 1_000_000,
        }
    return result


def _write_prices_json(path: Path, new_models: dict) -> tuple[int, str]:
    """Merge new_models into path, preserving the 'unknown' fallback entry.

    Returns (model_count, last_fetched_iso). model_count excludes 'unknown'.
    """
    existing: dict = {}
    if path.exists():
        try:
            with open(path) as f:
                existing = json.load(f)
        except Exception:
            pass

    models = dict(new_models)
    unknown = (existing.get("models") or {}).get("unknown")
    if unknown:
        models["unknown"] = unknown

    last_fetched = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    data = {
        "_last_fetched": last_fetched,
        "_last_updated": existing.get("_last_updated", last_fetched[:10]),
        "models": models,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return len(new_models), last_fetched


def refresh_prices(path: Path | None = None) -> tuple[int, str]:
    """Force-fetch from LiteLLM and write to path (default: PRICES_PATH).

    Returns (model_count, last_fetched_iso). Raises on any failure.
    """
    target = path if path is not None else PRICES_PATH
    raw = _fetch_litellm_prices()
    new_models = _map_litellm_to_schema(raw)
    return _write_prices_json(target, new_models)


def ensure_prices(path: Path | None = None) -> None:
    """Refresh if PRICES_PATH is missing or older than _CACHE_TTL_DAYS. Silent on error."""
    target = path if path is not None else PRICES_PATH
    needs_fetch = True
    if target.exists():
        try:
            with open(target) as f:
                data = json.load(f)
            last = data.get("_last_fetched")
            if last:
                age = datetime.now(timezone.utc) - datetime.fromisoformat(last)
                needs_fetch = age.days >= _CACHE_TTL_DAYS
        except Exception:
            pass
    if needs_fetch:
        try:
            refresh_prices(path=target)
        except Exception:
            pass


def get_prices_meta(path: Path | None = None) -> dict:
    """Return {last_fetched, model_count} from prices.json without triggering a fetch."""
    target = path if path is not None else PRICES_PATH
    try:
        with open(target) as f:
            data = json.load(f)
        models = data.get("models", {})
        return {
            "last_fetched": data.get("_last_fetched"),
            "model_count": sum(1 for k in models if k != "unknown"),
        }
    except Exception:
        return {"last_fetched": None, "model_count": 0}


def total_cost(per_model_rows: list[dict], prices: dict | None = None) -> Cost:
    """Sum imputed cost across rows that each carry a 'model' field plus token columns."""
    if prices is None:
        prices = load_prices()
    agg = Cost(0.0, 0.0, 0.0, 0.0)
    for r in per_model_rows:
        c = impute_cost(r, prices)
        agg = Cost(
            input_usd=agg.input_usd + c.input_usd,
            output_usd=agg.output_usd + c.output_usd,
            cache_write_usd=agg.cache_write_usd + c.cache_write_usd,
            cache_read_usd=agg.cache_read_usd + c.cache_read_usd,
        )
    return agg


def cost_dict(c: Cost) -> dict:
    return {
        "input_usd": round(c.input_usd, 4),
        "output_usd": round(c.output_usd, 4),
        "cache_write_usd": round(c.cache_write_usd, 4),
        "cache_read_usd": round(c.cache_read_usd, 4),
        "total_usd": round(c.total_usd, 4),
    }
