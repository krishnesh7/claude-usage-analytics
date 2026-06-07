# Cost Mode Toggle + Dynamic Pricing from LiteLLM

**Date:** 2026-06-07
**Status:** Approved

## Problem

Two related gaps in the current dashboard:

1. **Single cost frame** — every cost number is shown at full API rates. Claude Code subscription users pay 5–10× less in practice (cache tokens are heavily discounted). The number on screen doesn't match their bill.

2. **Stale pricing** — `prices.json` is hand-maintained. When Anthropic ships a new model, costs for that model silently fall back to the `unknown` entry (Sonnet rates) until someone manually updates the file.

## Goals

- Add a **cost mode toggle** (API / Conservative / Subscription) to the filter bar so users can switch between frames without refetching data.
- Add **automatic pricing updates** from LiteLLM's community-maintained model pricing DB, cached locally in `prices.json` and refreshed weekly.

## Out of Scope

- Session-level cost mode display (sessions table already shows cost; mode toggle applies there too, no separate work needed).
- Storing historical costs at a specific mode — costs are always computed from raw token counts × current prices × mode multiplier.

---

## Architecture

Five files change. No new dependencies (stdlib `urllib` for the fetch).

```
pricing.py       ← COST_MODES multipliers, impute_cost_all_modes(), LiteLLM fetch+map
db.py            ← aggregate all 3 mode costs in totals queries
serve.py         ← return cost_api/conservative/subscription per row; /api/prices/refresh
dashboard.html   ← cost mode toggle in filter bar; renderCosts(mode) swaps displayed values
data/prices.json ← LiteLLM-fetched data written here on refresh
```

`config/prices.json` in the repo stays as the seed file (used if `data/prices.json` is absent). `PRICES_PATH` in `paths.py` already resolves to the working copy under `USAGE_DIR`.

---

## Dynamic Pricing

### Fetch flow

On server startup, `pricing.py` checks `PRICES_PATH` for a `_last_fetched` ISO timestamp. If missing or older than 7 days, it fetches LiteLLM's raw pricing DB:

```
https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json
```

Filters to entries where `litellm_provider == "anthropic"`. Maps to our schema (see below). Writes result to `PRICES_PATH` with `_last_fetched` set to now.

If the fetch fails (no network, timeout >5s, bad JSON), falls back silently to whatever is already in `PRICES_PATH`. No startup error is raised.

### LiteLLM → our schema mapping

LiteLLM stores cost-per-token; we store USD-per-million-tokens. LiteLLM has one cache write price; we have two (5m and 1h tiers). The 1h tier is always 1.6× the 5m tier — a fixed Anthropic ratio.

| LiteLLM field | Our field | Transform |
|---|---|---|
| `input_cost_per_token` | `input` | × 1,000,000 |
| `output_cost_per_token` | `output` | × 1,000,000 |
| `cache_creation_input_token_cost` | `cache_write_5m` | × 1,000,000 |
| derived | `cache_write_1h` | `cache_write_5m × 1.6` |
| `cache_read_input_token_cost` | `cache_read` | × 1,000,000 |

Models missing any of these fields are skipped. The `unknown` fallback entry is preserved from the existing file and never overwritten by the fetch.

### Manual refresh

`GET /api/prices/refresh` — forces an immediate fetch regardless of the staleness check. Returns:

```json
{
  "ok": true,
  "last_fetched": "2026-06-07T14:32:00Z",
  "model_count": 12
}
```

The dashboard footer shows "Prices updated: N days ago · [refresh]". Clicking it calls this endpoint and updates the footer text.

---

## Cost Modes

### Multipliers

Input and output tokens are always at full API rate. Only cache tokens are discounted:

```python
COST_MODES = {
    "api":          {"cache_write": 1.00, "cache_read": 1.00},
    "conservative": {"cache_write": 0.15, "cache_read": 0.05},
    "subscription": {"cache_write": 0.08, "cache_read": 0.01},
}
```

**API** — full published rates. Useful for comparing to raw API spend.  
**Conservative** — cache at 15%/5% of API rate. Upper bound for subscription users.  
**Subscription** — cache at 8%/1% of API rate. Approximates real Claude Code billing.

The multipliers apply to both `cache_write_5m` and `cache_write_1h` identically, so the 1h/5m accuracy advantage is preserved across all modes.

### `impute_cost_all_modes(row, prices) -> dict`

New function in `pricing.py`. Extracts token counts once from `row`, then loops over the 3 modes. Returns `{"api": Cost, "conservative": Cost, "subscription": Cost}`.

Existing `impute_cost(row, prices)` is unchanged. All existing call sites continue to work.

---

## API Response Shape

Every cost-bearing endpoint adds three fields alongside the existing `cost` field:

```json
{
  "cost": 0.42,
  "cost_api": 3.10,
  "cost_conservative": 0.89,
  "cost_subscription": 0.42
}
```

`cost` stays equal to the subscription value. No existing consumers break.

Affected endpoints: `/api/summary` (KPI total), `/api/sessions` (per-session rows — currently has no cost field; this adds one), `/api/attribution` (per-project rows). Stage and model tables are computed inside `/api/summary`.

---

## Dashboard UI

### Filter bar toggle

3-button toggle group added after the existing preset buttons:

```
API | Conservative | Subscription
```

Styled identically to the existing `preset-btn` class. Default active = **Subscription**. Selection saved to `localStorage` key `cu-cost-mode` and restored on page load.

A 1-line tooltip appears below the active button:
- API → "Full published API rates"
- Conservative → "Cache tokens at 15% of API rate"  
- Subscription → "Approximates Claude Code subscription billing"

### `renderCosts(mode)`

Client-side function called once after data loads and again on each toggle click. Reads `cost_api`, `cost_conservative`, or `cost_subscription` from the already-loaded data object and updates:

- KPI "total cost" card
- Project table cost column
- Model table cost column
- Stage table cost column
- Session table cost column (if visible)

No refetch. Mode switching is instant.

### Footer

```
Prices updated: 3 days ago · [refresh]
```

Clicking "refresh" calls `GET /api/prices/refresh` and updates the text. On failure, shows "refresh failed — using cached prices".

---

## Data Flow

```
Server startup
  └─ pricing.py: check _last_fetched in prices.json
       ├─ stale/missing → fetch LiteLLM DB → map → write prices.json
       └─ fresh → use existing prices.json

GET /api/summary (or /api/sessions, /api/attribution)
  └─ db.py: aggregate token counts per row
       └─ pricing.py: impute_cost_all_modes() → {api, conservative, subscription}
            └─ serve.py: return cost + cost_api + cost_conservative + cost_subscription

Browser: data loaded
  └─ read cu-cost-mode from localStorage (default: subscription)
       └─ renderCosts(mode) → fill cost cells from precomputed fields

User clicks toggle
  └─ save new mode to localStorage
       └─ renderCosts(mode) → re-fill cost cells (no fetch)
```

---

## Testing

- `test_pricing_modes.py` — `impute_cost_all_modes` returns correct values for each mode; subscription ≤ conservative ≤ api for all-positive token counts.
- `test_litellm_mapping.py` — mapping function produces valid schema from a fixture of LiteLLM JSON; `unknown` entry is preserved; models with missing fields are skipped.
- `test_prices_refresh.py` — refresh endpoint returns expected shape; fallback to cached prices on network failure.
- Existing `test_pricing_cache_split.py` continues to pass unchanged.
