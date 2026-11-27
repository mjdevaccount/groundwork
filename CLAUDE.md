# CLAUDE.md

Operating rules for this workspace. The tour is `README.md`; history is each package's
`CHANGELOG.md`.

## Rules

- **One package per concern**, under `packages/<name>/` with its own `pyproject.toml`, `src/`,
  `tests/`, `README.md` and `CHANGELOG.md`. A package is released alone, by the tag
  `<name>-vX.Y.Z`; the tag must equal that package's `version` (`release.yml` refuses otherwise).
- **Imports point down only.** The layers are import-linter contracts in the root
  `pyproject.toml`; a new package joins them in the change that adds it. `primitives-kit` is the
  floor and imports no other first-party package.
- **primitives-kit is pure**: the standard library and pydantic, nothing else
  (`tests/test_purity.py` reads the source and the installed metadata). It holds contracts only:
  protocols, error trees, value types. A contract enters only when two libraries that cannot import
  each other each carried a copy and the copies had drifted; the change that adds it names both.
- **platform-kit's core is stdlib**: `registry`, `stamp`, `sqlkit`, `notify`, `watch` import the
  standard library only; every other module imports only its extra's declared dependencies
  (`packages/platform-kit/tests/test_purity.py`, which also reads the installed metadata and keeps
  the consumer deny-list as sha256 digests). A new module joins `EXTRA_IMPORTS` there.
- **No consumer knowledge** in any package: no application names, hostnames, addresses, schema
  names, symbol lists or a consumer's environment-variable names. Docstrings state the contract.
- **Unknown is `None`, never `0`.** Datetimes carry a timezone. Value types are frozen.
- **Typed surface**: `mypy --strict` and `pyright --verifytypes` at 100% per package.
- **Coverage floor** in the root `pyproject.toml` is raised, never lowered.
- Branch + PR into `base`, squash, auto-merge armed. CI's `test` job is the required check.
