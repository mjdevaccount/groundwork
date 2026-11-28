"""The contracts a pack is written against, and nothing that runs one.

A PACK is an installed distribution that contributes to a host through two entry points of the same
name: a manifest file (read first, without importing the pack) and a pluggy plugin. A pack depends
on THIS distribution only, never on the host's loader.

- `contract`: `CONTRACT_VERSION` (one MAJOR.MINOR for hooks and manifest) and its rule.
- `manifest`: `PackManifest` (id, version, contract, tier, provides, needs) and `Tier`.
- `discovery`: `MANIFEST_GROUP`, `read_manifests()` (no pack code imported), `ManifestError`.
- `hooks`: `PROJECT_NAME`, `PLUGIN_GROUP`, `hookspec` / `hookimpl`, `PackSpec`, `Contribution`.
- `surface`: the contract surface and the committed ledger that holds the versioning rule.
- `schema`: the committed JSON Schema projection of `PackManifest`.

Standard library, pydantic and pluggy; nothing else.
"""

from importlib.metadata import version

from pack_contracts.contract import CONTRACT_VERSION, ContractVersion, satisfies
from pack_contracts.discovery import MANIFEST_GROUP, ManifestError, ManifestRecord, Manifests, read_manifests
from pack_contracts.hooks import (
    PLUGIN_GROUP,
    PROJECT_NAME,
    Contribution,
    PackSpec,
    contribution_key,
    hookimpl,
    hookspec,
)
from pack_contracts.manifest import PackManifest, Tier

__all__ = [
    "CONTRACT_VERSION",
    "MANIFEST_GROUP",
    "PLUGIN_GROUP",
    "PROJECT_NAME",
    "ContractVersion",
    "Contribution",
    "ManifestError",
    "ManifestRecord",
    "Manifests",
    "PackManifest",
    "PackSpec",
    "Tier",
    "__version__",
    "contribution_key",
    "hookimpl",
    "hookspec",
    "read_manifests",
    "satisfies",
]

__version__: str = version("pack-contracts")
