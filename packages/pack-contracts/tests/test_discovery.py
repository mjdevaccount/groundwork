"""The manifest reader: it reads an installed pack WITHOUT importing it, and every failure is a typed
`ManifestError` naming the pack and the stage. Each stage is proven to fire."""

from __future__ import annotations

import json
import logging
import sys
import tomllib
import types
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from pack_contracts.contract import ContractVersion
from pack_contracts.discovery import (
    MANIFEST_GROUP,
    STAGES,
    ManifestError,
    parse_manifest,
    read_manifest,
    read_manifests,
)
from pack_contracts.manifest import Tier

if TYPE_CHECKING:
    from collections.abc import Callable

TRIPWIRE = "raise RuntimeError('the reader imported pack code')\n"


def _stage(exc: pytest.ExceptionInfo[ManifestError], stage: str, pack: str = "example") -> None:
    assert (exc.value.stage, exc.value.pack) == (stage, pack), str(exc.value)


def test_it_reads_an_installed_pack_from_the_real_entry_points(install: Callable[..., Any]) -> None:
    site = install()
    found = read_manifests()  # the default discovery: importlib.metadata over sys.path
    assert found.group == MANIFEST_GROUP and found.packs == ("example",)
    (rec,) = found.records
    assert rec.origin == "example-pack==1.0.0"
    assert Path(rec.source) == site.package / "pack.toml"
    assert rec.manifest.tier is Tier.LOADS


def test_it_never_imports_the_pack(install: Callable[..., Any]) -> None:
    """A pack whose import raises is still read: its package was located, never executed."""
    site = install(init=TRIPWIRE)
    sub = site.package / "sub"
    sub.mkdir()
    (sub / "__init__.py").write_text(TRIPWIRE, encoding="utf-8")
    (sub / "pack.toml").write_text((site.package / "pack.toml").read_text(encoding="utf-8"), encoding="utf-8")
    assert read_manifests(entry_points=site.entry_points).packs == ("example",)
    nested = types.SimpleNamespace(name="example", value="example_pack.sub:pack.toml", dist=None)
    assert read_manifest(nested).manifest.id == "example"  # a dotted package: no parent executed either
    assert not [m for m in sys.modules if m.split(".")[0] == "example_pack"]
    with pytest.raises(RuntimeError, match="imported pack code"):  # the tripwire is live
        __import__("example_pack")


def test_packs_come_back_sorted_and_counted(
    install: Callable[..., Any], example_manifest: str, caplog: pytest.LogCaptureFixture
) -> None:
    a = install()
    b = install(dist="b-pack", package="b_pack", name="b", manifest=example_manifest.replace('"example"', '"b"'))
    eps = a.entry_points()  # one site holds both packs
    assert len(eps) == 2 and b.root == a.root
    with caplog.at_level(logging.INFO, logger="pack_contracts.discovery"):
        found = read_manifests(entry_points=lambda: list(reversed(eps)))
    assert found.packs == ("b", "example")
    assert found.series() == [
        (
            "pack_manifest",
            {"group": MANIFEST_GROUP, "pack": p, "version": "1.0.0", "contract": "1.0", "tier": "loads",
             "origin": f"{d}==1.0.0"},
            1.0,
        )
        for p, d in (("b", "b-pack"), ("example", "example-pack"))
    ]  # fmt: skip
    assert "pack_manifests_read" in caplog.text and "packs=b,example" in caplog.text


def test_no_installed_pack_is_an_empty_result() -> None:
    assert read_manifests(entry_points=list).records == ()


def test_a_duplicate_name_refuses(install: Callable[..., Any]) -> None:
    site = install()
    with pytest.raises(ManifestError) as caught:
        read_manifests(entry_points=lambda: site.entry_points() * 2)
    _stage(caught, "duplicate")


def _ep(value: str, name: str = "example", dist: Any = None) -> Any:
    return types.SimpleNamespace(name=name, value=value, dist=dist)


@pytest.mark.parametrize(
    "value",
    [
        "example_pack",  # no colon
        ":pack.toml",
        "example_pack:",
        "example_pack:../pack.toml",  # not a bare file name
        "example_pack:sub/pack.toml",
        "example_pack:..",
        "nowhere_pack:pack.toml",  # not installed
        "nowhere_pack.sub:pack.toml",
        "example_pack.nope:pack.toml",  # no such subpackage
        "example_pack.plugin:pack.toml",  # a module, not a package
        "example_pack.plugin.deeper:pack.toml",
        "solo:pack.toml",  # a top-level module, not a package
        "example_pack:missing.toml",
    ],
)
def test_locate_refuses(install: Callable[..., Any], value: str) -> None:
    site = install()
    (site.root / "solo.py").write_text("", encoding="utf-8")
    with pytest.raises(ManifestError) as caught:
        read_manifest(_ep(value))
    _stage(caught, "locate")


