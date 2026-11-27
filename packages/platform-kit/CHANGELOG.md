# Changelog: platform-kit

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the package uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Releases are tagged
`platform-kit-vX.Y.Z`.

## [Unreleased]

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
