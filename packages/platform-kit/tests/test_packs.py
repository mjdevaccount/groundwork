"""platform_kit.packs: every step refuses loudly, the report names every pack's state, and a host
with no packs boots. The packs are synthetic, installed into a throwaway site directory with a real
`.dist-info`, so the loader reads exactly what an installed pack looks like (R9: never the
developer's site-packages)."""

from __future__ import annotations

import logging
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from importlib.metadata import EntryPoint, distributions
from typing import TYPE_CHECKING, Any

import pytest

from platform_kit import packs, plugins
from platform_kit.packs import PackLoadError, PackStatus, load_packs, main, pin_from_env, survey
from platform_kit.testing.plugin_conformance import FakeEntryPoint

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

MANIFEST_GROUP = "pack_contracts.manifest"
PLUGIN_GROUP = "pack_contracts.plugin"
CLOCK = ("clock", "utc")

PLUGIN = """
from dataclasses import dataclass
from pack_contracts import hookimpl

@dataclass(frozen=True)
class Thing:
    kind: str
    name: str

@hookimpl
def register_contributions(register):
    for kind, name in {keys!r}:
        register(Thing(kind, name))
"""


def manifest(
    pack: str, provides: dict[str, list[str]], needs: dict[str, list[str]] | None = None, version: str = "1.0.0"
) -> str:
    def table(name: str, keys: dict[str, list[str]]) -> str:
        return f"[{name}]\n" + "".join(f"{k} = {v!r}\n" for k, v in keys.items())

    head = f'id = "{pack}"\nversion = "{version}"\ncontract = "1.0"\ntier = "loads"\n'
    return head + table("provides", provides) + (table("needs", needs) if needs else "")


@dataclass
class Site:
    root: Path

    def eps(self, group: str) -> list[EntryPoint]:
        return [ep for d in distributions(path=[str(self.root)]) for ep in d.entry_points if ep.group == group]

    def run(self, fn: Callable[..., packs.Packs] = survey, **kw: object) -> packs.Packs:
        return fn(
            manifest_entry_points=lambda: self.eps(MANIFEST_GROUP),
            plugin_entry_points=lambda: self.eps(PLUGIN_GROUP),
            **kw,
        )


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., Site]]:
    """`site(name, provides=, needs=, registers=, plugin=, manifest_text=, manifest_ep=, plugin_ep=)`
    installs one pack and returns the site (one site for every pack a test installs)."""
    root = tmp_path / "site"
    root.mkdir()
    monkeypatch.syspath_prepend(str(root))
    made: list[str] = []

    def install(
        name: str,
        *,
        provides: dict[str, list[str]] | None = None,
        needs: dict[str, list[str]] | None = None,
        registers: list[tuple[str, str]] | None = None,
        plugin: str | None = None,
        manifest_text: str | None = None,
        manifest_ep: bool = True,
        plugin_ep: bool = True,
    ) -> Site:
        provides = provides if provides is not None else {"thing": [name]}
        keys = registers if registers is not None else [(k, n) for k, ns in provides.items() for n in ns]
        pkg = root / f"{name}_pack"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "plugin.py").write_text(plugin if plugin is not None else PLUGIN.format(keys=keys), encoding="utf-8")
        (pkg / "pack.toml").write_text(manifest_text or manifest(name, provides, needs), encoding="utf-8")
        info = root / f"{name}_pack-1.0.0.dist-info"
        info.mkdir()
        (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}-pack\nVersion: 1.0.0\n", encoding="utf-8")
        eps = (f"[{PLUGIN_GROUP}]\n{name} = {name}_pack.plugin\n" if plugin_ep else "") + (
            f"[{MANIFEST_GROUP}]\n{name} = {name}_pack:pack.toml\n" if manifest_ep else ""
        )
        (info / "entry_points.txt").write_text(eps, encoding="utf-8")
        made.append(f"{name}_pack")
        return Site(root)

    yield install
    for mod in [m for m in sys.modules if m.split(".")[0] in made]:
        del sys.modules[mod]


def _state(report: packs.Packs) -> dict[str, tuple[str, str | None]]:
    return {s.pack: (s.state, s.stage) for s in report.statuses}


# -- zero packs: the host boots ----------------------------------------------------------------------
def test_no_packs_installed_boots_and_says_so() -> None:
    report = load_packs(pin=None, manifest_entry_points=list, plugin_entry_points=list)
    assert report.ok and report.statuses == () and dict(report.contributions) == {}
    assert report.render() == "no packs installed\n" and report.series() == []


