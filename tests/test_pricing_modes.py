import pytest
from claude_usage.pricing import impute_cost, impute_cost_all_modes, total_cost_all_modes

PRICES = {
    "claude-sonnet-4-6": {
        "input": 3.0, "output": 15.0,
        "cache_write_5m": 3.75, "cache_write_1h": 6.0, "cache_read": 0.3,
    }
}

ROW = {
    "model": "claude-sonnet-4-6",
    "input_tokens": 100_000,
    "cache_creation_tokens": 500_000,
    "cache_creation_1h_tokens": 200_000,
    "cache_read_tokens": 300_000,
    "output_tokens": 50_000,
}


def test_all_modes_ordering():
    """subscription ≤ conservative ≤ api for all-positive token counts."""
    costs = impute_cost_all_modes(ROW, PRICES)
    assert costs["subscription"].total_usd <= costs["conservative"].total_usd
    assert costs["conservative"].total_usd <= costs["api"].total_usd


def test_api_mode_matches_impute_cost():
    """API mode (1.0 multipliers) must equal the existing impute_cost()."""
    all_modes = impute_cost_all_modes(ROW, PRICES)
    single = impute_cost(ROW, PRICES)
    assert all_modes["api"].total_usd == pytest.approx(single.total_usd)


def test_subscription_cache_multipliers():
    """Subscription mode: cache_write at 8%, cache_read at 1% of API rate."""
    row = {
        "model": "claude-sonnet-4-6",
        "input_tokens": 0,
        "cache_creation_tokens": 1_000_000,
        "cache_creation_1h_tokens": 0,
        "cache_read_tokens": 1_000_000,
        "output_tokens": 0,
    }
    costs = impute_cost_all_modes(row, PRICES)
    # cache_write_5m: 3.75/M * 1M * 0.08 = 0.3
    assert costs["subscription"].cache_write_usd == pytest.approx(3.75 * 0.08)
    # cache_read: 0.3/M * 1M * 0.01 = 0.003
    assert costs["subscription"].cache_read_usd == pytest.approx(0.3 * 0.01)


def test_input_output_unchanged_across_modes():
    """Input and output tokens are NOT affected by cost mode multipliers."""
    costs = impute_cost_all_modes(ROW, PRICES)
    for mode in ("conservative", "subscription"):
        assert costs[mode].input_usd == pytest.approx(costs["api"].input_usd)
        assert costs[mode].output_usd == pytest.approx(costs["api"].output_usd)


def test_total_cost_all_modes_sums_rows():
    """total_cost_all_modes with two identical rows doubles each mode's cost."""
    costs_single = impute_cost_all_modes(ROW, PRICES)
    costs_total = total_cost_all_modes([ROW, ROW], PRICES)
    for mode in ("api", "conservative", "subscription"):
        assert costs_total[mode].total_usd == pytest.approx(2 * costs_single[mode].total_usd)
