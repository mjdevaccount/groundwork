"""The pluggy surface: the synthetic pack implements `PackSpec` with this package's markers alone, and
pluggy 1.7 behaves the way the versioning rule says it does (defaults filled, required not)."""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING, Any

import pluggy
import pytest

from pack_contracts.hooks import (
    PLUGIN_GROUP,
    PROJECT_NAME,
    Contribution,
    PackSpec,
    contribution_key,
    hookimpl,
    hookspec,
)
from pack_contracts.manifest import PackManifest

if TYPE_CHECKING:
    from collections.abc import Callable


def _manager() -> pluggy.PluginManager:
    pm = pluggy.PluginManager(PROJECT_NAME)
    pm.add_hookspecs(PackSpec)
    return pm


def test_the_markers_carry_the_project_name() -> None:
    assert hookspec.project_name == PROJECT_NAME == hookimpl.project_name
    assert PLUGIN_GROUP == "pack_contracts.plugin"


def test_the_example_pack_registers_exactly_what_its_manifest_provides(install: Callable[..., Any]) -> None:
    site = install()
    (ep,) = site.entry_points(PLUGIN_GROUP)
    plugin = ep.load()  # the plugin group IS imported; that is the loader's job, after the manifest
    manifest = PackManifest.model_validate(tomllib.loads((site.package / "pack.toml").read_text(encoding="utf-8")))
    pm = _manager()
    pm.register(plugin, name=ep.name)
    pm.check_pending()
    got: list[Contribution] = []
    pm.hook.register_contributions(register=got.append)
    assert all(isinstance(c, Contribution) for c in got)
    assert {contribution_key(c) for c in got} == manifest.provided()


def test_a_misspelled_hookimpl_is_caught_by_check_pending() -> None:
    class Typo:
        @hookimpl
        def register_contribution(self, register: Any) -> None:  # one letter short
            raise AssertionError("never called")

    pm = _manager()
    pm.register(Typo(), name="typo")
    with pytest.raises(pluggy.PluginValidationError, match="unknown hook"):
        pm.check_pending()


def test_an_object_without_kind_and_name_is_not_a_contribution() -> None:
    assert not isinstance(object(), Contribution)


# -- pluggy 1.7 behaves the way pack_contracts.contract's rule assumes ------------------------------
class _V10:
    @hookspec
    def register_contributions(self, register: Any) -> None: ...


class _V11:  # a MINOR: one new DEFAULTED parameter
    @hookspec
    def register_contributions(self, register: Any, locale: str = "en") -> None: ...


class _V20:  # a MAJOR: one new REQUIRED parameter
    @hookspec
    def register_contributions(self, register: Any, locale: Any) -> None: ...


class _OldPack:
    @hookimpl
    def register_contributions(self, register: Any) -> None:
        register(("old", None))


class _NewPack:
    @hookimpl
    def register_contributions(self, register: Any, locale: str) -> None:
        register(("new", locale))


def _call(spec: type, plugins: list[object], **kwargs: Any) -> list[Any]:
    pm = pluggy.PluginManager(PROJECT_NAME)
    pm.add_hookspecs(spec)
    for i, p in enumerate(plugins):
        pm.register(p, name=f"p{i}")
    got: list[Any] = []
    pm.hook.register_contributions(register=got.append, **kwargs)
    return sorted(got, key=str)


def test_a_minor_keeps_old_packs_and_old_callers_working() -> None:
    assert _call(_V10, [_OldPack()]) == [("old", None)]
    assert _call(_V11, [_OldPack(), _NewPack()]) == [("new", "en"), ("old", None)]  # the default is filled
    assert _call(_V11, [_OldPack(), _NewPack()], locale="fr") == [("new", "fr"), ("old", None)]


def test_a_new_required_parameter_breaks_the_old_caller() -> None:
    with pytest.warns(UserWarning, match="cannot be found in this hook call"), pytest.raises(pluggy.HookCallError):
        _call(_V20, [_NewPack()])


def test_a_hookimpl_naming_a_parameter_the_spec_lacks_is_refused() -> None:
    pm = pluggy.PluginManager(PROJECT_NAME)
    pm.add_hookspecs(_V10)
    with pytest.raises(pluggy.PluginValidationError, match="locale"):
        pm.register(_NewPack(), name="new")
