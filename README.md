# groundwork

Typed, dependency-light Python libraries, one package per concern. Each package under
`packages/` has its own version, changelog and release tag, so a fix to one package moves only
the consumers that pin it.

| package | what it holds | depends on |
|---|---|---|
| [`primitives-kit`](packages/primitives-kit) | shared contracts with no behaviour: the rate-budget protocol, its error tree, the vendor quota reading | pydantic |
| [`pack-contracts`](packages/pack-contracts) | what a pack is written against: a pack manifest read without importing the pack, the pluggy hookspecs and markers, a ledger that holds the versioning rule | pydantic, pluggy |
| [`platform-kit`](packages/platform-kit) | the service platform: typed config, one push path, a watchdog plane, a duplicate-guarded registry, a strict plugin loader, a FastAPI composition root, fingerprints, a Postgres rate budget | stdlib core; per-extra: sqlalchemy + primitives-kit, pydantic-settings, fastapi + structlog, pluggy |

## Layers

Imports point down only. `primitives-kit` is the floor: it imports no other package in this
repository, so any library can depend on it without a cycle. `platform-kit` sits on it (its rate
budget raises primitives-kit's budget errors) and imports no other package here. `pack-contracts`
sits on the floor too and imports nothing that runs a pack: a pack depends on it alone, never on
platform-kit's loader. The rule is an import-linter contract (`pyproject.toml`), run in CI. No
package names a consumer (`tests/test_no_consumer_knowledge.py` scans every one).

## Using a package

Pin the package's release tag and its subdirectory. The tag is `<package>-vX.Y.Z`:

```toml
[tool.uv.sources]
primitives-kit = { git = "https://github.com/mjdevaccount/groundwork", tag = "primitives-kit-v0.1.0", subdirectory = "packages/primitives-kit" }
```

## Developing

```bash
uv sync --all-groups
uv run pytest -q --cov
uv run ruff check . && uv run ruff format --check . && uv run lint-imports
uv run mypy && uv run pyright --verifytypes primitives_kit --ignoreexternal
uv run pyright --verifytypes platform_kit --ignoreexternal
uv run pyright --verifytypes pack_contracts --ignoreexternal
```

platform-kit's SQL stores and rate budget run against a real Postgres: set
`PLATFORM_KIT_TEST_PG=postgresql://user:pw@host:port/db`, or leave it unset and a throwaway
`postgres:18` testcontainer is started (Docker needed; without Docker those tests skip locally).
CI's `pytest` job runs them against a Postgres service with `PLATFORM_KIT_TEST_PG_REQUIRED=1`, so
they cannot skip there; the `test-lowest` leg has no database and does skip them.

Releasing a package: bump its `version`, move `Unreleased` in its `CHANGELOG.md`, merge, then push
the tag `<package>-vX.Y.Z`. `release.yml` re-runs the gate, checks the tag against the package's
version, and attaches that package's sdist and wheel to a GitHub release.
