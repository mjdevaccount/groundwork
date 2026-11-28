"""Load the installed packs: manifests first, then the allow-list, the merge, the import, the key check.
Extra `[packs]` (pluggy>=1.7, pack-contracts).

A PACK is an installed distribution written against `pack_contracts` (its manifest under
`pack_contracts.manifest`, its plugin under `pack_contracts.plugin`, both by the pack's id). This
is the ONE path from "installed" to "contributing": every host that runs packs calls it, so a pack
is refused, excluded or loaded by the same rules everywhere.

    report = load_packs(pin=pin_from_env("MY_APP"), host_provides=[("clock", "utc")])
    report.contributions[("greeting", "hello")]       # what the packs registered, by (kind, name)
    log/expose `report.series()`                      # pack_status{pack,state,version,origin}

THE STEPS, in order. A step that refuses a pack marks it `failed` with the step as its `stage`;
nothing is imported unless every step before the import passed for every selected pack.

  manifest  every installed manifest is read and validated WITHOUT importing the pack
            (`pack_contracts.read_manifest`), whether or not the allow-list selects it: an
            installed pack with a broken manifest is a packaging defect, and the host stops on it.
  pair      a plugin entry point with no manifest of the same name is refused (it would load code
            nobody declared); so is a selected manifest with no plugin.
  pin       the allow-list. `pin` (a host reads it with `pin_from_env`, `<PREFIX>_LOAD_PACKS`):
            None = every installed pack, "" = none, "a,b" = exactly those. A pinned name that is
            not installed is refused. A pack the pin leaves out is `excluded`, never silent.
  provides  the merge, from the manifests alone: a `(kind, name)` two selected packs provide
            refuses BOTH, each naming the other.
  needs     a need neither the host (`host_provides`) nor another selected pack provides.
  load      `platform_kit.plugins.load` (R1-R10) over the selected plugin entry points, then
            `collect(register_contributions)` one pack at a time, in name order.
  keys      the keys a pack registered must equal its manifest's `provides` exactly: a key
            registered and not declared, or declared and never registered (what tier `loads` claims).

States: `loaded`; `excluded` (the pin left it out); `failed` (stage + reason); `held` (selected and
sound, but not loaded because another selected pack failed before the import: the set loads whole
or not at all).

TELEMETRY. `survey()` never raises for a pack: it returns the `Packs` report with every installed
pack's state. `load_packs()` is the boot call: it runs the survey, logs one `pack_status` line per
pack (ERROR for failed, WARNING for held, INFO otherwise) plus a `packs_loaded` summary, and raises
`PackLoadError` (an ImportError carrying the report) when any pack failed -- a crashed boot, never a
pack quietly dropped. What stays silently wrong is a pack that is simply not installed: the host's
watchdog compares `Packs.series()` with the pin in its deploy config. `python -m platform_kit.packs
list` (`main`) prints the report and exits 1 when a pack failed: the list-packs surface.

LIBRARIES CHECKED: `pack_contracts.read_manifests` is all-or-nothing by design (a host that only
reads manifests stops at the first refusal); the report needs every pack's state, so this module
reads one manifest per entry point with its `read_manifest`. pluggy has no manifest, allow-list or
merge step. stevedore 5.10 logs and continues on a failed load. The import is `platform_kit.plugins`.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from importlib.metadata import entry_points as _installed
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

import pluggy

from pack_contracts import (
    CONTRACT_VERSION,
    MANIFEST_GROUP,
    PLUGIN_GROUP,
    PROJECT_NAME,
    ContractVersion,
    Contribution,
    ManifestError,
    PackSpec,
)
from pack_contracts.discovery import ManifestRecord, read_manifest
from platform_kit import plugins
from platform_kit.registry import Registry

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

__all__ = [
    "PIN_SUFFIX",
    "PackLoadError",
    "PackStatus",
    "Packs",
    "State",
    "load_packs",
    "main",
    "pin_from_env",
    "survey",
]

log: logging.Logger = logging.getLogger("platform_kit.packs")

State = Literal["loaded", "excluded", "failed", "held"]
Stage = Literal["manifest", "pair", "pin", "provides", "needs", "load", "keys"]
#: a host's allow-list variable is `<PREFIX>` + this; the prefix is the host's
PIN_SUFFIX = "_LOAD_PACKS"
Key = tuple[str, str]


@dataclass(frozen=True, slots=True)
class PackStatus:
    """One installed (or pinned) pack and what happened to it. Unknown is None."""

    pack: str
    state: State
    version: str | None = None
    origin: str | None = None
    stage: Stage | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class Packs:
    """Every pack's status, sorted by name, and what the loaded packs registered."""

    statuses: tuple[PackStatus, ...]
    contributions: Mapping[Key, Contribution] = field(default_factory=lambda: MappingProxyType({}))
    owner: Mapping[Key, str] = field(default_factory=lambda: MappingProxyType({}))

    def of(self, state: State) -> tuple[str, ...]:
        """The names of the packs in `state`, in order."""
        return tuple(s.pack for s in self.statuses if s.state == state)

    @property
    def ok(self) -> bool:
        """True when no pack failed."""
        return not self.of("failed")

    def series(self) -> list[tuple[str, dict[str, str], float]]:
        """`pack_status{pack,state,version,origin} = 1` per pack, in order ("" = unknown)."""
        return [
            (
                "pack_status",
                {"pack": s.pack, "state": s.state, "version": s.version or "", "origin": s.origin or ""},
                1.0,
            )
            for s in self.statuses
        ]

    def render(self) -> str:
        """The list-packs table: one line per pack, then the totals."""
        if not self.statuses:
            return "no packs installed\n"
        rows = [("pack", "state", "version", "origin", "reason")]
        for s in self.statuses:
            why = f"{s.stage}: {s.reason}" if s.stage else (s.reason or "")
            rows.append((s.pack, s.state, s.version or "-", s.origin or "-", why))
        widths = [max(len(r[i]) for r in rows) for i in range(4)]
        lines = ["  ".join([*(c.ljust(w) for c, w in zip(r[:4], widths, strict=True)), r[4]]).rstrip() for r in rows]
        counts = ", ".join(f"{len(self.of(st))} {st}" for st in ("loaded", "excluded", "failed", "held"))
        return "\n".join([*lines, counts]) + "\n"


