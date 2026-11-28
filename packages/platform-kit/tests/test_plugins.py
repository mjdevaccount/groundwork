"""platform_kit.plugins carries the R1-R10 conformance suite, plus the loader's own surface:
`Loaded` origin + series, the boot log, R1's fresh-manager refusal, and `Registry.freeze()`."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pluggy
import pytest

from platform_kit.plugins import STAGES, Loaded, PluginLoadError, collect, load
from platform_kit.registry import Registry
from platform_kit.testing.plugin_conformance import FakeEntryPoint, PluginConformance

GROUP = "t_widgets"
hookspec = pluggy.HookspecMarker(GROUP)
hookimpl = pluggy.HookimplMarker(GROUP)


@dataclass(frozen=True)
class Widget:
    id: str


class Spec:
    @hookspec
    def register_widgets(self, register) -> None:
        """Call register(widget) per widget."""


class TestPlatformKitLoader(PluginConformance):
    error = PluginLoadError
    hookimpl = hookimpl
    hook = "register_widgets"

    def thing(self, key: str) -> Widget:
        return Widget(key)

    def run(self, *, builtins, entry_points, pin):
        pm = pluggy.PluginManager(GROUP)
        loaded = load(pm, group=GROUP, hookspecs=Spec, builtins=builtins, pin=pin, entry_points=entry_points)
        store: Registry[Widget] = Registry("widget")
        collect(pm, "register_widgets", store, loaded=loaded, kind=Widget)
        return loaded.plugins, store, store.add


def _plugin(*keys: str) -> object:
    return TestPlatformKitLoader().plugin(*keys)


def test_loaded_names_where_each_plugin_came_from_and_logs_it(caplog: pytest.LogCaptureFixture) -> None:
    eps = [FakeEntryPoint("extra", _plugin("e"), dist_name="acme-widgets", version="1.2.3")]
    with caplog.at_level(logging.INFO, logger="platform_kit.plugins"):
        loaded = load(pluggy.PluginManager(GROUP), group=GROUP, hookspecs=Spec, builtins=[("core", _plugin("c"))],
                      entry_points=lambda: eps)  # fmt: skip
    assert loaded == Loaded(GROUP, ("core", "extra"), loaded.origin)
    assert dict(loaded.origin) == {"core": "builtin", "extra": "acme-widgets==1.2.3"}
    assert loaded.series() == [
        ("plugins_loaded", {"group": GROUP, "plugin": "core", "origin": "builtin"}, 1.0),
        ("plugins_loaded", {"group": GROUP, "plugin": "extra", "origin": "acme-widgets==1.2.3"}, 1.0),
    ]
    assert "plugins_loaded group=t_widgets names=core,extra" in caplog.text


def test_load_refuses_a_manager_that_already_holds_plugins() -> None:
    pm = pluggy.PluginManager(GROUP)
    pm.register(_plugin("early"), name="early")
    with pytest.raises(ValueError, match="fresh PluginManager"):
        load(pm, group=GROUP, hookspecs=Spec, entry_points=lambda: ())


def test_an_installed_plugin_may_not_shadow_a_builtin() -> None:
    eps = [FakeEntryPoint("core", _plugin("x"))]
    with pytest.raises(PluginLoadError) as ei:
        load(pluggy.PluginManager(GROUP), group=GROUP, hookspecs=Spec, builtins=[("core", _plugin("c"))],
             entry_points=lambda: eps)  # fmt: skip
    assert ei.value.stage == "duplicate" and ei.value.plugin == "core"


def test_a_pin_may_name_a_builtin() -> None:
    loaded = load(pluggy.PluginManager(GROUP), group=GROUP, hookspecs=Spec, builtins=[("core", _plugin("c"))],
                  pin="core", entry_points=lambda: [FakeEntryPoint("a", _plugin("a"))])  # fmt: skip
    assert loaded.plugins == ("core",)


def test_collect_needs_a_known_hook_and_stage_is_closed() -> None:
    pm = pluggy.PluginManager(GROUP)
    loaded = load(pm, group=GROUP, hookspecs=Spec, entry_points=lambda: ())
    with pytest.raises(ValueError, match="no hook"):
        collect(pm, "register_gadgets", Registry("widget"), loaded=loaded)
    with pytest.raises(ValueError, match="unknown plugin load stage"):
        PluginLoadError(GROUP, "p", "exploded", "x")  # type: ignore[arg-type]
    assert set(STAGES) == {"import", "register", "hook", "duplicate", "pin", "pending"}


def test_collect_can_leave_the_store_open_for_a_second_hook() -> None:
    pm = pluggy.PluginManager(GROUP)
    loaded = load(pm, group=GROUP, hookspecs=Spec, builtins=[("core", _plugin("c"))], entry_points=lambda: ())
    store: Registry[Widget] = Registry("widget")
    collect(pm, "register_widgets", store, loaded=loaded, freeze=False)
    assert not store.frozen
    store.add(Widget("more"))
    store.freeze()
    with pytest.raises(RuntimeError, match="frozen"):
        store["late"] = Widget("late")


def test_freeze_is_one_way_and_empty_is_writable() -> None:
    reg: Registry[Widget] = Registry("widget")
    reg.add(Widget("a"))
    reg.freeze()
    with pytest.raises(RuntimeError, match="widget registry is frozen: 'b' arrived after load"):
        reg.add(Widget("b"))
    with pytest.raises(RuntimeError, match="frozen"):
        reg.add(Widget("a"))  # even an identical re-add: frozen means no writes
    assert reg.frozen and list(reg) == ["a"] and reg.key_of(Widget("z")) == "z"
    fresh = reg.empty()
    assert not fresh.frozen
    fresh.add(Widget("b"))


class TestLoaderWithoutStageCheck(TestPlatformKitLoader):
    """The mixin's `checks_stage = False` path: a loader whose error carries no stage."""

    checks_stage = False


