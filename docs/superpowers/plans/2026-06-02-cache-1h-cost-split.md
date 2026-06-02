# Cache 1h/5m Cost Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store 1-hour cache creation tokens separately from 5-minute tokens so `impute_cost()` applies the correct (higher) rate to each tier, producing accurate imputed costs.

**Architecture:** Add `cache_creation_1h_tokens` column to the `turns` table in the SQLite schema and parser. Thread it through the four DB query functions that feed the pricing layer. Update `impute_cost()` to split the cache creation cost into 1h and 5m components. `cache_creation_tokens` (total) stays unchanged for backward compatibility.

**Tech Stack:** Node.js (better-sqlite3) for parser, Python + SQLite for read layer and pricing, pytest for tests.

---

## Files

- Modify: `parser/parse.mjs` — schema DDL, migration guard, upsertTurn statement, ingestion call
- Modify: `tests/conftest.py` — add `cache_creation_1h_tokens` to test SCHEMA
- Modify: `claude_usage/db.py` — add column to `turns_by_model`, `turns_by_model_for_stage`, `turns_by_model_for_day`, `daily_cost_by_day`
- Modify: `claude_usage/pricing.py` — update `impute_cost()` to use per-tier rates
- Create: `tests/test_pricing_cache_split.py` — unit tests for the new cost calculation

---

### Task 1: Schema DDL + migration guard in parse.mjs

**Files:**
- Modify: `parser/parse.mjs`

- [ ] **Step 1: Add `cache_creation_1h_tokens` to the CREATE TABLE statement**

In `parser/parse.mjs`, find the `turns` table definition (around line 71). Add the new column after `cache_creation_tokens`:

```sql
CREATE TABLE IF NOT EXISTS turns (
  id INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL,
  request_id TEXT UNIQUE,
  ts TEXT,
  model TEXT,
  input_tokens INTEGER DEFAULT 0,
  cache_creation_tokens INTEGER DEFAULT 0,
  cache_creation_1h_tokens INTEGER DEFAULT 0,
  cache_read_tokens INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,
  service_tier TEXT
);
```

- [ ] **Step 2: Add migration guard for existing DBs**

After the `db.exec(DDL)` call that initialises the schema, add the following block to handle databases created before this column existed. better-sqlite3 throws when adding a column that already exists, so we catch and ignore that case:

```js
try {
  db.prepare('ALTER TABLE turns ADD COLUMN cache_creation_1h_tokens INTEGER DEFAULT 0').run()
} catch (_) { /* column already exists in this DB */ }
```

- [ ] **Step 3: Commit**

```bash
git add parser/parse.mjs
git commit -m "feat(parser): add cache_creation_1h_tokens column to turns schema"
```

---

### Task 2: Update upsertTurn statement and ingestion call in parse.mjs

**Files:**
- Modify: `parser/parse.mjs`

- [ ] **Step 1: Update the upsertTurn prepared statement**

Find the `upsertTurn` statement (around line 190). Replace it with:

```js
upsertTurn: db.prepare(`
  INSERT INTO turns (session_id, request_id, ts, model, input_tokens, cache_creation_tokens, cache_creation_1h_tokens, cache_read_tokens, output_tokens, service_tier)
  VALUES (@session_id, @request_id, @ts, @model, @input_tokens, @cache_creation_tokens, @cache_creation_1h_tokens, @cache_read_tokens, @output_tokens, @service_tier)
  ON CONFLICT(request_id) DO UPDATE SET
    output_tokens = MAX(turns.output_tokens, excluded.output_tokens),
    input_tokens = MAX(turns.input_tokens, excluded.input_tokens),
    cache_creation_tokens = MAX(turns.cache_creation_tokens, excluded.cache_creation_tokens),
    cache_creation_1h_tokens = MAX(turns.cache_creation_1h_tokens, excluded.cache_creation_1h_tokens),
    cache_read_tokens = MAX(turns.cache_read_tokens, excluded.cache_read_tokens),
    model = COALESCE(excluded.model, turns.model),
    service_tier = COALESCE(excluded.service_tier, turns.service_tier)
`),
```

- [ ] **Step 2: Update the ingestion call site**

Find the `stmt.upsertTurn.run({...})` call (around line 541). Add `cache_creation_1h_tokens` to the object:

```js
stmt.upsertTurn.run({
  session_id: info.sessionId,
  request_id: key,
  ts: ts || null,
  model: model,
  input_tokens: usage.input_tokens || 0,
  cache_creation_tokens: usage.cache_creation_input_tokens || 0,
  cache_creation_1h_tokens: usage.cache_creation?.ephemeral_1h_input_tokens || 0,
  cache_read_tokens: usage.cache_read_input_tokens || 0,
  output_tokens: usage.output_tokens || 0,
  service_tier: usage.service_tier || null,
})
```

- [ ] **Step 3: Commit**

```bash
git add parser/parse.mjs
git commit -m "feat(parser): extract ephemeral_1h cache tokens into cache_creation_1h_tokens"
```

---

### Task 3: Update test SCHEMA and four DB query functions

**Files:**
- Modify: `tests/conftest.py`
- Modify: `claude_usage/db.py`

- [ ] **Step 1: Update SCHEMA in conftest.py**

In `tests/conftest.py`, add `cache_creation_1h_tokens` to the `turns` table definition (after `cache_creation_tokens`):

