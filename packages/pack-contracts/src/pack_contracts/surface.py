"""The contract's surface, and the committed ledger that holds `pack_contracts.contract`'s rule.

The SURFACE is everything a pack is written against, as plain data:

- `names`: the pluggy project name and the two entry-point groups (renaming one breaks every pack);
- `hooks`: per hookspec, each parameter's annotation and whether it is required (and if not, the
  `repr` of its default), the return annotation, and the `firstresult` / `historic` options;
- `protocols`: per protocol a pack implements, each member and its annotation;
- `manifest`: the manifest's JSON Schema (`pack_contracts.schema`), with `description` and `title`
  annotations stripped (prose is not contract; types, patterns, enums, bounds and defaults are);
- `manifest_rules`: the model's validators by name, with the fields each one checks. A schema
  cannot express a cross-field rule, so its body is not compared; adding, removing or re-targeting
  one changes the surface (and a changed BODY that refuses what used to pass is a new major by the
  rule, which the reviewer holds, not this ledger).

The LEDGER (`surface-ledger.json`, shipped in this package) is append-only: one entry per released
contract version, oldest first. `verify_ledger` holds it to the rule:

- versions strictly increase; a new MAJOR starts at `.0` and is exactly one more;
- inside one MAJOR every entry is a compatible evolution of the one before (`evolution_errors`):
  everything already there is UNCHANGED, and the only additions are a hook, a DEFAULTED parameter,
  a protocol, an OPTIONAL manifest property or a schema definition;
- the last entry is `CONTRACT_VERSION`, and it equals the live surface. So changing a hookspec, a
  name, a protocol or the manifest model fails the suite until the change is entered as a new
  version, and an incompatible change fails unless that version is a new MAJOR.

`append_only_errors` holds a released ledger (the file at a `pack-contracts-v*` tag, or on the
default branch) to be a PREFIX of the current one, so an entry edited in place is caught too; the
suite reads the released copies from git.

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
import re
from importlib.resources import files
from typing import TYPE_CHECKING, Any, cast

from pack_contracts.contract import CONTRACT_VERSION, ContractVersion
from pack_contracts.discovery import MANIFEST_GROUP
from pack_contracts.hooks import PLUGIN_GROUP, PROJECT_NAME, Contribution, PackSpec
from pack_contracts.manifest import PackManifest
from pack_contracts.schema import manifest_json_schema

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from pydantic import BaseModel

__all__ = [
    "LEDGER_RESOURCE",
    "append_only_errors",
    "evolution_errors",
    "hook_surface",
    "ledger_entries",
    "live_surface",
    "load_ledger",
    "manifest_surface",
    "names_surface",
    "protocol_surface",
    "rules_surface",
    "verify_ledger",
]

LEDGER_RESOURCE = "surface-ledger.json"
_KINDS = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
#: `repr` of an object with no `__repr__` of its own: an address, different every run
_ADDRESS_REPR = re.compile(r" at 0x[0-9A-Fa-f]+>")
#: schema keywords that are prose, not contract
_PROSE = frozenset({"description", "title"})
#: schema keywords whose value maps NAMES to schemas (the names are data, never prose keywords)
_NAMED = frozenset({"properties", "patternProperties", "$defs"})


def _annotation(value: Any) -> str:
    if value is inspect.Parameter.empty:
        return ""
    return value if isinstance(value, str) else inspect.formatannotation(value)


def hook_surface(spec: type, project: str = PROJECT_NAME) -> dict[str, dict[str, Any]]:
    """Every hookspec on `spec` (a class), by name: `params` (name -> `annotation`, `required`, and
    `default` when not required), `returns`, `firstresult`, `historic`.
    A keyword-only or variadic parameter raises ValueError (pluggy does not pass one, so it could
    never be part of the contract), and so does a default whose `repr` is an address (a sentinel
    object: it would differ on every run, so no ledger could hold it)."""
    marker = f"{project}_spec"
    out: dict[str, dict[str, Any]] = {}
    for name in sorted(vars(spec)):
        func = vars(spec)[name]
        opts = getattr(func, marker, None)
        if opts is None:
            continue
        sig = inspect.signature(func)
        params = list(sig.parameters.values())[1:]  # drop `self`
        odd = [p.name for p in params if p.kind not in _KINDS]
        if odd:
            raise ValueError(f"hook {name!r}: keyword-only or variadic parameters {odd} are not passed by pluggy")
        described: dict[str, dict[str, Any]] = {}
        for p in params:
            entry: dict[str, Any] = {"annotation": _annotation(p.annotation), "required": p.default is p.empty}
            if p.default is not p.empty:
                entry["default"] = repr(p.default)
                if _ADDRESS_REPR.search(entry["default"]):
                    raise ValueError(f"hook {name!r}: the default of {p.name!r} has no stable repr: {entry['default']}")
            described[p.name] = entry
        out[name] = {
            "params": described,
            "returns": _annotation(sig.return_annotation),
            "firstresult": bool(opts.get("firstresult", False)),
            "historic": bool(opts.get("historic", False)),
        }
    return out


def protocol_surface(*protocols: type) -> dict[str, dict[str, str]]:
    """Per protocol, its public members: an attribute or a property by its annotation, a method by
    its signature."""
    out: dict[str, dict[str, str]] = {}
    for proto in protocols:
        members = {n: _annotation(a) for n, a in inspect.get_annotations(proto).items() if not n.startswith("_")}
        for n, value in vars(proto).items():
            if n.startswith("_"):
                continue
            if isinstance(value, property):
                getter = cast("Callable[..., object]", value.fget)  # a protocol property always has one
                members[n] = "property -> " + _annotation(inspect.get_annotations(getter).get("return", ""))
            elif callable(value):
                sig = inspect.signature(value)
                params = ", ".join(
                    p.name + (f": {_annotation(p.annotation)}" if p.annotation is not p.empty else "")
                    for p in sig.parameters.values()
                )
                members[n] = f"def ({params}) -> {_annotation(sig.return_annotation)}"
        out[proto.__name__] = dict(sorted(members.items()))
    return out


def names_surface() -> dict[str, str]:
    """The names a pack's metadata and markers carry."""
    return {"project": PROJECT_NAME, "plugin_group": PLUGIN_GROUP, "manifest_group": MANIFEST_GROUP}


