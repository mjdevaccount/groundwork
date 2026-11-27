# platform-kit

The service platform a family of Python services shares: typed config, one push path, a watchdog
plane, a duplicate-guarded registry, a strict plugin loader, a FastAPI composition root, canonical
fingerprints and a Postgres rate budget. One subpackage per plane.

Every consumer fact is an argument. The package names no table, environment variable, host,
schedule or vocabulary of its own: the state table, the owner list, the push transport, the env
names and the market gate are all passed in. `tests/test_purity.py` holds the package to that, and
to its declared imports.

## The planes

| module | what it is | extra |
|---|---|---|
| `registry` | `Registry`, the "specs declared at import, keyed by id" table: a duplicate id raises (or an equal re-import returns the one held), `freeze()` after boot | none |
| `stamp` | canonical JSON fingerprints, pinned bit-for-bit (a persisted stamp never changes algorithm) | none |
| `sqlkit` | `qualified()` for a consumer-supplied `schema.table`, `savepoint()` per fan-out member, `json_text()` for a jsonb bind | none |
| `notify` | `Notifier.notify(Notice) -> Delivery`: dedup, budget, publish, record, never raises; `LocalLedger` holds the same rules in memory when the ledger is down | none |
| `notify.ledger` | `SqlLedger` over the consumer's three tables, with `ddl()` and `outcome_series()` | `sql` |
| `watch` | `WatchRegistry`, `WatchRunner` (probe per savepoint, transition dedup, re-alert, a never-raising pager), `notify_pager` | none |
| `watch.state` | `WatchdogStateStore` over the consumer's state table, with `ddl()` | `sql` |
| `budget` | `PgWindowBudget`: one fixed-window rate budget per vendor account, shared through a Postgres row; its errors are [primitives-kit](../primitives-kit)'s budget tree | `sql` |
| `config` | `Domain` + `knob()`: every knob has a class (secret, topology, tunable, policy, operational, sealed), a source and a fingerprint; `load_all()` at the composition root; `python -m platform_kit.config lint\|schema\|catalog` | `config` |
| `service` | the FastAPI composition root: `Database`, `PgIdentity`, `build_lifespan()`, `ServiceSettings`, typed env-flag families, the `fresh` envelope, one error body, an API-key guard, `/healthz` + `/readyz`, an admin-run timeline | `service` |
| `plugins` | `load()` / `collect()`: pluggy as the transport, `Registry` as the store; a plugin that fails to load stops the process | `plugins` |
| `testing.plugin_conformance` | `PluginConformance`, the mixin a plugin loader runs to prove it keeps the loader contract | `plugins` |

The modules without an extra import the standard library only, so `import platform_kit.notify`
loads no third-party module.

Every plane that can fail says so somewhere a caller can watch: `Delivery.recorded` and an
`on_degraded` hook for notify, `BudgetStats` for the budget, an exit code of 2 ("did not finish
looking") for the watch runner and the config CLI, never 0.

## A budget refusal is a primitives-kit error

```python
import primitives_kit
from platform_kit.budget import PgWindowBudget, Window

try:
    await budget.acquire()
except primitives_kit.BudgetError:  # BudgetExhausted or BudgetUnavailable, from any library
    ...
```

`platform_kit.budget.BudgetExhausted` and `BudgetUnavailable` subclass the primitives-kit classes
of the same name, so a caller that catches the shared tree needs no translation layer.

## Install

Pin a release tag of this package and the extras you use. The source sits in a subdirectory of the
workspace repository:

```toml
# uv
[project]
dependencies = ["platform-kit[service,sql]"]

[tool.uv.sources]
platform-kit = { git = "https://github.com/mjdevaccount/groundwork", tag = "platform-kit-v0.1.0", subdirectory = "packages/platform-kit" }
primitives-kit = { git = "https://github.com/mjdevaccount/groundwork", tag = "primitives-kit-v0.1.0", subdirectory = "packages/primitives-kit" }
```

```text
# pip / PEP 508
platform-kit[service,sql] @ git+https://github.com/mjdevaccount/groundwork@platform-kit-v0.1.0#subdirectory=packages/platform-kit
```

The `sql` extra needs `primitives-kit`, which is not on an index either: pin it the same way.