```python
CREATE TABLE IF NOT EXISTS turns (
  id INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL,
  request_id TEXT UNIQUE,
  ts TEXT,
  model TEXT,
  input_tokens INTEGER DEFAULT 0,
  cache_creation_tokens INTEGER DEFAULT 0,
  cache_creation_1h_tokens INTEGER DEFAULT 0,
  cache_read_tokens INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,
  service_tier TEXT
);
```

- [ ] **Step 2: Update `turns_by_model` in db.py**

Find `turns_by_model` (around line 316). Add `cache_creation_1h_tokens` to its SELECT (after `cache_creation_tokens`):

```python
    sql = """
        SELECT
          COALESCE(t.model, 'unknown') AS model,
          COALESCE(SUM(t.input_tokens), 0) AS input_tokens,
          COALESCE(SUM(t.cache_creation_tokens), 0) AS cache_creation_tokens,
          COALESCE(SUM(t.cache_creation_1h_tokens), 0) AS cache_creation_1h_tokens,
          COALESCE(SUM(t.cache_read_tokens), 0) AS cache_read_tokens,
          COALESCE(SUM(t.output_tokens), 0) AS output_tokens,
          COUNT(t.id) AS turns
        FROM sessions s
        JOIN turns t ON t.session_id = s.session_id
    """
```

- [ ] **Step 3: Update `turns_by_model_for_stage` in db.py**

Find `turns_by_model_for_stage` (around line 339). Add the same column:

```python
    sql = """
        SELECT
          COALESCE(t.model, 'unknown') AS model,
          COALESCE(SUM(t.input_tokens), 0) AS input_tokens,
          COALESCE(SUM(t.cache_creation_tokens), 0) AS cache_creation_tokens,
          COALESCE(SUM(t.cache_creation_1h_tokens), 0) AS cache_creation_1h_tokens,
          COALESCE(SUM(t.cache_read_tokens), 0) AS cache_read_tokens,
          COALESCE(SUM(t.output_tokens), 0) AS output_tokens,
          COUNT(t.id) AS turns
        FROM sessions s
        JOIN turns t ON t.session_id = s.session_id
        JOIN session_stage ss ON ss.session_id = s.session_id
    """
```

- [ ] **Step 4: Update `turns_by_model_for_day` in db.py**

Find `turns_by_model_for_day` (around line 530). Add the same column:

```python
    sql = f"""
        SELECT COALESCE(t.model, 'unknown') AS model,
               COALESCE(SUM(t.input_tokens),0) AS input_tokens,
               COALESCE(SUM(t.cache_creation_tokens),0) AS cache_creation_tokens,
               COALESCE(SUM(t.cache_creation_1h_tokens),0) AS cache_creation_1h_tokens,
               COALESCE(SUM(t.cache_read_tokens),0) AS cache_read_tokens,
               COALESCE(SUM(t.output_tokens),0) AS output_tokens,
               COUNT(t.id) AS turns
        FROM sessions s
        JOIN turns t ON t.session_id = s.session_id
        WHERE {' AND '.join(where)}
        GROUP BY COALESCE(t.model, 'unknown')
    """
```

- [ ] **Step 5: Update `daily_cost_by_day` in db.py**

Find `daily_cost_by_day` (around line 483). Add the same column:

```python
    sql = """
        SELECT date(COALESCE(t.ts, s.started_at)) AS day,
               COALESCE(t.model, 'unknown') AS model,
               COALESCE(SUM(t.input_tokens), 0) AS input_tokens,
               COALESCE(SUM(t.cache_creation_tokens), 0) AS cache_creation_tokens,
               COALESCE(SUM(t.cache_creation_1h_tokens), 0) AS cache_creation_1h_tokens,
               COALESCE(SUM(t.cache_read_tokens), 0) AS cache_read_tokens,
               COALESCE(SUM(t.output_tokens), 0) AS output_tokens
        FROM sessions s
        LEFT JOIN turns t ON t.session_id = s.session_id
    """
```

- [ ] **Step 6: Run existing tests to confirm no regressions**

```bash
python -m pytest tests/ -v
```

Expected: all existing tests pass.

- [ ] **Step 7: Commit**

```bash
git add tests/conftest.py claude_usage/db.py
git commit -m "feat(db): thread cache_creation_1h_tokens through cost-feeding queries"
```

---

### Task 4: Update impute_cost() and add unit tests

**Files:**
- Create: `tests/test_pricing_cache_split.py`
- Modify: `claude_usage/pricing.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_pricing_cache_split.py`:

```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_pricing_cache_split.py -v
```

Expected: `test_all_1h_cache_costs_more` and `test_mixed_cache_tiers` FAIL (currently all cache billed at 5m rate). The other two should already pass.

- [ ] **Step 3: Update `impute_cost()` in pricing.py**

Find `impute_cost` (around line 48). Replace the body:

```python
def impute_cost(row: dict, prices: dict) -> Cost:
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
```

- [ ] **Step 4: Run all tests**

```bash
python -m pytest tests/ -v
```

Expected: all tests pass, including the four new ones.

- [ ] **Step 5: Commit**

```bash
git add claude_usage/pricing.py tests/test_pricing_cache_split.py
git commit -m "feat(pricing): split cache write cost into 1h and 5m tiers"
```
