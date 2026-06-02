import pytest
from claude_usage.pricing import impute_cost

PRICES = {
    "claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_write_5m": 3.75,
        "cache_write_1h": 6.0,
        "cache_read": 0.3,
    }
}


def test_all_5m_cache_unchanged():
    """Row with no 1h tokens produces same result as pre-change behavior."""
    row = {
        "model": "claude-sonnet-4-6",
        "input_tokens": 0,
        "cache_creation_tokens": 1_000_000,
        "cache_creation_1h_tokens": 0,
        "cache_read_tokens": 0,
        "output_tokens": 0,
    }
    cost = impute_cost(row, PRICES)
    assert cost.cache_write_usd == pytest.approx(3.75)


def test_all_1h_cache_costs_more():
    """Row where all cache creation is 1h should produce the 1h rate."""
    row_1h = {
        "model": "claude-sonnet-4-6",
        "input_tokens": 0,
        "cache_creation_tokens": 1_000_000,
        "cache_creation_1h_tokens": 1_000_000,
        "cache_read_tokens": 0,
        "output_tokens": 0,
    }
    row_5m = {
        "model": "claude-sonnet-4-6",
        "input_tokens": 0,
        "cache_creation_tokens": 1_000_000,
        "cache_creation_1h_tokens": 0,
        "cache_read_tokens": 0,
        "output_tokens": 0,
    }
    cost_1h = impute_cost(row_1h, PRICES)
    cost_5m = impute_cost(row_5m, PRICES)
    assert cost_1h.cache_write_usd == pytest.approx(6.0)
    assert cost_1h.cache_write_usd > cost_5m.cache_write_usd


def test_mixed_cache_tiers():
    """500k 1h + 500k 5m = blended cost."""
    row = {
        "model": "claude-sonnet-4-6",
        "input_tokens": 0,
        "cache_creation_tokens": 1_000_000,
        "cache_creation_1h_tokens": 500_000,
        "cache_read_tokens": 0,
        "output_tokens": 0,
    }
    cost = impute_cost(row, PRICES)
    # 500k * 3.75/M + 500k * 6.0/M = 1.875 + 3.0 = 4.875
    assert cost.cache_write_usd == pytest.approx(4.875)


def test_missing_1h_field_defaults_to_5m():
    """Old DB rows without cache_creation_1h_tokens key fall back to 5m pricing."""
    row = {
        "model": "claude-sonnet-4-6",
        "input_tokens": 0,
        "cache_creation_tokens": 1_000_000,
        "cache_read_tokens": 0,
        "output_tokens": 0,
    }
    cost = impute_cost(row, PRICES)
    assert cost.cache_write_usd == pytest.approx(3.75)