class PackLoadError(ImportError):
    """At least one pack failed. `report` holds every pack's status; the message names each failure."""

    def __init__(self, report: Packs) -> None:
        failed = [s for s in report.statuses if s.state == "failed"]
        detail = "; ".join(f"{s.pack!r} at {s.stage}: {s.reason}" for s in failed)
        super().__init__(f"{len(failed)} pack(s) failed to load: {detail}", name=failed[0].pack if failed else None)
        self.report: Packs = report


def pin_from_env(prefix: str, environ: Mapping[str, str] | None = None) -> str | None:
    """The allow-list `<prefix>_LOAD_PACKS`, or None when it is unset (= every installed pack)."""
    if not prefix or not prefix.strip():
        raise ValueError("pin_from_env needs the host's prefix")
    return (os.environ if environ is None else environ).get(prefix + PIN_SUFFIX)


def _contribution_id(thing: Contribution) -> str:
    return f"{thing.kind}/{thing.name}"  # slugs hold no "/": one string per (kind, name)


class _Survey:
    """The state of one run: a status per pack, filled step by step."""

    def __init__(self) -> None:
        self.status: dict[str, PackStatus] = {}

    def fail(self, pack: str, stage: Stage, reason: str, record: ManifestRecord | None = None) -> None:
        if self.failed(pack):
            return  # the first refusal is the one reported
        version, origin = (record.manifest.version, record.origin) if record else (None, None)
        self.status[pack] = PackStatus(pack, "failed", version, origin, stage, reason)

    def set(self, pack: str, state: State, record: ManifestRecord, reason: str | None = None) -> None:
        self.status[pack] = PackStatus(pack, state, record.manifest.version, record.origin, None, reason)

    def failed(self, pack: str) -> bool:
        s = self.status.get(pack)
        return s is not None and s.state == "failed"


def _by_name(eps: Iterable[Any]) -> tuple[dict[str, Any], set[str]]:
    found: dict[str, Any] = {}
    dupes: set[str] = set()
    for ep in eps:
        if ep.name in found:
            dupes.add(ep.name)
        found[ep.name] = ep
    return found, dupes


