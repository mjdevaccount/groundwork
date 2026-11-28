"""The versioning rule, enforced: the committed ledger holds it and matches the live surface, every
released copy of the ledger is a prefix of it, and every way to break the rule is proven to be caught."""

from __future__ import annotations

import copy
import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import Field

from pack_contracts.contract import CONTRACT_VERSION, ContractVersion
from pack_contracts.hooks import Contribution, PackSpec, hookspec
from pack_contracts.manifest import PackManifest
from pack_contracts.surface import (
    append_only_errors,
    evolution_errors,
    hook_surface,
    ledger_entries,
    live_surface,
    load_ledger,
    manifest_surface,
    names_surface,
    protocol_surface,
    verify_ledger,
)

if TYPE_CHECKING:
    from collections.abc import Callable

LEDGER_PATH = "packages/pack-contracts/src/pack_contracts/surface-ledger.json"
#: set in CI's locked pytest job (full history): a checkout without the released ledgers FAILS
#: instead of skipping, so the append-only gate cannot go quiet by a shallow clone
HISTORY_REQUIRED = "PACK_CONTRACTS_LEDGER_HISTORY_REQUIRED"


def test_the_committed_ledger_holds_the_rule_and_matches_the_live_surface() -> None:
    entries = load_ledger()
    assert verify_ledger(entries, live_surface()) == []
    assert entries[-1]["contract"] == str(CONTRACT_VERSION)


def test_the_live_surface_is_every_name_hook_protocol_and_the_manifest_schema() -> None:
    live = live_surface()
    assert live["names"] == {"project": "pack", "plugin_group": "pack_contracts.plugin",
                             "manifest_group": "pack_contracts.manifest"}  # fmt: skip
    assert live["hooks"] == {
        "register_contributions": {
            "params": {"register": {"annotation": "Callable[[Contribution], None]", "required": True}},
            "returns": "None",
            "firstresult": False,
            "historic": False,
        }
    }
    assert live["protocols"] == {"Contribution": {"kind": "property -> str", "name": "property -> str"}}
    manifest = live["manifest"]
    assert set(manifest["required"]) == {"contract", "id", "provides", "tier", "version"}
    assert manifest["$defs"]["Tier"]["enum"] == ["declared", "loads", "conformant"]
    assert manifest["properties"]["id"]["pattern"] == r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$"
    assert "description" not in manifest["properties"]["id"] and "$id" not in manifest


class _Spec:
    @hookspec(firstresult=True)
    def pick(self, a: int, b: str | None = None) -> bool:
        return bool(a or b)

    def helper(self) -> None:  # not a hookspec: not in the surface
        ...


def test_hook_surface_reads_annotations_options_and_defaults_and_skips_plain_methods() -> None:
    assert hook_surface(_Spec) == {
        "pick": {
            "params": {"a": {"annotation": "int", "required": True},
                       "b": {"annotation": "str | None", "required": False, "default": "None"}},
            "returns": "bool",
            "firstresult": True,
            "historic": False,
        }
    }  # fmt: skip


@pytest.mark.parametrize("sig", ["self, *, a", "self, *a", "self, **a"])
def test_hook_surface_refuses_parameters_pluggy_never_passes(sig: str) -> None:
    ns: dict[str, Any] = {"hookspec": hookspec}
    exec(f"class S:\n    @hookspec\n    def h({sig}): ...\n", ns)
    with pytest.raises(ValueError, match="not passed by pluggy"):
        hook_surface(ns["S"])


def test_hook_surface_refuses_a_default_with_no_stable_repr() -> None:
    ns: dict[str, Any] = {"hookspec": hookspec, "SENTINEL": object()}
    exec("class S:\n    @hookspec\n    def h(self, a=SENTINEL): ...\n", ns)
    with pytest.raises(ValueError, match="no stable repr"):
        hook_surface(ns["S"])


def test_hook_surface_records_an_unannotated_parameter_as_empty() -> None:
    ns: dict[str, Any] = {"hookspec": hookspec}
    exec("class S:\n    @hookspec\n    def h(self, a): ...\n", ns)
    assert hook_surface(ns["S"])["h"]["params"] == {"a": {"annotation": "", "required": True}}
    assert hook_surface(ns["S"])["h"]["returns"] == ""


def test_protocol_surface_reads_attributes_properties_and_methods() -> None:
    class P:
        size: int = 3  # an annotated attribute with a value: read once, by its annotation
        _private: int

        @property
        def kind(self) -> str:
            return "p"

        def render(self, width: int) -> str:
            return "-" * width

    assert protocol_surface(P) == {"P": {"kind": "property -> str", "render": "def (self, width: int) -> str",
                                         "size": "int"}}  # fmt: skip
    assert protocol_surface(Contribution) == live_surface()["protocols"]


def test_names_surface_is_the_three_names() -> None:
    assert set(names_surface()) == {"project", "plugin_group", "manifest_group"}


