"""The versioning rule, enforced: the committed ledger holds it and matches the live surface, and
every way to break it is proven to be caught."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import BaseModel, Field

from pack_contracts.contract import CONTRACT_VERSION, ContractVersion
from pack_contracts.hooks import PackSpec, hookspec
from pack_contracts.surface import (
    evolution_errors,
    hook_surface,
    live_surface,
    load_ledger,
    manifest_surface,
    verify_ledger,
)


def test_the_committed_ledger_holds_the_rule_and_matches_the_live_surface() -> None:
    entries = load_ledger()
    assert verify_ledger(entries, live_surface()) == []
    assert entries[-1]["contract"] == str(CONTRACT_VERSION)


def test_the_live_surface_is_the_hookspecs_and_the_manifest_fields() -> None:
    assert hook_surface(PackSpec) == {
        "register_contributions": {"required": ["register"], "defaulted": {}, "firstresult": False, "historic": False}
    }
    assert manifest_surface() == {
        "required": ["contract", "id", "provides", "tier", "version"],
        "optional": ["description", "needs", "title"],
    }


class _Spec:
    @hookspec(firstresult=True)
    def pick(self, a: Any, b: Any = None) -> Any: ...

    def helper(self) -> None:  # not a hookspec: not in the surface
        ...


def test_hook_surface_reads_options_and_defaults_and_skips_plain_methods() -> None:
    assert hook_surface(_Spec) == {"pick": {"required": ["a"], "defaulted": {"b": "None"}, "firstresult": True,
                                            "historic": False}}  # fmt: skip


@pytest.mark.parametrize("sig", ["self, *, a", "self, *a", "self, **a"])
def test_hook_surface_refuses_parameters_pluggy_never_passes(sig: str) -> None:
    ns: dict[str, Any] = {"hookspec": hookspec}
    exec(f"class S:\n    @hookspec\n    def h({sig}): ...\n", ns)
    with pytest.raises(ValueError, match="not passed by pluggy"):
        hook_surface(ns["S"])


def test_manifest_surface_uses_the_file_names() -> None:
    class M(BaseModel):
        a: int
        b: int = Field(default=0, alias="B")

    assert manifest_surface(M) == {"required": ["a"], "optional": ["B"]}


def _entry(version: str = "1.0", **hooks: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract": version,
        "hooks": hooks or {"h": {"required": ["r"], "defaulted": {"d": "1"}, "firstresult": False, "historic": False}},
        "manifest": {"required": ["id"], "optional": ["title"]},
    }


def _evolve(change: Any) -> list[str]:
    old = _entry()
    new = copy.deepcopy(old)
    change(new)
    return evolution_errors(old, new)


def test_additions_are_a_compatible_minor() -> None:
    def add(new: dict[str, Any]) -> None:
        new["hooks"]["h"]["defaulted"]["e"] = "'x'"
        new["hooks"]["other"] = {"required": ["anything"], "defaulted": {}, "firstresult": True, "historic": False}
        new["manifest"]["optional"].append("colour")

    assert _evolve(add) == []


@pytest.mark.parametrize(
    ("change", "needle"),
    [
        (lambda n: n["hooks"].pop("h"), "removed"),
        (lambda n: n["hooks"]["h"]["required"].append("x"), "new required parameters ['x']"),
        (lambda n: n["hooks"]["h"]["required"].remove("r"), "required parameter 'r' removed"),
        (lambda n: (n["hooks"]["h"]["required"].remove("r"), n["hooks"]["h"]["defaulted"].update(r="0")),
         "required parameter 'r' made defaulted"),
        (lambda n: n["hooks"]["h"]["defaulted"].pop("d"), "defaulted parameter 'd' removed"),
        (lambda n: (n["hooks"]["h"]["defaulted"].pop("d"), n["hooks"]["h"]["required"].append("d")),
         "defaulted parameter 'd' made required"),
        (lambda n: n["hooks"]["h"]["defaulted"].update(d="2"), "default of 'd' changed 1 -> 2"),
        (lambda n: n["hooks"]["h"].update(firstresult=True), "firstresult changed"),
        (lambda n: n["hooks"]["h"].update(historic=True), "historic changed"),
        (lambda n: n["manifest"]["required"].append("version"), "required fields changed"),
        (lambda n: n["manifest"]["optional"].remove("title"), "optional fields removed ['title']"),
        (lambda n: (n["manifest"]["optional"].remove("title"), n["manifest"]["required"].append("title")),
         "required fields changed"),
    ],
)  # fmt: skip
def test_every_breaking_change_is_caught(change: Any, needle: str) -> None:
    errors = _evolve(change)
    assert errors and any(needle in e for e in errors), errors


def test_a_ledger_verifies_across_a_minor_and_a_major() -> None:
    v10 = _entry("1.0")
    v11 = copy.deepcopy(v10) | {"contract": "1.1"}
    v11["hooks"]["h"]["defaulted"]["e"] = "None"
    v20 = _entry("2.0", h={"required": ["z"], "defaulted": {}, "firstresult": True, "historic": False})
    assert verify_ledger([v10, v11, v20], v20, ContractVersion(2, 0)) == []


def test_a_breaking_change_at_a_minor_fails_the_ledger() -> None:
    v10 = _entry("1.0")
    v11 = _entry("1.1", h={"required": ["z"], "defaulted": {}, "firstresult": False, "historic": False})
    errors = verify_ledger([v10, v11], v11, ContractVersion(1, 1))
    assert errors and all(e.startswith("1.0 -> 1.1: ") for e in errors), errors


@pytest.mark.parametrize(
    ("versions", "needle"),
    [(["1.0", "1.0"], "does not follow"), (["1.1", "1.0"], "does not follow"),
     (["1.0", "3.0"], "a new major is the next integer"), (["1.0", "2.1"], "a new major is the next integer")],
)  # fmt: skip
def test_ledger_versions_must_step_forward(versions: list[str], needle: str) -> None:
    entries = [_entry(v) for v in versions]
    errors = verify_ledger(entries, entries[-1], ContractVersion.parse(versions[-1]))
    assert any(needle in e for e in errors), errors


def test_the_ledger_must_end_at_the_contract_and_match_the_live_surface() -> None:
    v10 = _entry("1.0")
    assert any("the contract is 1.1" in e for e in verify_ledger([v10], v10, ContractVersion(1, 1)))
    drifted = copy.deepcopy(v10)
    drifted["hooks"]["h"]["defaulted"]["e"] = "None"
    assert any("live surface differs" in e for e in verify_ledger([v10], drifted, ContractVersion(1, 0)))
    assert verify_ledger([], v10) == ["the ledger is empty"]


def test_changing_the_real_hookspec_without_a_ledger_entry_fails() -> None:
    """Must-fire on the real surface: a defaulted parameter added to `PackSpec` (a legal minor) still
    fails until the ledger records it as a new version."""

    class Grown(PackSpec):
        @hookspec
        def register_contributions(self, register: Any, extra: Any = None) -> None: ...

    live = live_surface() | {"hooks": hook_surface(Grown)}
    errors = verify_ledger(load_ledger(), live)
    assert any("live surface differs" in e for e in errors), errors
    grown_entry = live | {"contract": "1.1"}
    assert verify_ledger([*load_ledger(), grown_entry], live, ContractVersion(1, 1)) == []