def test_the_real_environment_boots_with_zero_packs() -> None:
    """The workspace installs no pack: the list-packs surface, run as a process over the real
    metadata, exits 0 and lists none. This is the CI boot with zero packs."""
    done = subprocess.run(
        [sys.executable, "-m", "platform_kit.packs", "list"], capture_output=True, text=True, check=False
    )
    assert (done.returncode, done.stdout) == (0, "no packs installed\n"), done.stderr


# -- loaded -----------------------------------------------------------------------------------------
def test_a_sound_pack_loads_and_its_contributions_are_keyed(
    site: Callable[..., Site], caplog: pytest.LogCaptureFixture
) -> None:
    s = site("apple", provides={"greeting": ["hello", "bye"]}, needs={"clock": ["utc"]})
    with caplog.at_level(logging.INFO, logger="platform_kit.packs"):
        report = s.run(load_packs, pin=None, host_provides=[CLOCK])
    assert _state(report) == {"apple": ("loaded", None)}
    assert sorted(report.contributions) == [("greeting", "bye"), ("greeting", "hello")]
    assert report.contributions[("greeting", "hello")].name == "hello"
    assert dict(report.owner) == {("greeting", "bye"): "apple", ("greeting", "hello"): "apple"}
    assert report.series() == [
        ("pack_status", {"pack": "apple", "state": "loaded", "version": "1.0.0", "origin": "apple-pack==1.0.0"}, 1.0)
    ]
    assert "pack_status pack=apple state=loaded" in caplog.text
    assert "packs_loaded pin=None loaded=apple excluded= failed= held=" in caplog.text


def test_two_packs_load_in_name_order(site: Callable[..., Site]) -> None:
    site("berry")
    s = site("apple", needs={"thing": ["berry"]})
    report = s.run(pin="apple,berry")
    assert report.of("loaded") == ("apple", "berry") and set(report.owner.values()) == {"apple", "berry"}


# -- pin --------------------------------------------------------------------------------------------
def test_the_pin_excludes_loudly_and_refuses_a_name_not_installed(site: Callable[..., Site]) -> None:
    site("apple")
    s = site("berry")
    assert _state(s.run(pin="")) == {"apple": ("excluded", None), "berry": ("excluded", None)}
    assert _state(s.run(pin=" berry ,")) == {"apple": ("excluded", None), "berry": ("loaded", None)}
    refused = s.run(pin="berry,cedar")
    assert _state(refused) == {"apple": ("excluded", None), "berry": ("held", None), "cedar": ("failed", "pin")}
    assert next(x for x in refused.statuses if x.pack == "cedar").version is None


def test_pin_from_env_reads_the_hosts_prefix() -> None:
    assert pin_from_env("HOST", {}) is None
    assert pin_from_env("HOST", {"HOST_LOAD_PACKS": "a,b"}) == "a,b"
    assert pin_from_env("HOST", {"HOST_LOAD_PACKS": ""}) == ""
    with pytest.raises(ValueError, match="prefix"):
        pin_from_env(" ")


def test_pin_from_env_defaults_to_the_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOSTX_LOAD_PACKS", "x")
    assert pin_from_env("HOSTX") == "x"


# -- the merge, from manifests alone ----------------------------------------------------------------
def test_a_key_two_packs_provide_refuses_both_and_holds_the_rest(site: Callable[..., Site]) -> None:
    site("apple", provides={"thing": ["same"]})
    site("berry", provides={"thing": ["same"]})
    site("cedar", provides={"thing": ["same"]})
    s = site("dune")
    report = s.run(pin=None)
    assert _state(report) == {
        "apple": ("failed", "provides"),
        "berry": ("failed", "provides"),
        "dune": ("held", None),
        "cedar": ("failed", "provides"),
    }
    apple = next(x for x in report.statuses if x.pack == "apple")
    assert apple.reason == "('thing', 'same') is provided by both 'apple' and 'berry'"
    assert "apple_pack" not in sys.modules, "a refused set imports nothing"
    with pytest.raises(PackLoadError) as ei:
        s.run(load_packs, pin=None)
    assert ei.value.report.of("failed") == ("apple", "berry", "cedar") and ei.value.name == "apple"
    assert "3 pack(s) failed to load: 'apple' at provides" in str(ei.value)