def _strip_prose(node: Any, *, named: bool = False) -> Any:
    if isinstance(node, dict):
        if named:
            return {k: _strip_prose(v) for k, v in node.items()}
        return {k: _strip_prose(v, named=k in _NAMED) for k, v in node.items() if k not in _PROSE}
    if isinstance(node, list):
        return [_strip_prose(v) for v in node]
    return node


def manifest_surface(schema: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The manifest's JSON Schema without `$schema`, `$id` and prose; `schema` defaults to the live
    projection of `PackManifest`."""
    doc = dict(manifest_json_schema() if schema is None else schema)
    doc.pop("$schema", None)
    doc.pop("$id", None)
    stripped: dict[str, Any] = _strip_prose(doc)
    return stripped


def rules_surface(model: type[BaseModel] = PackManifest) -> dict[str, str]:
    """`model`'s validators: name -> `field <fields> <mode>` or `model <mode>`."""
    decorators = model.__pydantic_decorators__
    out = {n: f"field {','.join(d.info.fields)} {d.info.mode}" for n, d in decorators.field_validators.items()}
    out |= {n: f"model {d.info.mode}" for n, d in decorators.model_validators.items()}
    return dict(sorted(out.items()))


def live_surface() -> dict[str, Any]:
    """The surface this distribution defines now, as a ledger entry."""
    return {
        "contract": str(CONTRACT_VERSION),
        "names": names_surface(),
        "hooks": hook_surface(PackSpec),
        "protocols": protocol_surface(Contribution),
        "manifest": manifest_surface(),
        "manifest_rules": rules_surface(),
    }


def load_ledger() -> list[dict[str, Any]]:
    """The committed ledger's entries, oldest first."""
    return ledger_entries(files("pack_contracts").joinpath(LEDGER_RESOURCE).read_text(encoding="utf-8"))


def ledger_entries(text: str) -> list[dict[str, Any]]:
    """The entries of a ledger file's text (the committed one, or a released copy read from git)."""
    entries: list[dict[str, Any]] = json.loads(text)["entries"]
    return entries


def _kept(errors: list[str], where: str, old: Mapping[str, Any], new: Mapping[str, Any], *, extend: bool) -> None:
    """Every key of `old` is in `new` unchanged; `extend` allows new keys."""
    for key, was in old.items():
        if key not in new:
            errors.append(f"{where}: {key!r} was removed")
        elif new[key] != was:
            errors.append(f"{where}: {key!r} changed {json.dumps(was, sort_keys=True)} -> "
                          f"{json.dumps(new[key], sort_keys=True)}")  # fmt: skip
    if not extend:
        added = sorted(set(new) - set(old))
        if added:
            errors.append(f"{where}: {added} added")


def evolution_errors(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[str]:
    """Why `new` is NOT a compatible (minor) evolution of `old`; empty when it is."""
    errors: list[str] = []
    _kept(errors, "names", old["names"], new["names"], extend=False)
    for hook, was in old["hooks"].items():
        now = new["hooks"].get(hook)
        if now is None:
            errors.append(f"hook {hook!r} was removed")
            continue
        _kept(errors, f"hook {hook!r}", {k: v for k, v in was.items() if k != "params"},
              {k: v for k, v in now.items() if k != "params"}, extend=False)  # fmt: skip
        _kept(errors, f"hook {hook!r} parameters", was["params"], now["params"], extend=True)
        added = sorted(p for p, d in now["params"].items() if p not in was["params"] and d["required"])
        if added:
            errors.append(f"hook {hook!r}: new required parameters {added} (a minor adds only defaulted ones)")
    for proto, was in old["protocols"].items():
        if proto not in new["protocols"]:
            errors.append(f"protocol {proto!r} was removed")
        else:  # a member added to a protocol is one every existing implementation lacks
            _kept(errors, f"protocol {proto!r}", was, new["protocols"][proto], extend=False)
    _kept(errors, "manifest rules", old["manifest_rules"], new["manifest_rules"], extend=False)
    was_m, now_m = old["manifest"], new["manifest"]
    if sorted(now_m.get("required", [])) != sorted(was_m.get("required", [])):
        errors.append(f"manifest: required fields changed {was_m.get('required')} -> {now_m.get('required')}")
    rest = {"required", "properties", "$defs"}
    _kept(errors, "manifest", {k: v for k, v in was_m.items() if k not in rest},
          {k: v for k, v in now_m.items() if k not in rest}, extend=False)  # fmt: skip
    _kept(errors, "manifest property", was_m.get("properties", {}), now_m.get("properties", {}), extend=True)
    _kept(errors, "manifest definition", was_m.get("$defs", {}), now_m.get("$defs", {}), extend=True)
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
    if {k: v for k, v in entries[-1].items() if k != "contract"} != {k: v for k, v in live.items() if k != "contract"}:
        errors.append(
            f"the live surface differs from the ledger's {versions[-1]} entry: enter the change as a new "
            "contract version (`python -m pack_contracts surface`)"
        )
    return errors


def append_only_errors(
    released: Sequence[Mapping[str, Any]], current: Sequence[Mapping[str, Any]], *, ref: str
) -> list[str]:
    """Why `current` is not `released` (the ledger at `ref`) with entries appended; empty when it is."""
    errors: list[str] = []
    for i, entry in enumerate(released):
        if i >= len(current):
            errors.append(f"{ref}: entry {entry.get('contract')} was removed")
        elif current[i] != entry:
            errors.append(f"{ref}: entry {entry.get('contract')} was edited; enter a change as a new version")
    return errors
