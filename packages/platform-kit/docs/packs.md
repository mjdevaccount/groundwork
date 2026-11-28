# packs: one path from an installed pack to its contributions

Design record for `platform_kit.packs`. The module docstring is the authority for behaviour; this
file holds the reasons and what was ruled out.

## Purpose

A pack is a distribution written against [pack-contracts](../../pack-contracts): a manifest under
`pack_contracts.manifest` and a plugin under `pack_contracts.plugin`, both named by the pack's id.
A host that runs packs needs the same answer to "which packs run here, and why not the others"
every time, so there is one loader and every host calls it. Two loaders reading the same entry
points with different rules is the defect this module exists to prevent.

## Decision: manifests before code, the set loads whole

The steps run in this order: `manifest`, `pair`, `pin`, `provides`, `needs`, `load`, `keys`. Every
step before `load` reads manifests only, so a pack that collides with another, needs something
nobody provides, or is left out by the allow-list is refused before any of its code is imported.

- **Every installed manifest is read, selected or not.** An installed pack whose manifest does not
  validate is a packaging defect on this machine; the allow-list chooses among sound packs and
  does not hide a broken one.
- **The set loads whole or not at all.** When any selected pack fails before the import, the other
  selected packs are `held`, not loaded. A host that boots with half its intended packs is the
  "pack quietly dropped" case in another form.
- **A duplicate key refuses both packs**, each naming the other. Picking a winner (the first by
  name, the newest) would make the result depend on which packs happen to be installed.
- **`needs` are capabilities, not packs.** The host passes what it provides itself
  (`host_provides`); a selected pack may provide the rest. A need met only by an excluded pack is
  unmet.
- **The registered keys equal the manifest's `provides`.** This is what tier `loads` claims, and it
  keeps the manifest honest: the pre-import merge is only as good as the declarations it reads.

## Decision: report everything, raise at boot

`survey()` returns every pack's state (`loaded`, `excluded`, `failed` with step and reason, `held`)
and never raises for a pack. `load_packs()` is the boot call: it logs one `pack_status` line per
pack and a `packs_loaded` summary, then raises `PackLoadError` (an `ImportError` carrying the
report) when any pack failed. The two share one run, so the list-packs surface
(`python -m platform_kit.packs list`, exit 1 on a failure) shows exactly what boot would refuse.

## The allow-list

`pin_from_env(prefix)` reads `<PREFIX>_LOAD_PACKS`. Unset = every installed pack; `""` = none;
`"a,b"` = exactly those, and a listed name that is not installed fails. These are the plugin
loader's R6 semantics, so a host's two pins read the same way. The prefix is the host's: this
package names no consumer's variable.

## Telemetry

What fails silently here is a pack that is simply not installed, or not pinned: nothing raises.
`Packs.series()` renders `pack_status{pack,state,version,origin} = 1`; the host exports it and its
watchdog compares the loaded set with the pin in its deploy config. Everything else is a raise at
boot, and the supervisor's restart count is the signal.

## Checked and not chosen

- `pack_contracts.read_manifests`: all-or-nothing by design, which is right for a host that only
  reads manifests and wrong for a report that must name every pack. This module reads one manifest
  per entry point with `read_manifest` instead.
- pluggy: the transport (through `platform_kit.plugins`). It has no manifest, allow-list or merge
  step, and `load_setuptools_entrypoints` imports every plugin to discover it.
- stevedore 5.10: logs and continues on a failed load; reads entry points by importing them.
- napari npe2's plugin manager: reads manifests first, but a manifest that fails validation is
  logged and the plugin skipped, and the contribution points are napari's.

## Not here

- Pack-defined config, routers or lifecycle hooks: each is a new hook in a minor contract version
  of pack-contracts, collected through the same path.
- A minimum tier a host requires (`Tier.at_least`): the manifest carries the claim; a host that
  needs one checks `report` today.
