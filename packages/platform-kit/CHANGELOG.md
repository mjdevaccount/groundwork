# Changelog: platform-kit

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the package uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Releases are tagged
`platform-kit-vX.Y.Z`.

## [Unreleased]

## [0.2.0]

### Added

- `platform_kit.packs` (extra `[packs]`: pluggy and pack-contracts 0.1.0 by its release tag): the
  pack loader. `load_packs(pin=, host_provides=)` reads every installed manifest without importing
  the pack, applies the allow-list (`pin_from_env(prefix)` reads `<PREFIX>_LOAD_PACKS`: unset =
  every installed pack, `""` = none, `"a,b"` = exactly those), refuses a key two packs provide and
  a need nobody provides from the manifests alone, imports through `plugins.load`, collects
  `register_contributions` per pack and holds the registered keys equal to the manifest's
  `provides`. Every pack ends `loaded`, `excluded`, `failed` (with the step and the reason) or
  `held`; one `pack_status` log line each, `Packs.series()` for an exporter, and `PackLoadError`
  (carrying the report) when any pack failed. `survey()` is the same run without the raise, and
  `python -m platform_kit.packs list` prints it (exit 1 on a failure): the list-packs surface.
- `docs/packs.md`: the design record of the pack loader; `docs/plugins.md`, `docs/rate-budget.md`,
  `docs/config.md`: the design records of three more planes (reasons, invariants, ruled-out
  options). The purity scan now reads `docs/` too.

### Changed

- `plugins.collect` calls each hookimpl with only the arguments it names, filling the hookspec's
  defaults (`HookSpec.kwargdefaults`), as pluggy's own hook caller does since 1.7. A hookspec that
  gains a defaulted parameter in a minor contract version now reaches an implementation that names
  it; one that names an argument `collect` cannot pass is refused at stage `hook`.
- The consumer-name scan moved out of `tests/test_purity.py` to the workspace's
  `tests/test_no_consumer_knowledge.py`, which runs the same deny-list over every package
  (test-only; nothing shipped changes).

## [0.1.1]

### Security

- `[sql]` names primitives-kit by a direct reference to its release tag
  (`primitives-kit @ git+https://github.com/mjdevaccount/groundwork@primitives-kit-v0.1.0#subdirectory=packages/primitives-kit`),
  not by bare name. Neither name is on PyPI, so a pip install (or `uv --no-sources`) of 0.1.0's
  `[sql]` asked the index for `primitives-kit`, and whoever registered that name would have got code
  into the install. Inside the workspace the root `[tool.uv.sources]` still resolves it to the
  member on disk. The workspace test `tests/test_internal_deps.py` fails CI on a bare internal name
  (or a ref to another package's tag or directory, a version newer than the member on disk, a
  dynamic requirement list, a bare name in `[build-system]`), and CI's build job resolves each
  built wheel with every extra from its metadata alone, so a ref to a tag that is not pushed fails.
- README: install from `platform-kit-v0.1.1`; the uv example no longer pins primitives-kit beside
  it (two URLs for one package), and says when `override-dependencies` is the fix.

## [0.1.0]

### Added

- The general service planes, each behind the extra it needs: `registry`, `stamp`, `sqlkit`,
  `notify` and `watch` (standard library only); `budget`, `notify.ledger` and `watch.state`
  (`[sql]`); `config` (`[config]`); `service` (`[service]`); `plugins` and
  `testing.plugin_conformance` (`[plugins]`).
- `budget.BudgetExhausted` / `BudgetUnavailable` join primitives-kit's budget error tree, so
  catching `primitives_kit.BudgetError` catches a `PgWindowBudget` refusal.
- `notify.TIERS` and `notify.ClockBlind` are defined in `notify.types`: the push path needs no
  policy module of the consumer's.
- `tests/test_purity.py`: each module imports only its extra's declared dependencies, the
  distribution declares exactly those, and no file names a consumer (a hashed deny-list, emails,
  non-documentation IPv4 addresses), each rule proven to fire.