def _read(
    run: _Survey, manifest_eps: Iterable[Any], plugin_eps: Mapping[str, Any], host: ContractVersion
) -> dict[str, ManifestRecord]:
    """Steps `manifest` and `pair` (the orphan plugin half)."""
    eps, dupes = _by_name(manifest_eps)
    records: dict[str, ManifestRecord] = {}
    for name in sorted(eps):
        if name in dupes:
            run.fail(name, "manifest", "two installed manifest entry points share the name")
            continue
        try:
            records[name] = read_manifest(eps[name], host=host)
        except ManifestError as exc:
            run.fail(name, "manifest", f"{exc.stage}: {exc}")
    for name in sorted(set(plugin_eps) - set(eps)):
        run.fail(name, "pair", "a plugin entry point with no manifest of the same name")
    return records


def _select(run: _Survey, records: Mapping[str, ManifestRecord], installed: set[str], pin: str | None) -> list[str]:
    """Step `pin`: who is selected; the rest are excluded."""
    wanted = set(installed) if pin is None else {p.strip() for p in pin.split(",") if p.strip()}
    for name in sorted(wanted - installed):
        run.fail(name, "pin", f"pinned but not installed (installed: {sorted(installed)})")
    for name in sorted(n for n in set(records) - wanted if not run.failed(n)):
        run.set(name, "excluded", records[name], "not in the allow-list")
    return sorted(n for n in wanted & set(records) if not run.failed(n))


def _merge(
    run: _Survey,
    records: Mapping[str, ManifestRecord],
    selected: Sequence[str],
    plugin_eps: Mapping[str, Any],
    host_provides: frozenset[Key],
) -> None:
    """Steps `pair` (the missing plugin half), `provides` and `needs`, on the manifests alone."""
    owner: dict[Key, str] = {}
    for name in selected:
        if name not in plugin_eps:
            run.fail(name, "pair", "a manifest with no plugin entry point of the same name", records[name])
        for key in sorted(records[name].manifest.provided()):
            first = owner.setdefault(key, name)
            if key in host_provides:
                run.fail(name, "provides", f"{key} is provided by the host already", records[name])
            elif first != name:
                for pack in (first, name):
                    run.fail(pack, "provides", f"{key} is provided by both {first!r} and {name!r}", records[pack])
    available = set(host_provides) | {k for n in selected if not run.failed(n) for k in records[n].manifest.provided()}
    for name in selected:
        missing = sorted(records[name].manifest.needed() - available)
        if missing:
            run.fail(name, "needs", f"nobody provides {missing}", records[name])


def _load(
    run: _Survey, records: Mapping[str, ManifestRecord], selected: Sequence[str], plugin_eps: Mapping[str, Any]
) -> tuple[dict[Key, Contribution], dict[Key, str]]:
    """Steps `load` and `keys`."""
    pm = pluggy.PluginManager(PROJECT_NAME)
    eps = [plugin_eps[n] for n in selected]
    try:
        loaded = plugins.load(
            pm, group=PLUGIN_GROUP, hookspecs=PackSpec, pin=",".join(selected), entry_points=lambda: eps
        )
    except plugins.PluginLoadError as exc:
        for name in [exc.plugin] if exc.plugin in selected else selected:
            run.fail(name, "load", f"{exc.stage}: {exc}", records[name])
        return {}, {}
    store: Registry[Contribution] = Registry("pack contribution", key=_contribution_id)
    contributions: dict[Key, Contribution] = {}
    owner: dict[Key, str] = {}
    for name in selected:
        before = set(store)
        one = plugins.Loaded(loaded.group, (name,), loaded.origin)
        try:
            plugins.collect(pm, "register_contributions", store, loaded=one, kind=Contribution, freeze=False)
        except plugins.PluginLoadError as exc:
            run.fail(name, "load", f"{exc.stage}: {exc}", records[name])
            continue
        got = {(store[k].kind, store[k].name): store[k] for k in set(store) - before}
        declared = records[name].manifest.provided()
        extra, absent = sorted(set(got) - declared), sorted(declared - set(got))
        if extra or absent:
            run.fail(
                name,
                "keys",
                f"registered but not declared {extra}; declared but not registered {absent}",
                records[name],
            )
            continue
        contributions.update(got)
        owner.update(dict.fromkeys(got, name))
        run.set(name, "loaded", records[name])
    store.freeze()
    return contributions, owner


