# groundwork

Typed, dependency-light Python libraries, one package per concern. Each package under
`packages/` has its own version, changelog and release tag, so a fix to one package moves only
the consumers that pin it.

| package | what it holds | depends on |
|---|---|---|
| [`primitives-kit`](packages/primitives-kit) | shared contracts with no behaviour: the rate-budget protocol, its error tree, the vendor quota reading | pydantic |

## Layers

Imports point down only. `primitives-kit` is the floor: it imports no other package in this
repository, so any library can depend on it without a cycle. The rule is an import-linter
contract (`pyproject.toml`), run in CI.

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
```

Releasing a package: bump its `version`, move `Unreleased` in its `CHANGELOG.md`, merge, then push
the tag `<package>-vX.Y.Z`. `release.yml` re-runs the gate, checks the tag against the package's
version, and attaches that package's sdist and wheel to a GitHub release.
