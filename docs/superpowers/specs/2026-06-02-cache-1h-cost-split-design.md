# Cache 1h/5m Cost Split — Design Spec

**Date:** 2026-06-02  
**Status:** Approved

## Problem

`pricing.py` assumes all cache creation tokens are billed at the 5-minute ephemeral rate (`cache_write_5m`). In practice, Claude Code also uses the 1-hour cache tier (`cache_write_1h`), which costs ~60% more (e.g. $3.75 vs $6.00 per 1M tokens for Sonnet). The raw JSONL logs expose both tiers separately under `usage.cache_creation.ephemeral_1h_input_tokens` and `usage.cache_creation.ephemeral_5m_input_tokens`, but `parse.mjs` collapses them into a single `cache_creation_tokens` column, causing systematic underpricing of 1h cache writes.

## Goal

Store the 1h and 5m cache creation token counts separately so that `impute_cost()` can apply the correct rate to each tier.

## Approach

Minimal schema addition: add one new column `cache_creation_1h_tokens` to `turns`. The existing `cache_creation_tokens` column retains the total (unchanged for backward compatibility). The 5m count is derived at query time as `cache_creation_tokens - cache_creation_1h_tokens`.

This avoids touching any display code or the `Cost` dataclass shape — only the four cost-feeding DB queries and `impute_cost()` need updating.

## Changes

### 1. `parser/parse.mjs` — Schema & ingestion

Add column to `turns` table definition:
```sql
cache_creation_1h_tokens INTEGER DEFAULT 0
```

Add migration guard for existing DBs (runs once, silently ignored if column exists):
```sql
ALTER TABLE turns ADD COLUMN cache_creation_1h_tokens INTEGER DEFAULT 0
```

Update `upsertTurn` INSERT and ON CONFLICT SET to include the new column:
```js
cache_creation_1h_tokens: usage.cache_creation?.ephemeral_1h_input_tokens || 0
```

### 2. `claude_usage/db.py` — Read layer

Add `COALESCE(SUM(t.cache_creation_1h_tokens), 0) AS cache_creation_1h_tokens` to the SELECT of these four functions:
- `turns_by_model()`
- `turns_by_model_for_stage()`
- `turns_by_model_for_day()`
- `daily_cost_by_day()`

No changes needed to aggregation queries used for display counts (totals_by_stage, totals_by_project, etc.).

### 3. `claude_usage/pricing.py` — Cost computation

Update `impute_cost()`:
```python
cc_1h = row.get("cache_creation_1h_tokens", 0) or 0
cc_5m = (row.get("cache_creation_tokens", 0) or 0) - cc_1h
cache_write_usd = (cc_5m * p.get("cache_write_5m", 0) + cc_1h * p.get("cache_write_1h", 0)) / M
```

`Cost.cache_write_usd` stays as one combined field — no downstream changes.

### 4. `prices.json`

No changes needed — `cache_write_1h` rates already present for all models.

## Backward Compatibility

- Existing DB rows default `cache_creation_1h_tokens = 0`, so they fall back to all-5m pricing (same as before).
- Re-running the parser over historical JSONL will backfill the 1h counts correctly via the ON CONFLICT upsert.

## Testing

- Unit test: `impute_cost()` with a row where `cache_creation_1h_tokens > 0` produces higher `cache_write_usd` than all-5m.
- Unit test: rows with `cache_creation_1h_tokens = 0` produce identical results to pre-change behavior.
- Parser smoke test: a sample JSONL record with `ephemeral_1h_input_tokens` is stored correctly.
