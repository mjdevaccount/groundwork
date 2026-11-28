"""Read every installed pack's manifest WITHOUT importing any pack code.

A pack names its manifest file under the entry-point group `MANIFEST_GROUP`:

    [project.entry-points."pack_contracts.manifest"]
    example = "example_pack:pack.toml"     # <package>:<file in that package's directory>

The value is a package and a file name, not an object: the reader finds the package's directory
with `importlib.util.find_spec` (the top-level name) and `importlib.machinery.PathFinder` (each
level below it), which locate a package without executing it, and reads the file from there. So a
pack whose import would fail, or would do work at import time, can still be refused, listed or
diffed by its manifest alone. `.toml` and `.json` are read (both standard library).

EVERY FAILURE RAISES `ManifestError(pack, stage)`, a subclass of `ImportError`, so a host that
stops on a plugin that did not load stops on a manifest that did not validate too. There is no
"skip the bad one": a pack that silently did not load is indistinguishable from one nobody
installed. Stages, in the order they are checked:

  duplicate  two installed entry points share a name
  locate     the value is not `<package>:<file>`, the package is not importable, or the file is not
             in its directory
  read       the file could not be read or parsed (or its suffix is not `.toml` / `.json`)
  validate   the content is not a valid `PackManifest`
  identity   the manifest's `id` is not the entry-point name, or its `version` is not the installed
             distribution's
  contract   the manifest's contract is one this host does not satisfy (another MAJOR, or a newer
             MINOR)

TELEMETRY: `read_manifests` logs `pack_manifests_read` at INFO and returns `Manifests`, whose
`series()` renders `pack_manifest{group,pack,version,contract,tier,origin} = 1` per pack for the
host's exporter. A refusal is a raise at boot (the process exits non-zero; the supervisor's restart
count is the signal). What is silently WRONG is a pack that is simply absent, so the host's
watchdog compares that series with the allow-list in its deploy config.

LIBRARIES CHECKED: npe2's `PluginManifest.discover` is the pattern, but it resolves the manifest
with `importlib.util.find_spec("<pkg>.<sub>")`, which imports every parent package, and it LOGS a
manifest that fails validation and yields it as an error result (the caller may drop it); it is
also napari's, with napari's contribution points. stevedore 5.10 reads entry points by loading
them (importing the target) and logs and continues on a failure. pluggy has no manifest notion.
`importlib.metadata.entry_points` is what this module uses underneath.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import logging
import tomllib
from dataclasses import dataclass
from importlib.metadata import entry_points as _installed
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import ValidationError

from pack_contracts.contract import CONTRACT_VERSION, ContractVersion, satisfies
from pack_contracts.manifest import PackManifest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

__all__ = [
    "MANIFEST_GROUP",
    "STAGES",
    "ManifestError",
    "ManifestRecord",
    "Manifests",
    "Stage",
    "parse_manifest",
    "read_manifest",
    "read_manifests",
]

log: logging.Logger = logging.getLogger("pack_contracts.discovery")

#: the entry-point group that names a pack's manifest file
MANIFEST_GROUP = "pack_contracts.manifest"

Stage = Literal["duplicate", "locate", "read", "validate", "identity", "contract"]
STAGES: tuple[str, ...] = ("duplicate", "locate", "read", "validate", "identity", "contract")
_PARSERS: dict[str, Callable[[str], Any]] = {".toml": tomllib.loads, ".json": json.loads}


class ManifestError(ImportError):
    """A pack's manifest was refused. Names the pack (its entry-point name) and the stage."""

    def __init__(self, pack: str, stage: Stage, detail: str) -> None:
        if stage not in STAGES:
            raise ValueError(f"unknown manifest stage {stage!r}")
        super().__init__(f"pack {pack!r} manifest refused at {stage}: {detail}", name=pack)
        self.pack: str = pack
        self.stage: Stage = stage


@dataclass(frozen=True, slots=True)
class ManifestRecord:
    """One validated manifest and where it came from."""

    pack: str
    manifest: PackManifest
    origin: str
    source: str


@dataclass(frozen=True, slots=True)
class Manifests:
    """Every manifest the reader validated, sorted by pack name."""

    group: str
    records: tuple[ManifestRecord, ...]

    @property
    def packs(self) -> tuple[str, ...]:
        """The pack names, in order."""
        return tuple(r.pack for r in self.records)

    def series(self) -> list[tuple[str, dict[str, str], float]]:
        """`pack_manifest{group,pack,version,contract,tier,origin} = 1` per pack, in order."""
        return [
            (
                "pack_manifest",
                {
                    "group": self.group,
                    "pack": r.pack,
                    "version": r.manifest.version,
                    "contract": r.manifest.contract,
                    "tier": r.manifest.tier.value,
                    "origin": r.origin,
                },
                1.0,
            )
            for r in self.records
        ]


