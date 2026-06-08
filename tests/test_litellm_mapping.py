import json
import pytest
from pathlib import Path
from claude_usage.pricing import _map_litellm_to_schema, _write_prices_json, ensure_prices

LITELLM_FIXTURE = {
    "claude-3-5-sonnet-20241022": {
        "litellm_provider": "anthropic",
        "input_cost_per_token": 3e-6,
        "output_cost_per_token": 15e-6,
        "cache_creation_input_token_cost": 3.75e-6,
        "cache_read_input_token_cost": 0.3e-6,
    },
    "claude-3-opus-20240229": {
        "litellm_provider": "anthropic",
        "input_cost_per_token": 15e-6,
        "output_cost_per_token": 75e-6,
        # missing cache_creation_input_token_cost — must be skipped
        "cache_read_input_token_cost": 1.5e-6,
    },
    "gpt-4o": {
        "litellm_provider": "openai",
        "input_cost_per_token": 5e-6,
        "output_cost_per_token": 15e-6,
        "cache_creation_input_token_cost": 2.5e-6,
        "cache_read_input_token_cost": 1.25e-6,
    },
}

_UNKNOWN_ENTRY = {"input": 3.0, "output": 15.0, "cache_write_5m": 3.75, "cache_write_1h": 6.0, "cache_read": 0.3}


def test_map_basic_model():
    result = _map_litellm_to_schema(LITELLM_FIXTURE)
    assert "claude-3-5-sonnet-20241022" in result
    m = result["claude-3-5-sonnet-20241022"]
    assert m["input"] == pytest.approx(3.0)
    assert m["output"] == pytest.approx(15.0)
    assert m["cache_write_5m"] == pytest.approx(3.75)
    assert m["cache_write_1h"] == pytest.approx(3.75 * 1.6)
    assert m["cache_read"] == pytest.approx(0.3)


def test_map_skips_missing_cache_creation():
    result = _map_litellm_to_schema(LITELLM_FIXTURE)
    assert "claude-3-opus-20240229" not in result


def test_map_filters_non_anthropic():
    result = _map_litellm_to_schema(LITELLM_FIXTURE)
    assert "gpt-4o" not in result


def test_write_prices_preserves_unknown(tmp_path):
    p = tmp_path / "prices.json"
    p.write_text(json.dumps({"_last_updated": "2026-01-01",
                              "models": {"unknown": _UNKNOWN_ENTRY}}))
    new_models = {"claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0,
                   "cache_write_5m": 3.75, "cache_write_1h": 6.0, "cache_read": 0.3}}
    count, last_fetched = _write_prices_json(p, new_models)
    data = json.loads(p.read_text())
    assert "unknown" in data["models"]
    assert "claude-3-5-sonnet-20241022" in data["models"]
    assert "_last_fetched" in data
    assert count == 1  # excludes 'unknown'


def test_write_prices_sets_last_fetched(tmp_path):
    p = tmp_path / "prices.json"
    _, ts = _write_prices_json(p, {"m": {"input": 1.0, "output": 5.0,
                                         "cache_write_5m": 1.25, "cache_write_1h": 2.0,
                                         "cache_read": 0.1}})
    data = json.loads(p.read_text())
    assert data["_last_fetched"] == ts
    assert "T" in ts  # ISO timestamp with time component


def test_ensure_prices_fallback_on_error(tmp_path, monkeypatch):
    """ensure_prices must NOT raise and must leave the file unchanged on fetch failure."""
    from datetime import datetime, timezone
    stale_ts = "2020-01-01T00:00:00+00:00"
    p = tmp_path / "prices.json"
    seed = {"_last_fetched": stale_ts, "models": {"unknown": _UNKNOWN_ENTRY}}
    p.write_text(json.dumps(seed))

    import claude_usage.pricing as pm
    monkeypatch.setattr(pm, "_fetch_litellm_prices", lambda: (_ for _ in ()).throw(OSError("no net")))
    ensure_prices(path=p)  # must not raise
    assert json.loads(p.read_text())["models"] == seed["models"]  # file unchanged
