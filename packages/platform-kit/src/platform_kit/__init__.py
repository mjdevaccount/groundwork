"""The general service platform, one subpackage per plane; every consumer fact is an argument.

Standard library only (import without an extra):

- `registry`: `Registry`, the duplicate-guarded spec table (`freeze()` after boot).
- `stamp`: canonical JSON fingerprints.
- `sqlkit`: table-name validation, one SAVEPOINT per fan-out member, jsonb text.
- `notify`: `Notifier.notify(Notice) -> Delivery`, the one push path (dedup, budget, record, never
  raises), with an in-memory fallback ledger.
- `watch`: the watchdog plane (spec, runner, pager).

Behind an extra:

- `[sql]`: `budget` (the shared Postgres rate window, on primitives-kit's error tree),
  `notify.ledger` and `watch.state` (the SQL stores over the consumer's tables).
- `[config]`: `config` (typed knobs with a class, a source and a fingerprint).
- `[service]`: `service` (the FastAPI composition root).
- `[plugins]`: `plugins` (the strict entry-point loader) and `testing.plugin_conformance`.
"""

from importlib.metadata import version

__all__ = ["__version__"]

__version__: str = version("platform-kit")