def parse_manifest(text: str, *, suffix: str, pack: str = "?") -> PackManifest:
    """Parse and validate manifest `text` in the format `suffix` names (`.toml` or `.json`).
    Raises `ManifestError` at `read` or `validate`; `pack` only labels the error."""
    parser = _PARSERS.get(suffix.lower())
    if parser is None:
        raise ManifestError(pack, "read", f"a manifest is .toml or .json, not {suffix or 'no suffix'!r}")
    try:
        data = parser(text)
    except ValueError as exc:  # tomllib.TOMLDecodeError and json.JSONDecodeError are both ValueErrors
        raise ManifestError(pack, "read", f"not valid {suffix.lower()[1:]}: {exc}") from exc
    try:
        return PackManifest.model_validate(data)
    except ValidationError as exc:
        raise ManifestError(pack, "validate", str(exc)) from exc


def _package_dirs(pack: str, module: str) -> list[Path]:
    """The directories of package `module`, found without executing it or any parent."""
    top, *rest = module.split(".")
    try:
        spec = importlib.util.find_spec(top)  # a top-level name: located, never executed
    except (ImportError, ValueError) as exc:
        raise ManifestError(pack, "locate", f"package {top!r}: {exc}") from exc
    name = top
    for part in rest:
        if spec is None or spec.submodule_search_locations is None:
            break
        name = f"{name}.{part}"
        spec = importlib.machinery.PathFinder.find_spec(name, list(spec.submodule_search_locations))
    if spec is None or spec.submodule_search_locations is None:
        raise ManifestError(pack, "locate", f"{module!r} is not an installed package")
    return [Path(p) for p in spec.submodule_search_locations]


def _origin(ep: Any) -> tuple[str, str | None]:
    dist = getattr(ep, "dist", None)
    name, version = getattr(dist, "name", None), getattr(dist, "version", None)
    if name and version:
        return f"{name}=={version}", version
    return f"entry-point {getattr(ep, 'value', '?')}", None


def read_manifest(ep: Any, *, host: ContractVersion = CONTRACT_VERSION) -> ManifestRecord:
    """Locate, read, validate and check ONE manifest entry point (an `importlib.metadata.EntryPoint`,
    or anything with its `name`, `value` and `dist`). Never calls `ep.load()`."""
    pack = ep.name
    module, sep, filename = str(ep.value).partition(":")
    module, filename = module.strip(), filename.strip()
    if not sep or not module or not filename:
        raise ManifestError(pack, "locate", f"entry point value {ep.value!r} is not '<package>:<file>'")
    if Path(filename).name != filename or filename in {".", ".."}:
        raise ManifestError(pack, "locate", f"{filename!r} is not a file name in the package's directory")
    path = next((d / filename for d in _package_dirs(pack, module) if (d / filename).is_file()), None)
    if path is None:
        raise ManifestError(pack, "locate", f"no {filename!r} in package {module!r}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ManifestError(pack, "read", f"{path}: {exc}") from exc
    manifest = parse_manifest(text, suffix=path.suffix, pack=pack)
    origin, dist_version = _origin(ep)
    if manifest.id != pack:
        raise ManifestError(pack, "identity", f"manifest id {manifest.id!r} is not the entry-point name {pack!r}")
    if dist_version is not None and manifest.version != dist_version:
        raise ManifestError(
            pack, "identity", f"manifest version {manifest.version!r} is not the distribution's {dist_version!r}"
        )
    if not satisfies(host, manifest.contract_version):
        raise ManifestError(pack, "contract", f"the pack targets contract {manifest.contract}; this host speaks {host}")
    return ManifestRecord(pack=pack, manifest=manifest, origin=origin, source=str(path))


def read_manifests(
    *,
    group: str = MANIFEST_GROUP,
    entry_points: Callable[[], Iterable[Any]] | None = None,
    host: ContractVersion = CONTRACT_VERSION,
) -> Manifests:
    """Read every manifest in `group`, sorted by entry-point name. `entry_points` replaces the
    installed set (a test suite pins it; it never reads the developer's site-packages). Any refusal
    raises `ManifestError`; there is no partial result."""
    if not isinstance(group, str) or not group.strip():
        raise ValueError("read_manifests needs a group")
    discover = entry_points if entry_points is not None else (lambda: _installed(group=group))
    by_name: dict[str, Any] = {}
    for ep in discover():
        if ep.name in by_name:
            raise ManifestError(ep.name, "duplicate", "two installed entry points share the name")
        by_name[ep.name] = ep
    records = tuple(read_manifest(by_name[name], host=host) for name in sorted(by_name))
    found = Manifests(group, records)
    log.info(
        "pack_manifests_read group=%s packs=%s origin=%s",
        group,
        ",".join(found.packs),
        {r.pack: r.origin for r in records},
    )
    return found