def test_load_needs_a_group() -> None:
    with pytest.raises(ValueError, match="needs a group"):
        load(pluggy.PluginManager(GROUP), group=" ", hookspecs=Spec, entry_points=lambda: ())


def test_the_same_object_under_two_names_is_refused_at_register() -> None:
    p = _plugin("x")
    with pytest.raises(PluginLoadError) as ei:
        load(pluggy.PluginManager(GROUP), group=GROUP, hookspecs=Spec, builtins=[("a", p), ("b", p)],
             entry_points=lambda: ())  # fmt: skip
    assert ei.value.stage == "register" and ei.value.plugin == "b"


def test_two_entry_points_sharing_a_name_are_refused() -> None:
    eps = [FakeEntryPoint("twin", _plugin("a")), FakeEntryPoint("twin", _plugin("b"))]
    with pytest.raises(PluginLoadError) as ei:
        load(pluggy.PluginManager(GROUP), group=GROUP, hookspecs=Spec, entry_points=lambda: eps)
    assert ei.value.stage == "duplicate"


class _NoHooks:
    """A plugin with no hookimpl: loads, and contributes nothing to the collected store."""


def test_a_plugin_without_the_hook_contributes_nothing() -> None:
    pm = pluggy.PluginManager(GROUP)
    loaded = load(pm, group=GROUP, hookspecs=Spec, builtins=[("core", _plugin("c")), ("quiet", _NoHooks())],
                  entry_points=lambda: ())  # fmt: skip
    store: Registry[Widget] = Registry("widget")
    collect(pm, "register_widgets", store, loaded=loaded, kind=Widget)
    assert list(store) == ["c"]


def test_a_registered_thing_without_a_key_names_the_plugin() -> None:
    class Bare:
        @hookimpl
        def register_widgets(self, register: Any) -> None:
            register(object())

    pm = pluggy.PluginManager(GROUP)
    loaded = load(pm, group=GROUP, hookspecs=Spec, builtins=[("bare", Bare())], entry_points=lambda: ())
    store: Registry[Widget] = Registry("widget")
    with pytest.raises(PluginLoadError, match="no key") as ei:
        collect(pm, "register_widgets", store, loaded=loaded)
    assert ei.value.plugin == "bare"


class _DefaultsSpec:
    @hookspec
    def register_widgets(self, register, flavour: str = "plain") -> None:
        """A minor added `flavour`, defaulted."""

    @hookspec
    def register_gadgets(self, register, size) -> None:
        """`size` has no default, so collect cannot pass it."""


def test_collect_fills_hookspec_defaults_and_passes_only_named_arguments() -> None:
    class Old:
        @hookimpl
        def register_widgets(self, register) -> None:
            register(Widget("old"))

    class New:
        @hookimpl
        def register_widgets(self, register, flavour) -> None:
            register(Widget(f"new-{flavour}"))

    pm = pluggy.PluginManager(GROUP)
    loaded = load(pm, group=GROUP, hookspecs=_DefaultsSpec, builtins=[("old", Old()), ("new", New())],
                  entry_points=lambda: ())  # fmt: skip
    store: Registry[Widget] = Registry("widget")
    collect(pm, "register_widgets", store, loaded=loaded, kind=Widget)
    assert list(store) == ["old", "new-plain"]


def test_collect_refuses_an_argument_it_cannot_pass() -> None:
    class Sized:
        @hookimpl
        def register_gadgets(self, register, size) -> None:
            raise AssertionError("never called")

    pm = pluggy.PluginManager(GROUP)
    loaded = load(pm, group=GROUP, hookspecs=_DefaultsSpec, builtins=[("sized", Sized())], entry_points=lambda: ())
    with pytest.raises(PluginLoadError, match=r"takes \['register', 'size'\]") as ei:
        collect(pm, "register_gadgets", Registry("gadget"), loaded=loaded)
    assert ei.value.stage == "hook" and ei.value.plugin == "sized"


def test_collect_refuses_an_impl_that_cannot_register() -> None:
    """A hookimpl that does not take `register` would load and contribute nothing (R7's shape)."""

    class Quiet:
        @hookimpl
        def register_widgets(self) -> None:
            raise AssertionError("never called")

    pm = pluggy.PluginManager(GROUP)
    loaded = load(pm, group=GROUP, hookspecs=_DefaultsSpec, builtins=[("q", Quiet())], entry_points=lambda: ())
    with pytest.raises(PluginLoadError, match="must take `register`") as ei:
        collect(pm, "register_widgets", Registry("widget"), loaded=loaded)
    assert ei.value.stage == "hook"
