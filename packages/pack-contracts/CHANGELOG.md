# Changelog: pack-contracts

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the package uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Releases are tagged
`pack-contracts-vX.Y.Z`. The contract version (`CONTRACT_VERSION`) is separate from the package
version; each release notes the contract it ships.

## [Unreleased]

## [0.1.0]

Contract 1.0.

### Added

- `PackManifest` (pydantic v2, `extra="forbid"`, frozen): `id`, `version`, `contract`, `tier`,
  `provides`, `needs`, `title`, `description`; `Tier` (`declared` < `loads` < `conformant`).
- `read_manifests()` / `read_manifest()`: every `pack_contracts.manifest` entry point, sorted, read
  and validated without importing the pack; every failure a `ManifestError(pack, stage)`;
  `Manifests.series()` for the host's exporter.
- The pluggy surface: `PROJECT_NAME`, `PLUGIN_GROUP`, the `hookspec` / `hookimpl` markers,
  `PackSpec.register_contributions`, the `Contribution` protocol and `contribution_key`.
- The versioning rule (a minor adds only hooks, defaulted parameters and optional manifest fields)
  and `surface-ledger.json`, the append-only ledger `verify_ledger()` holds to it.
- `pack-manifest.schema.json`, the committed JSON Schema projection of `PackManifest`.
- `python -m pack_contracts schema | surface | validate FILE...`.