def survey(
    *,
    pin: str | None,
    host_provides: Iterable[Key] = (),
    manifest_entry_points: Callable[[], Iterable[Any]] | None = None,
    plugin_entry_points: Callable[[], Iterable[Any]] | None = None,
    host: ContractVersion = CONTRACT_VERSION,
) -> Packs:
    """Run every step and report every pack's state; never raises for a pack (`load_packs` does).
    The two `*_entry_points` replace the installed sets (a suite pins them, R9)."""
    run = _Survey()
    manifest_eps = (manifest_entry_points or (lambda: _installed(group=MANIFEST_GROUP)))()
    plugin_eps, plugin_dupes = _by_name((plugin_entry_points or (lambda: _installed(group=PLUGIN_GROUP)))())
    records = _read(run, manifest_eps, plugin_eps, host)
    for name in sorted(plugin_dupes):
        run.fail(name, "pair", "two installed plugin entry points share the name", records.get(name))
    installed = set(records) | {n for n, s in run.status.items() if s.stage in ("manifest", "pair")}
    selected = _select(run, records, installed, pin)
    _merge(run, records, selected, plugin_eps, frozenset(host_provides))
    selected = [n for n in selected if not run.failed(n)]
    contributions: dict[Key, Contribution] = {}
    owner: dict[Key, str] = {}
    if any(s.state == "failed" for s in run.status.values()):
        for name in selected:
            run.set(name, "held", records[name], "not loaded: another pack failed, and the set loads whole")
    else:
        contributions, owner = _load(run, records, selected, plugin_eps)
    return Packs(
        tuple(run.status[n] for n in sorted(run.status)), MappingProxyType(contributions), MappingProxyType(owner)
    )


_LEVEL: dict[str, int] = {"failed": logging.ERROR, "held": logging.WARNING}


def load_packs(
    *,
    pin: str | None,
    host_provides: Iterable[Key] = (),
    manifest_entry_points: Callable[[], Iterable[Any]] | None = None,
    plugin_entry_points: Callable[[], Iterable[Any]] | None = None,
    host: ContractVersion = CONTRACT_VERSION,
) -> Packs:
    """The boot call: `survey`, one `pack_status` log line per pack and a `packs_loaded` summary,
    then `PackLoadError` when any pack failed."""
    report = survey(
        pin=pin,
        host_provides=host_provides,
        manifest_entry_points=manifest_entry_points,
        plugin_entry_points=plugin_entry_points,
        host=host,
    )
    for s in report.statuses:
        log.log(
            _LEVEL.get(s.state, logging.INFO),
            "pack_status pack=%s state=%s version=%s origin=%s stage=%s reason=%s",
            s.pack,
            s.state,
            s.version,
            s.origin,
            s.stage,
            s.reason,
        )
    log.info(
        "packs_loaded pin=%r loaded=%s excluded=%s failed=%s held=%s",
        pin,
        ",".join(report.of("loaded")),
        ",".join(report.of("excluded")),
        ",".join(report.of("failed")),
        ",".join(report.of("held")),
    )
    if not report.ok:
        raise PackLoadError(report)
    return report


def _key(text: str) -> Key:
    kind, sep, name = text.partition("/")
    if not sep or not kind or not name:
        raise argparse.ArgumentTypeError(f"{text!r} is not kind/name")
    return kind, name


def main(argv: Sequence[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    """`list [--pin P | --env-prefix PREFIX] [--host-provides kind/name ...]`: print the report;
    exit 1 when a pack failed, 0 otherwise."""
    parser = argparse.ArgumentParser(prog="python -m platform_kit.packs")
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("list", help="every installed pack and its state")
    which = cmd.add_mutually_exclusive_group()
    which.add_argument("--pin", default=None, help='the allow-list: "" = none, "a,b" = exactly those')
    which.add_argument("--env-prefix", default=None, help="read the allow-list from <PREFIX>_LOAD_PACKS")
    cmd.add_argument("--host-provides", type=_key, action="append", default=[], help="a key the host provides")
    args = parser.parse_args(argv)
    pin = pin_from_env(args.env_prefix, environ) if args.env_prefix else args.pin
    report = survey(pin=pin, host_provides=args.host_provides)
    sys.stdout.write(report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover - `main` is tested in-process
    raise SystemExit(main())