def test_a_key_the_host_provides_is_refused(site: Callable[..., Site]) -> None:
    s = site("apple", provides={"clock": ["utc"]})
    assert _state(s.run(pin=None, host_provides=[CLOCK])) == {"apple": ("failed", "provides")}


def test_a_need_nobody_provides_is_refused(site: Callable[..., Site]) -> None:
    s = site("apple", needs={"clock": ["utc"]})
    report = s.run(pin=None)
    assert _state(report) == {"apple": ("failed", "needs")}
    assert report.statuses[0].reason == "nobody provides [('clock', 'utc')]"


def test_a_need_only_an_excluded_pack_provides_is_refused(site: Callable[..., Site]) -> None:
    site("berry")
    s = site("apple", needs={"thing": ["berry"]})
    assert _state(s.run(pin="apple")) == {"apple": ("failed", "needs"), "berry": ("excluded", None)}


# -- manifest and pairing -----------------------------------------------------------------------------
def test_a_broken_manifest_fails_even_when_excluded(site: Callable[..., Site]) -> None:
    site("apple", manifest_text='id = "apple"\nversion = "1.0.0"\ncontract = "1.0"\ntier = "loads"\n[provides]\n')
    s = site("berry")
    report = s.run(pin="berry")
    assert _state(report) == {"apple": ("failed", "manifest"), "berry": ("held", None)}
    assert report.statuses[0].reason.startswith("validate: ")  # type: ignore[union-attr]


def test_a_plugin_without_a_manifest_and_a_manifest_without_a_plugin(site: Callable[..., Site]) -> None:
    site("apple", manifest_ep=False)
    s = site("berry", plugin_ep=False)
    report = s.run(pin=None)
    assert _state(report) == {"apple": ("failed", "pair"), "berry": ("failed", "pair")}
    assert [x.reason for x in report.statuses] == [
        "a plugin entry point with no manifest of the same name",
        "a manifest with no plugin entry point of the same name",
    ]


def test_entry_point_names_installed_twice_are_refused(site: Callable[..., Site]) -> None:
    s = site("apple")
    man, plug = s.eps(MANIFEST_GROUP), s.eps(PLUGIN_GROUP)
    twice = survey(pin=None, manifest_entry_points=lambda: man * 2, plugin_entry_points=lambda: plug)
    assert _state(twice) == {"apple": ("failed", "manifest")}
    plug_twice = survey(pin="", manifest_entry_points=lambda: man, plugin_entry_points=lambda: plug * 2)
    assert _state(plug_twice) == {"apple": ("failed", "pair")}
    assert plug_twice.statuses[0].version == "1.0.0"


# -- load and keys ------------------------------------------------------------------------------------
def test_a_plugin_that_will_not_import_fails_at_load(site: Callable[..., Site]) -> None:
    s = site("apple", plugin="raise RuntimeError('boom')\n")
    report = s.run(pin=None)
    assert _state(report) == {"apple": ("failed", "load")}
    assert report.statuses[0].reason.startswith("import: ")  # type: ignore[union-attr]


def test_a_hook_that_raises_fails_that_pack_only(site: Callable[..., Site]) -> None:
    site("berry")
    s = site(
        "apple",
        plugin=textwrap.dedent("""
        from pack_contracts import hookimpl

        @hookimpl
        def register_contributions(register):
            raise RuntimeError("boom")
    """),
    )
    assert _state(s.run(pin=None)) == {"apple": ("failed", "load"), "berry": ("loaded", None)}


@pytest.mark.parametrize(
    ("registers", "words"),
    [
        ([("thing", "apple"), ("thing", "extra")], "registered but not declared [('thing', 'extra')]"),
        ([], "declared but not registered [('thing', 'apple')]"),
    ],
)
def test_the_registered_keys_must_equal_the_manifest(
    site: Callable[..., Site], registers: list[tuple[str, str]], words: str
) -> None:
    report = site("apple", registers=registers).run(pin=None)
    assert _state(report) == {"apple": ("failed", "keys")} and words in report.statuses[0].reason  # type: ignore[operator]
    assert dict(report.contributions) == {}


