"""The contract's surface, and the committed ledger that holds `pack_contracts.contract`'s rule.

The SURFACE is what a pack is written against, as plain data: per hook, its required parameters,
its defaulted parameters (name -> `repr` of the default) and its `firstresult` / `historic`
options; for the manifest, its required and optional fields.

The LEDGER (`surface-ledger.json`, shipped in this package) is append-only: one entry per released
contract version, oldest first. `verify_ledger` holds it to the rule:

- versions strictly increase; a new MAJOR starts at `.0` and is exactly one more;
- inside one MAJOR every entry is a compatible evolution of the one before (`evolution_errors`):
  hooks and manifest fields may be ADDED (a hook parameter only with a default, a manifest field
  only as optional); nothing is removed, renamed, made required, re-defaulted or re-optioned;
- the last entry is `CONTRACT_VERSION`, and it equals the live surface. So changing a hookspec, or
  the manifest model, fails the suite until the change is entered as a new version, and an
  incompatible change fails unless that version is a new MAJOR.

Why defaults are the minor-version lever: pluggy >= 1.7 fills a hookspec's defaulted parameters
when the caller omits them (`HookCaller._apply_defaults` merges `HookSpec.kwargdefaults` under the
call's arguments), and calls each implementation with only the parameters it names. So an
implementation written before a parameter existed keeps working, and a caller written before it
existed keeps calling. A new REQUIRED parameter breaks the old caller (pluggy only WARNS that the
call lacks it, then an implementation naming it fails with `HookCallError`); a removed one breaks
the implementation that names it.

Regenerate the live surface with `python -m pack_contracts surface`.
"""

from __future__ import annotations

import inspect
import json
from importlib.resources import files
from typing import TYPE_CHECKING, Any

from pack_contracts.contract import CONTRACT_VERSION, ContractVersion
from pack_contracts.hooks import PROJECT_NAME, PackSpec
from pack_contracts.manifest import PackManifest

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pydantic import BaseModel

__all__ = [
    "LEDGER_RESOURCE",
    "evolution_errors",
    "hook_surface",
    "live_surface",
    "load_ledger",
    "manifest_surface",
    "verify_ledger",
]

LEDGER_RESOURCE = "surface-ledger.json"
_KINDS = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)


def hook_surface(spec: type, project: str = PROJECT_NAME) -> dict[str, dict[str, Any]]:
    """Every hookspec on `spec` (a class), by name: `required`, `defaulted`, `firstresult`, `historic`.
    A keyword-only or variadic parameter raises ValueError: pluggy does not pass one, so it could
    never be part of the contract."""
    marker = f"{project}_spec"
    out: dict[str, dict[str, Any]] = {}
    for name in sorted(vars(spec)):
        func = vars(spec)[name]
        opts = getattr(func, marker, None)
        if opts is None:
            continue
        params = list(inspect.signature(func).parameters.values())[1:]  # drop `self`
        odd = [p.name for p in params if p.kind not in _KINDS]
        if odd:
            raise ValueError(f"hook {name!r}: keyword-only or variadic parameters {odd} are not passed by pluggy")
        empty = inspect.Parameter.empty
        out[name] = {
            "required": [p.name for p in params if p.default is empty],
            "defaulted": {p.name: repr(p.default) for p in params if p.default is not empty},
            "firstresult": bool(opts.get("firstresult", False)),
            "historic": bool(opts.get("historic", False)),
        }
    return out


def manifest_surface(model: type[BaseModel] = PackManifest) -> dict[str, list[str]]:
    """The manifest's fields by the names a file uses: `required` and `optional`, sorted."""
    fields = {(f.alias or n): f.is_required() for n, f in model.model_fields.items()}
    return {
        "required": sorted(n for n, req in fields.items() if req),
        "optional": sorted(n for n, req in fields.items() if not req),
    }


def live_surface() -> dict[str, Any]:
    """The surface this distribution defines now, as a ledger entry."""
    return {"contract": str(CONTRACT_VERSION), "hooks": hook_surface(PackSpec), "manifest": manifest_surface()}


def load_ledger() -> list[dict[str, Any]]:
    """The committed ledger's entries, oldest first."""
    data = json.loads(files("pack_contracts").joinpath(LEDGER_RESOURCE).read_text(encoding="utf-8"))
    entries: list[dict[str, Any]] = data["entries"]
    return entries


def evolution_errors(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[str]:
    """Why `new` is NOT a compatible (minor) evolution of `old`; empty when it is."""
    errors: list[str] = []
    for hook, was in old["hooks"].items():
        now = new["hooks"].get(hook)
        if now is None:
            errors.append(f"hook {hook!r} was removed")
            continue
        added = sorted(set(now["required"]) - set(was["required"]))
        if added:
            errors.append(f"hook {hook!r}: new required parameters {added} (a minor adds only defaulted ones)")
        for param in sorted(set(was["required"]) - set(now["required"])):
            where = "made defaulted" if param in now["defaulted"] else "removed"
            errors.append(f"hook {hook!r}: required parameter {param!r} {where}")
        for param, default in was["defaulted"].items():
            if param not in now["defaulted"]:
                where = "made required" if param in now["required"] else "removed"
                errors.append(f"hook {hook!r}: defaulted parameter {param!r} {where}")
            elif now["defaulted"][param] != default:
                errors.append(f"hook {hook!r}: default of {param!r} changed {default} -> {now['defaulted'][param]}")
        for opt in ("firstresult", "historic"):
            if bool(was[opt]) != bool(now[opt]):
                errors.append(f"hook {hook!r}: {opt} changed {was[opt]} -> {now[opt]}")
    was_m, now_m = old["manifest"], new["manifest"]
    if sorted(now_m["required"]) != sorted(was_m["required"]):
        errors.append(f"manifest: required fields changed {was_m['required']} -> {now_m['required']}")
    gone = sorted(set(was_m["optional"]) - set(now_m["optional"]) - set(now_m["required"]))
    if gone:
        errors.append(f"manifest: optional fields removed {gone}")
    return errors


def verify_ledger(
    entries: Sequence[Mapping[str, Any]],
    live: Mapping[str, Any],
    current: ContractVersion = CONTRACT_VERSION,
) -> list[str]:
    """Every way the ledger breaks the rule, or disagrees with the live surface; empty when it holds."""
    if not entries:
        return ["the ledger is empty"]
    errors: list[str] = []
    versions = [ContractVersion.parse(str(e["contract"])) for e in entries]
    for i in range(1, len(entries)):
        prev_v, next_v, prev, nxt = versions[i - 1], versions[i], entries[i - 1], entries[i]
        if next_v <= prev_v:
            errors.append(f"{next_v} does not follow {prev_v}")
        elif next_v.major == prev_v.major:
            errors += [f"{prev_v} -> {next_v}: {e}" for e in evolution_errors(prev, nxt)]
        elif next_v != ContractVersion(prev_v.major + 1, 0):
            errors.append(f"{next_v} after {prev_v}: a new major is the next integer, at minor 0")
    if versions[-1] != current:
        errors.append(f"the last entry is {versions[-1]}, but the contract is {current}")
    last = dict(entries[-1])
    if {"hooks": last.get("hooks"), "manifest": last.get("manifest")} != {
        "hooks": live["hooks"],
        "manifest": live["manifest"],
    }:
        errors.append(
            f"the live surface differs from the ledger's {versions[-1]} entry: enter the change as a new "
            "contract version (`python -m pack_contracts surface`)"
        )
    return errors
