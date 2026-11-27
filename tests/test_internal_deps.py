"""No package names another workspace package by bare name in its published metadata.

The workspace packages are not on PyPI, and nobody holds their names there. uv resolves a bare
`primitives-kit>=0.1.0` from the workspace source, but pip, or uv with `--no-sources`, reads only
the wheel's metadata and asks the index. Whoever registers the name then gets code into that
install (dependency confusion). So an internal requirement in `[project]` (and in
`[build-system] requires`) must be a PEP 508 direct reference to a release tag of that package in
this repository, at a version no newer than the member on disk:
`<name> @ git+https://github.com/<owner>/groundwork@<name>-vX.Y.Z#subdirectory=packages/<name>`.
Inside the workspace the root `[tool.uv.sources]` still wins, so the lock and the locked tests
keep using the member on disk. That the tag EXISTS is the CI build job's check: it resolves each
built wheel, every extra, from its metadata alone.

Requirement lists computed at build time (`dynamic`) are refused: this test could not read them.
A package naming itself (`all = ["pkg[a,b]"]`) is not an index lookup and is skipped. The
dependency groups in the root `pyproject.toml` are not published, so they may stay bare.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "git+https://github.com/mjdevaccount/groundwork"


def _toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def members(root: Path = ROOT) -> dict[str, Path]:
    """Workspace package name -> its directory, from the root's `[tool.uv.workspace] members`."""
    found: dict[str, Path] = {}
    for pattern in _toml(root / "pyproject.toml")["tool"]["uv"]["workspace"]["members"]:
        for path in sorted(root.glob(pattern)):
            if (path / "pyproject.toml").is_file():
                found[canonicalize_name(_toml(path / "pyproject.toml")["project"]["name"])] = path
    return found


def requirements(meta: dict[str, Any]) -> list[tuple[str, Requirement]]:
    """(where, requirement) for every requirement one member's pyproject publishes or builds with."""
    project = meta["project"]
    reqs = [("dependencies", Requirement(r)) for r in project.get("dependencies", [])]
    extras: dict[str, list[str]] = project.get("optional-dependencies", {})
    reqs += [(f"[{extra}]", Requirement(r)) for extra, rs in extras.items() for r in rs]
    return reqs + [("build-system", Requirement(r)) for r in meta.get("build-system", {}).get("requires", [])]


def findings(meta: dict[str, Any], internal: dict[str, Path], root: Path = ROOT) -> list[str]:
    """Every internal requirement in one member's pyproject that is not a direct reference to a
    release tag of that package, in its own directory, no newer than the member on disk."""
    me = meta["project"]["name"]
    dynamic = meta["project"].get("dynamic", [])
    out = [f"{me}: `{field}` is dynamic -- a requirement computed at build time is unread here"
           for field in ("dependencies", "optional-dependencies") if field in dynamic]  # fmt: skip
    for where, req in requirements(meta):
        name = canonicalize_name(req.name)
        if name not in internal or name == canonicalize_name(me):
            continue
        subdir = internal[name].relative_to(root).as_posix()
        want = re.compile(rf"{re.escape(REPO_URL)}@{re.escape(name)}-v(\d+\.\d+\.\d+)#subdirectory={re.escape(subdir)}")
        hit = want.fullmatch(req.url) if req.url is not None else None
        if req.url is None:
            out.append(f"{me} {where}: {req.name!r} is a bare name -- an index would resolve it")
        elif hit is None:
            out.append(f"{me} {where}: {req.name!r} -> {req.url} is not {REPO_URL}@{name}-vX.Y.Z#subdirectory={subdir}")
        elif Version(hit.group(1)) > (disk := Version(_toml(internal[name] / "pyproject.toml")["project"]["version"])):
            out.append(f"{me} {where}: {req.name!r} -> v{hit.group(1)} is newer than {name} on disk ({disk})")
    return out


def test_no_workspace_package_names_another_by_bare_name() -> None:
    internal = members()
    assert {"primitives-kit", "platform-kit"} <= set(internal)  # the walk found the workspace
    problems: list[str] = []
    for path in internal.values():
        meta = _toml(path / "pyproject.toml")
        problems += findings(meta, internal)
        hatch = meta.get("tool", {}).get("hatch", {}).get("metadata", {})
        if any(req.url for _, req in requirements(meta)) and not hatch.get("allow-direct-references"):
            problems.append(f"{meta['project']['name']}: a direct reference needs allow-direct-references")
    assert problems == []


def _meta(**project: Any) -> dict[str, Any]:
    return {"project": {"name": "x", **project}}


def test_the_check_fires_on_each_shape_it_exists_to_find() -> None:
    internal = members()
    good = f"primitives-kit @ {REPO_URL}@primitives-kit-v0.1.0#subdirectory=packages/primitives-kit"
    assert findings(_meta(dependencies=[good, "pydantic>=2.9"]), internal) == []
    marked = {"sql": ["primitives-kit>=0.1.0 ; python_version>'3'"]}  # a marker hides nothing
    bare = findings(_meta(**{"optional-dependencies": marked}), internal)
    assert len(bare) == 1 and "bare name" in bare[0]
    for wrong in (
        good.replace("primitives-kit-v0.1.0", "platform-kit-v0.1.0"),  # another package's tag
        good.replace("packages/primitives-kit", "packages/platform-kit"),  # another package's directory
        good.replace("mjdevaccount", "someone-else"),  # another owner
        "primitives-kit @ file:///tmp/primitives-kit",  # not a release
    ):
        assert len(findings(_meta(dependencies=[wrong]), internal)) == 1, wrong
    newer = findings(_meta(dependencies=[good.replace("v0.1.0", "v99.0.0")]), internal)
    assert len(newer) == 1 and "newer than" in newer[0]
    assert len(findings(_meta(dependencies=["Primitives_Kit"]), internal)) == 1  # name normalisation
    built_with = {"project": {"name": "x"}, "build-system": {"requires": ["hatchling", "primitives-kit"]}}
    assert len(findings(built_with, internal)) == 1
    assert len(findings(_meta(dynamic=["dependencies"]), internal)) == 1
    assert findings({"project": {"name": "platform-kit", "optional-dependencies": {"all": ["platform-kit[sql]"]}}},
                    internal) == []  # fmt: skip
