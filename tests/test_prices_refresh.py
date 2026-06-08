import json
import pytest
from pathlib import Path
from claude_usage.pricing import refresh_prices, ensure_prices

_UNKNOWN = {"input": 3.0, "output": 15.0, "cache_write_5m": 3.75, "cache_write_1h": 6.0, "cache_read": 0.3}
_FIXTURE = {
    "claude-3-5-sonnet-20241022": {
        "litellm_provider": "anthropic",
        "input_cost_per_token": 3e-6,
        "output_cost_per_token": 15e-6,
        "cache_creation_input_token_cost": 3.75e-6,
        "cache_read_input_token_cost": 0.3e-6,
    }
}


def test_refresh_prices_returns_count_and_iso_timestamp(tmp_path, monkeypatch):
    """refresh_prices returns (model_count, iso_timestamp) on success."""
    import claude_usage.pricing as pm
    monkeypatch.setattr(pm, "_fetch_litellm_prices", lambda: _FIXTURE)
    p = tmp_path / "prices.json"
    p.write_text(json.dumps({"models": {"unknown": _UNKNOWN}}))

    count, last_fetched = refresh_prices(path=p)

    assert count == 1
    assert "T" in last_fetched
    data = json.loads(p.read_text())
    assert data["_last_fetched"] == last_fetched
    assert "claude-3-5-sonnet-20241022" in data["models"]
    assert "unknown" in data["models"]


def test_refresh_prices_raises_on_network_failure(tmp_path, monkeypatch):
    """refresh_prices propagates exceptions from _fetch_litellm_prices."""
    import claude_usage.pricing as pm
    monkeypatch.setattr(pm, "_fetch_litellm_prices", lambda: (_ for _ in ()).throw(OSError("timeout")))
    with pytest.raises(Exception):
        refresh_prices(path=tmp_path / "prices.json")


def test_ensure_prices_skips_when_fresh(tmp_path, monkeypatch):
    """ensure_prices does NOT fetch when _last_fetched is today."""
    from datetime import datetime, timezone
    p = tmp_path / "prices.json"
    p.write_text(json.dumps({
        "_last_fetched": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "models": {"unknown": _UNKNOWN},
    }))
    fetched = []
    import claude_usage.pricing as pm
    monkeypatch.setattr(pm, "_fetch_litellm_prices", lambda: fetched.append(1) or {})
    ensure_prices(path=p)
    assert fetched == []


def test_ensure_prices_fetches_when_stale(tmp_path, monkeypatch):
    """ensure_prices triggers a fetch when _last_fetched is > 7 days ago."""
    p = tmp_path / "prices.json"
    p.write_text(json.dumps({
        "_last_fetched": "2020-01-01T00:00:00+00:00",
        "models": {"unknown": _UNKNOWN},
    }))
    fetched = []
    import claude_usage.pricing as pm
    monkeypatch.setattr(pm, "_fetch_litellm_prices", lambda: fetched.append(1) or _FIXTURE)
    ensure_prices(path=p)
    assert fetched == [1]