def test_locate_refuses_a_module_with_no_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    ghost = types.ModuleType("ghost_pack")
    ghost.__spec__ = None
    monkeypatch.setitem(sys.modules, "ghost_pack", ghost)
    with pytest.raises(ManifestError) as caught:
        read_manifest(_ep("ghost_pack:pack.toml"))
    _stage(caught, "locate")


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("pack.yaml", b"id: example\n"),  # a suffix the reader does not parse
        ("pack", b"id = 'example'\n"),
        ("pack.toml", b"id = \n"),  # not TOML
        ("pack.json", b"{not json"),
        ("pack.toml", b"\xff\xfe\x00"),  # not UTF-8
    ],
)
def test_read_refuses(install: Callable[..., Any], filename: str, content: bytes) -> None:
    site = install()
    (site.package / filename).write_bytes(content)
    with pytest.raises(ManifestError) as caught:
        read_manifest(_ep(f"example_pack:{filename}"))
    _stage(caught, "read")


def test_read_refuses_an_unreadable_file(install: Callable[..., Any], monkeypatch: pytest.MonkeyPatch) -> None:
    install()

    def denied(self: Path, *args: Any, **kwargs: Any) -> str:
        raise PermissionError(13, "denied", str(self))

    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(ManifestError) as caught:
        read_manifest(_ep("example_pack:pack.toml"))
    _stage(caught, "read")


def test_validate_refuses_and_chains_the_pydantic_error(install: Callable[..., Any], example_manifest: str) -> None:
    site = install(manifest=example_manifest + 'colour = "blue"\n')
    with pytest.raises(ManifestError) as caught:
        read_manifests(entry_points=site.entry_points)
    _stage(caught, "validate")
    assert "colour" in str(caught.value) and type(caught.value.__cause__).__name__ == "ValidationError"


def test_identity_refuses_an_id_that_is_not_the_entry_point_name(install: Callable[..., Any]) -> None:
    site = install(name="other")
    with pytest.raises(ManifestError) as caught:
        read_manifests(entry_points=site.entry_points)
    _stage(caught, "identity", pack="other")


def test_identity_refuses_a_version_that_is_not_the_distributions(install: Callable[..., Any]) -> None:
    site = install(version="1.0.1")
    with pytest.raises(ManifestError) as caught:
        read_manifests(entry_points=site.entry_points)
    _stage(caught, "identity")
    assert "'1.0.1'" in str(caught.value)


def test_without_a_distribution_the_version_is_not_compared(install: Callable[..., Any]) -> None:
    install()
    rec = read_manifest(_ep("example_pack:pack.toml"))
    assert rec.origin == "entry-point example_pack:pack.toml"


@pytest.mark.parametrize(("declared", "host"), [("2.0", "1.0"), ("1.1", "1.0"), ("1.0", "2.0")])
def test_contract_refuses_what_the_host_does_not_satisfy(
    install: Callable[..., Any], example_manifest: str, declared: str, host: str
) -> None:
    site = install(manifest=example_manifest.replace('contract = "1.0"', f'contract = "{declared}"'))
    with pytest.raises(ManifestError) as caught:
        read_manifests(entry_points=site.entry_points, host=ContractVersion.parse(host))
    _stage(caught, "contract")


def test_contract_accepts_an_older_minor(install: Callable[..., Any]) -> None:
    site = install()
    assert read_manifests(entry_points=site.entry_points, host=ContractVersion(1, 4)).packs == ("example",)


def test_parse_manifest_reads_json(example_manifest: str) -> None:
    text = json.dumps(tomllib.loads(example_manifest))
    assert parse_manifest(text, suffix=".JSON").id == "example"


def test_the_error_is_an_import_error_with_a_closed_stage_list() -> None:
    err = ManifestError("p", "locate", "why")
    assert isinstance(err, ImportError) and err.name == "p" and "at locate: why" in str(err)
    assert STAGES == ("duplicate", "locate", "read", "validate", "identity", "contract")
    with pytest.raises(ValueError, match="unknown manifest stage"):
        ManifestError("p", "skipped", "x")  # type: ignore[arg-type]


@pytest.mark.parametrize("group", ["", "  "])
def test_a_group_is_required(group: str) -> None:
    with pytest.raises(ValueError, match="needs a group"):
        read_manifests(group=group, entry_points=list)
