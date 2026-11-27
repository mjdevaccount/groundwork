# Changelog: primitives-kit

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the package uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Releases are tagged
`primitives-kit-vX.Y.Z`.

## [Unreleased]

## [0.1.0]

### Added

- The rate-budget contract: the `RateBudget` protocol (`acquire`, `observe`), the
  `BudgetError` > `BudgetExhausted` / `BudgetUnavailable` error tree, and `QuotaReading`, the
  vendor's validated report of its own quota window.