def test_manifest_surface_strips_prose_but_keeps_property_names() -> None:
    doc = {"$id": "x", "$schema": "y", "title": "T", "description": "D",
           "properties": {"title": {"type": "string", "title": "Title", "description": "d"}},
           "$defs": {"description": {"enum": ["a"], "title": "E"}}}  # fmt: skip
    assert manifest_surface(doc) == {"properties": {"title": {"type": "string"}},
                                     "$defs": {"description": {"enum": ["a"]}}}  # fmt: skip


def test_manifest_surface_sees_a_type_a_pattern_and_an_enum_change() -> None:
    """The breaking changes a names-only surface missed: each one now changes the surface."""

    class Retyped(PackManifest):
        version: int = Field(description="x")  # type: ignore[assignment]

    class Narrowed(PackManifest):
        id: str = Field(pattern="^[a-z]{1,8}$")

    base = manifest_surface()
    for model in (Retyped, Narrowed):
        changed = manifest_surface(model.model_json_schema())
        assert evolution_errors(_real() | {"manifest": base}, _real() | {"manifest": changed}), model


def _real() -> dict[str, Any]:
    return copy.deepcopy(live_surface())


def _evolve(change: Callable[[dict[str, Any]], Any]) -> list[str]:
    old = _real()
    new = copy.deepcopy(old)
    change(new)
    return evolution_errors(old, new)


