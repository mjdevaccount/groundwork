# Changelog: pack-contracts

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the package uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Releases are tagged
`pack-contracts-vX.Y.Z`. The contract version (`CONTRACT_VERSION`) is separate from the package
version; each release notes the contract it ships.

## [Unreleased]

### Changed

- README: the C2 seam section names the loader that plugs in, `platform_kit.packs` (docs only).

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
- The versioning rule (a minor adds only hooks, defaulted parameters, protocols and optional
  manifest properties; everything already there stays unchanged) and `surface-ledger.json`, the
  append-only ledger of the whole surface (names, hook parameters with annotations and defaults,
  protocol members, the manifest schema). `verify_ledger()` holds it to the rule;
  `append_only_errors()` holds every released copy (git tags and `base`) to be a prefix of it.
- `PackManifest` and `ManifestRecord` hash by value. A JSON manifest that repeats a key is refused
  at `read`; the `contract` stage is checked before `validate`.
- `pack-manifest.schema.json`, the committed JSON Schema projection of `PackManifest`.
- `python -m pack_contracts schema | surface | validate FILE...`.
