# budget: one shared fixed-window rate budget per vendor account

Design record for `platform_kit.budget` (`PgWindowBudget`, extra `[sql]`). The module docstring is
the authority for behaviour, including the lock rule and the timing bound; this file holds the
reasons and what was ruled out. The error tree and the `RateBudget` protocol are primitives-kit's.

## Purpose

A vendor's quota belongs to the ACCOUNT, not to a process. Every process that spends it draws from
one counter, so two workers on one key cannot each believe they have the whole quota.

## Decision: the port is primitives-kit's, the Postgres store is ours, pyrate-limiter stays in-process

Checked first: pyrate-limiter 4.5.1 `PostgresBucket`. Not adopted for the shared store, on source
evidence:

| finding in its source | consequence |
|---|---|
| sync only (`is_async = False`, a psycopg 3 `ConnectionPool`) | a blocking call on an async fetch path, plus a second driver pool |
| the constructor runs `CREATE TABLE IF NOT EXISTS` | runtime DDL outside the consumer's migration ledger |
| its clock falls back to LOCAL wall time on any exception, logged only | a guard that fails open: two processes disagree and both spend |
| every `put` takes `LOCK TABLE ... IN EXCLUSIVE MODE NOWAIT`; contention returns `False` | a busy bucket reads as "over limit" |
| a sliding log, one row per unit of weight | many vendors count a FIXED window that starts at the first request |

pyrate-limiter's `InMemoryBucket` remains the right per-process limiter inside a port library; this
module is only the shared store.

## Shape

- `ddl(table) -> str`: the CREATE TABLE text for the consumer to ship as its own numbered migration
  (key, window start, used, capacity, period, the vendor's reset time, updated at). Nothing here runs
  DDL, and the table name is validated before it is interpolated (`sqlkit.qualified`).
- `Window(capacity, period_s)`: the units per period the CONSUMER allows itself, at or below the
  vendor's limit by a stated headroom.
- `PgWindowBudget(sessions, table, key, window, *, max_wait, ...)` with `acquire(weight=1) ->
  seconds waited`, `observe(reading)`, `flush_observed()` and `stats` (`BudgetStats`).
- `BudgetExhausted` and `BudgetUnavailable` subclass primitives-kit's classes of the same name, so a
  caller that catches `primitives_kit.BudgetError` needs no translation layer.

One decision statement per attempt, on the DB clock, under a row lock: an `INSERT ... ON CONFLICT
(key) DO UPDATE` that starts a new window when `clock_timestamp()` has passed the old one, grants when
`used + weight <= capacity`, and returns whether it granted and how long until the window turns. A
refused attempt sleeps that remainder outside any transaction, then asks again.

## Invariants

1. **One row per vendor account key** (`<vendor>:<account>`); every process uses the same key and
   the same `Window`.
2. **The DB clock is the only clock.** No local-time fallback.
3. **Fail closed.** A store error raises `BudgetUnavailable`, never a silent grant. There is no
   default fallback: a lane that must not stop on a database blip wraps the budget in an explicit
   fallback at its composition root and reports every fallback use.
4. **Waiting holds no connection.** The decision is one short statement; the sleep is outside it.
5. **The vendor's counter wins.** `observe()` keeps the latest vendor reading; `flush_observed()`
   sets `used = GREATEST(used, vendor_used)` and the vendor's reset time. A refusal reading pins
   `used = capacity` until that reset. A reading whose reset is already past merges nothing.
6. **Weight is the vendor's unit** (usually one per request). A streaming session takes no budget.
7. **Injected, never imported.** A port library takes any `RateBudget`; it never imports this
   module. The consumer binds the Postgres budget at its composition root.

## Failure semantics

| situation | result |
|---|---|
| granted | `acquire` returns seconds waited (0.0 when immediate) |
| not granted within `max_wait` | `BudgetExhausted(key, waited_s)` |
| store unreachable, statement error, a lock held past the bound | `BudgetUnavailable(key)`; no silent grant |
| a malformed vendor reading | ignored, counted in `stats` |
| capacity or period differ between two processes | last writer wins on the row, a WARNING names both values, `stats` counts it |

## Telemetry

`BudgetStats` counts waits, wait seconds, exhaustions, unavailability, lock contention, slow-store
events, invalid and stale readings and config conflicts. What should watch them, from outside the
process:

| signal | lands | watcher |
|---|---|---|
| wait share, exhaustions, unavailability | the consumer's metrics exporter | an alert: a lane starved, or the store down |
| the bucket row itself (`used`, window start, vendor reset, `updated_at`) | the consumer's table | a drift watchdog: `updated_at` stale during the hours the vendor is used means nothing is drawing (a guard nothing invokes); the vendor's `used` well above ours means an unmetered caller exists |
| vendor refusals | the port library's failure reason | not rising over two sessions after adoption |

## Acceptance tests (`tests/test_budget*.py`)

1. Two budgets on two connections, capacity 5: 8 concurrent `acquire` calls -> exactly 5 immediate,
   3 wait until the window turns (real Postgres; an injected `sleep` records the waits).
2. Must-fire both ways: capacity 1, `max_wait=0.1` -> the second acquire raises `BudgetExhausted`;
   with capacity 2 the same call returns 0.0.
3. Store down -> `BudgetUnavailable`, and a counter proves no grant was returned.
4. `observe(used=90)` then `flush_observed` with local `used=10` -> the row holds 90.
5. A refusal reading drives `used = capacity`; the next acquire waits to the vendor's reset.
6. `ddl(table)` applied twice is idempotent; an unqualified or injected table name is refused.

## Ruled out

| option | why |
|---|---|
| per-process limiters for an account quota | the quota is per access token, not per process |
| pyrate-limiter `PostgresBucket` as the shared store | the table above |
| a circuit-breaker library | the port's fallback chain and the consumer's freshness verdict are the breaker |
| Redis as the shared store | a new resident service for one counter row |
| retry on 429 as the only throttle | some vendors refuse over-quota with HTTP 400 |