def _hook(n: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = n["hooks"]["register_contributions"]
    return out


def test_additions_are_a_compatible_minor() -> None:
    def add(new: dict[str, Any]) -> None:
        _hook(new)["params"]["extra"] = {"annotation": "str", "required": False, "default": "'x'"}
        new["hooks"]["other"] = {"params": {"anything": {"annotation": "int", "required": True}}, "returns": "None",
                                 "firstresult": True, "historic": False}  # fmt: skip
        new["protocols"]["Other"] = {"x": "int"}
        new["manifest"]["properties"]["colour"] = {"type": "string"}
        new["manifest"]["$defs"]["Colour"] = {"enum": ["red"]}

    assert _evolve(add) == []


@pytest.mark.parametrize(
    ("change", "needle"),
    [
        (lambda n: n["names"].update(project="packs"), "names: 'project' changed"),
        (lambda n: n["names"].update(plugin_group="x"), "names: 'plugin_group' changed"),
        (lambda n: n["names"].pop("manifest_group"), "names: 'manifest_group' was removed"),
        (lambda n: n["names"].update(extra="x"), "names: ['extra'] added"),
        (lambda n: n["hooks"].pop("register_contributions"), "was removed"),
        (lambda n: _hook(n)["params"].update(x={"annotation": "int", "required": True}),
         "new required parameters ['x']"),
        (lambda n: _hook(n)["params"].pop("register"), "parameters: 'register' was removed"),
        (lambda n: _hook(n)["params"].update(reg=_hook(n)["params"].pop("register")), "'register' was removed"),
        (lambda n: _hook(n)["params"]["register"].update(annotation="Callable[[str], None]"),
         "parameters: 'register' changed"),
        (lambda n: _hook(n)["params"]["register"].update(required=False, default="None"),
         "parameters: 'register' changed"),
        (lambda n: _hook(n).update(returns="bool"), "'returns' changed"),
        (lambda n: _hook(n).update(firstresult=True), "'firstresult' changed"),
        (lambda n: _hook(n).update(historic=True), "'historic' changed"),
        (lambda n: n["protocols"].pop("Contribution"), "protocol 'Contribution' was removed"),
        (lambda n: n["protocols"]["Contribution"].update(kind="property -> int"), "'kind' changed"),
        (lambda n: n["protocols"]["Contribution"].update(extra="int"), "['extra'] added"),
        (lambda n: n["manifest"]["required"].append("title"), "required fields changed"),
        (lambda n: n["manifest"]["required"].remove("tier"), "required fields changed"),
        (lambda n: n["manifest"]["properties"].pop("title"), "manifest property: 'title' was removed"),
        (lambda n: n["manifest"]["properties"]["id"].update(maxLength=8), "manifest property: 'id' changed"),
        (lambda n: n["manifest"]["properties"]["version"].update(type="integer"), "'version' changed"),
        (lambda n: n["manifest"]["$defs"]["Tier"]["enum"].remove("declared"), "manifest definition: 'Tier'"),
        (lambda n: n["manifest"].update(additionalProperties=True), "manifest: 'additionalProperties' changed"),
    ],
)  # fmt: skip
def test_every_breaking_change_is_caught(change: Callable[[dict[str, Any]], Any], needle: str) -> None:
    errors = _evolve(change)
    assert errors and any(needle in e for e in errors), errors


def _versioned(version: str, entry: dict[str, Any] | None = None) -> dict[str, Any]:
    return (entry or _real()) | {"contract": version}


def test_a_ledger_verifies_across_a_minor_and_a_major() -> None:
    v10 = _versioned("1.0")
    v11 = _versioned("1.1", copy.deepcopy(v10))
    _hook(v11)["params"]["extra"] = {"annotation": "str", "required": False, "default": "None"}
    v20 = _versioned("2.0", copy.deepcopy(v11))
    _hook(v20)["params"]["register"]["annotation"] = "Callable[[object], None]"
    assert verify_ledger([v10, v11, v20], v20, ContractVersion(2, 0)) == []


def test_a_breaking_change_at_a_minor_fails_the_ledger() -> None:
    v10 = _versioned("1.0")
    v11 = _versioned("1.1", copy.deepcopy(v10))
    v11["names"]["project"] = "renamed"
    errors = verify_ledger([v10, v11], v11, ContractVersion(1, 1))
    assert errors and all(e.startswith("1.0 -> 1.1: ") for e in errors), errors


@pytest.mark.parametrize(
    ("versions", "needle"),
    [(["1.0", "1.0"], "does not follow"), (["1.1", "1.0"], "does not follow"),
     (["1.0", "3.0"], "a new major is the next integer"), (["1.0", "2.1"], "a new major is the next integer")],
)  # fmt: skip
def test_ledger_versions_must_step_forward(versions: list[str], needle: str) -> None:
    entries = [_versioned(v) for v in versions]
    errors = verify_ledger(entries, entries[-1], ContractVersion.parse(versions[-1]))
    assert any(needle in e for e in errors), errors


def test_the_ledger_must_end_at_the_contract_and_match_the_live_surface() -> None:
    v10 = _versioned("1.0")
    assert any("the contract is 1.1" in e for e in verify_ledger([v10], v10, ContractVersion(1, 1)))
    drifted = copy.deepcopy(v10)
    drifted["manifest"]["properties"]["colour"] = {"type": "string"}
    assert any("live surface differs" in e for e in verify_ledger([v10], drifted, ContractVersion(1, 0)))
    assert verify_ledger([], v10) == ["the ledger is empty"]


def test_changing_the_real_hookspec_without_a_ledger_entry_fails() -> None:
    """Must-fire on the real surface: a defaulted parameter added to `PackSpec` (a legal minor) still
    fails until the ledger records it as a new version."""

    class Grown(PackSpec):
        @hookspec
        def register_contributions(self, register: Callable[[Contribution], None], extra: Any = None) -> None: ...

    live = live_surface() | {"hooks": hook_surface(Grown)}
    errors = verify_ledger(load_ledger(), live)
    assert any("live surface differs" in e for e in errors), errors
    grown_entry = live | {"contract": "1.1"}
    assert verify_ledger([*load_ledger(), grown_entry], live, ContractVersion(1, 1)) == []


def test_append_only_holds_a_prefix_and_refuses_an_edit_or_a_removal() -> None:
    v10, v11 = _versioned("1.0"), _versioned("1.1")
    assert append_only_errors([v10], [v10, v11], ref="t") == []
    edited = copy.deepcopy(v10)
    _hook(edited)["params"]["reg"] = _hook(edited)["params"].pop("register")
    assert append_only_errors([v10], [edited, v11], ref="t") == [
        "t: entry 1.0 was edited; enter a change as a new version"
    ]
    assert append_only_errors([v10, v11], [v10], ref="t") == ["t: entry 1.1 was removed"]


# --- the released ledgers, read from git ---------------------------------------------------------


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    git = shutil.which("git")
    assert git is not None
    return subprocess.run([git, *args], capture_output=True, text=True, check=False, cwd=Path(__file__).parent)


def _released_refs() -> list[str]:
    """`origin/base` (when fetched) and every `pack-contracts-v*` tag."""
    refs = [t for t in _git("tag", "--list", "pack-contracts-v*").stdout.split() if t]
    if _git("rev-parse", "--verify", "--quiet", "refs/remotes/origin/base").returncode == 0:
        refs.append("origin/base")
    return refs


def test_every_released_ledger_is_a_prefix_of_the_committed_one() -> None:
    """The append-only rule over real history: an entry edited in place (which `verify_ledger` alone
    cannot see, since both copies change together) fails against the copy at every release tag and
    on the default branch. A ref that predates the ledger has nothing to compare."""
    required = os.environ.get(HISTORY_REQUIRED) == "1"
    if shutil.which("git") is None or _git("rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
        if required:
            pytest.fail(f"{HISTORY_REQUIRED}=1 but this is not a git checkout")
        pytest.skip("not a git checkout: the released ledgers are not reachable")
    if _git("rev-parse", "--is-shallow-repository").stdout.strip() == "true":
        if required:
            pytest.fail(f"{HISTORY_REQUIRED}=1 but the clone is shallow (fetch-depth: 0)")
        pytest.skip("a shallow clone: the released ledgers are not reachable")
    current = load_ledger()
    errors: list[str] = []
    for ref in _released_refs():
        shown = _git("show", f"{ref}:{LEDGER_PATH}")
        if shown.returncode != 0:  # this ref predates the ledger
            continue
        errors += append_only_errors(ledger_entries(shown.stdout), current, ref=ref)
    assert errors == []
