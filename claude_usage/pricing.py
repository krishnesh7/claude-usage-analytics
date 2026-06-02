"""Imputed-cost computation from token counts using a static price table.

The prices.json file is hand-maintained at ~/.claude/usage/prices.json. Prices
are USD per 1M tokens. We treat all cache_creation_tokens as 5-minute ephemeral
unless we can later distinguish 1h (the JSONL includes a sub-breakdown but the
SQLite schema collapses them). This slightly under-bills 1h cache writes; the
parser could be extended to split them later if precision matters.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

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
    cc_5m = cc_total - cc_1h
    return Cost(
        input_usd=(row.get("input_tokens", 0) or 0) * p.get("input", 0) / M,
        output_usd=(row.get("output_tokens", 0) or 0) * p.get("output", 0) / M,
        cache_write_usd=(cc_5m * p.get("cache_write_5m", 0) + cc_1h * p.get("cache_write_1h", 0)) / M,
        cache_read_usd=(row.get("cache_read_tokens", 0) or 0) * p.get("cache_read", 0) / M,
    )


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