def test_a_loader_failure_naming_no_selected_pack_fails_every_selected_pack(
    site: Callable[..., Site], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object, **__: object) -> plugins.Loaded:
        raise plugins.PluginLoadError(PLUGIN_GROUP, "?", "pending", "unattributed")

    monkeypatch.setattr(plugins, "load", broken)
    site("apple")
    assert _state(site("berry").run(pin=None)) == {"apple": ("failed", "load"), "berry": ("failed", "load")}


# -- the report and list-packs ------------------------------------------------------------------------
def test_render_is_one_line_per_pack_then_the_totals() -> None:
    report = packs.Packs(
        (
            PackStatus("apple", "loaded", "1.0.0", "apple-pack==1.0.0"),
            PackStatus("berry", "failed", None, None, "pin", "pinned but not installed"),
            PackStatus("cedar", "excluded", "2.0", "g==2.0", None, "not in the allow-list"),
        )
    )
    assert report.render().splitlines() == [
        "pack   state     version  origin             reason",
        "apple  loaded    1.0.0    apple-pack==1.0.0",
        "berry  failed    -        -                  pin: pinned but not installed",
        "cedar  excluded  2.0      g==2.0             not in the allow-list",
        "1 loaded, 1 excluded, 1 failed, 0 held",
    ]
    assert not report.ok and str(PackLoadError(packs.Packs(()))) == "0 pack(s) failed to load: "


def test_main_lists_and_exits_one_on_a_failure(
    site: Callable[..., Site], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    s = site("apple", needs={"clock": ["utc"]})
    real = packs.survey

    def pinned(**kw: Any) -> packs.Packs:
        return real(
            manifest_entry_points=lambda: s.eps(MANIFEST_GROUP), plugin_entry_points=lambda: s.eps(PLUGIN_GROUP), **kw
        )

    monkeypatch.setattr(packs, "survey", pinned)
    assert main(["list"]) == 1 and "apple  failed" in capsys.readouterr().out
    assert main(["list", "--host-provides", "clock/utc"]) == 0 and "apple  loaded" in capsys.readouterr().out
    assert main(["list", "--env-prefix", "HOST"], environ={"HOST_LOAD_PACKS": ""}) == 0
    assert "apple  excluded" in capsys.readouterr().out
    assert main(["list", "--pin", ""]) == 0
    with pytest.raises(SystemExit) as ei:
        main(["list", "--host-provides", "nokind"])
    assert ei.value.code == 2 and "is not kind/name" in capsys.readouterr().err


def test_fake_entry_points_are_enough_for_a_failed_manifest() -> None:
    """A manifest entry point that cannot be located is a `manifest` failure with no version."""
    report = survey(pin=None, manifest_entry_points=lambda: [FakeEntryPoint("ghost")], plugin_entry_points=list)
    assert report.statuses == (
        PackStatus("ghost", "failed", None, None, "manifest", report.statuses[0].reason),
    ) and "locate" in (report.statuses[0].reason or "")


# -- review regressions: no sound pack vanishes from the report or is blamed for another ---------------
@pytest.mark.parametrize(
    ("plugin", "stage"),
    [
        ("raise RuntimeError('boom')\n", "import"),
        ("from pack_contracts import hookimpl\n\n@hookimpl\ndef register_contributionz(register):\n    pass\n",
         "pending"),
    ],
)  # fmt: skip
def test_an_import_failure_holds_every_other_selected_pack(site: Callable[..., Site], plugin: str, stage: str) -> None:
    site("berry")
    report = site("apple", plugin=plugin).run(pin=None)
    assert _state(report) == {"apple": ("failed", "load"), "berry": ("held", None)}
    berry = report.statuses[1]
    assert berry.reason == f"not loaded: 'apple' failed at {stage}; the set loads whole"
    assert berry.version == "1.0.0"


def test_an_undeclared_registration_does_not_fail_the_pack_that_declares_it(site: Callable[..., Site]) -> None:
    site("apple", provides={"thing": ["a"]}, registers=[("thing", "a"), ("thing", "b")])
    report = site("berry", provides={"thing": ["b"]}).run(pin=None)
    assert _state(report) == {"apple": ("failed", "keys"), "berry": ("loaded", None)}
    assert dict(report.owner) == {("thing", "b"): "berry"}


def test_a_pack_whose_provider_failed_is_held_not_blamed(site: Callable[..., Site]) -> None:
    site("berry", plugin_ep=False)
    report = site("apple", needs={"thing": ["berry"]}).run(pin=None)
    assert _state(report) == {"apple": ("held", None), "berry": ("failed", "pair")}
