"""Fixtures: the synthetic example pack, installed into a throwaway site directory.

`install()` copies `tests/example_pack/` into a temporary directory, writes a real `.dist-info`
(METADATA + entry_points.txt) beside it, and puts the directory on `sys.path`. The entry points it
returns come from `importlib.metadata.distributions(path=[site])`, so they carry a real `.dist`:
the reader sees exactly what an installed pack looks like, and never the developer's site-packages.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from importlib.metadata import EntryPoint, distributions
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

EXAMPLE = Path(__file__).parent / "example_pack"
MANIFEST_GROUP = "pack_contracts.manifest"
PLUGIN_GROUP = "pack_contracts.plugin"


@dataclass(frozen=True)
class Site:
    """One installed pack: where it lives and its entry points."""

    root: Path
    package: Path

    def entry_points(self, group: str = MANIFEST_GROUP) -> list[EntryPoint]:
        return [ep for d in distributions(path=[str(self.root)]) for ep in d.entry_points if ep.group == group]


@pytest.fixture
def install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., Site]]:
    """`install(dist=, version=, package=, manifest_ep=, init=, manifest=)` -> a `Site`. `init`
    replaces the package's `__init__.py` (a tripwire); `manifest` replaces `pack.toml`'s text; `manifest_ep`
    is the manifest entry point's value: "" = `<package>:pack.toml`, None = no manifest entry point."""
    made: list[str] = []

    def _install(  # noqa: PLR0913 - the keyword arguments are the fixture's API
        *,
        dist: str = "example-pack",
        version: str = "1.0.0",
        package: str = "example_pack",
        name: str = "example",
        manifest_ep: str | None = "",
        init: str | None = None,
        manifest: str | None = None,
        site: str = "site",
    ) -> Site:
        root = tmp_path / site
        target = root / package
        shutil.copytree(EXAMPLE, target, ignore=shutil.ignore_patterns("__pycache__"))
        if init is not None:
            (target / "__init__.py").write_text(init, encoding="utf-8")
        if manifest is not None:
            (target / "pack.toml").write_text(manifest, encoding="utf-8")
        info = root / f"{dist.replace('-', '_')}-{version}.dist-info"
        info.mkdir(parents=True)
        (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {dist}\nVersion: {version}\n", encoding="utf-8")
        eps = f"[{PLUGIN_GROUP}]\n{name} = {package}.plugin\n"
        if manifest_ep is not None:
            eps += f"[{MANIFEST_GROUP}]\n{name} = {manifest_ep or package + ':pack.toml'}\n"
        (info / "entry_points.txt").write_text(eps, encoding="utf-8")
        monkeypatch.syspath_prepend(str(root))
        made.append(package)
        return Site(root, target)

    yield _install
    for mod in [m for m in sys.modules if m.split(".")[0] in made]:
        del sys.modules[mod]


@pytest.fixture
def example_manifest() -> str:
    """The synthetic pack's manifest text."""
    return (EXAMPLE / "pack.toml").read_text(encoding="utf-8")
