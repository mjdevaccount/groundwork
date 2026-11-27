"""No package names another workspace package by bare name in its published metadata.

The workspace packages are not on PyPI, and nobody holds their names there. uv resolves a bare
`primitives-kit>=0.1.0` from the workspace source, but pip, or uv with `--no-sources`, reads only
the wheel's metadata and asks the index. Whoever registers the name then gets code into that
install (dependency confusion). So an internal requirement in `[project]` must be a PEP 508 direct
reference to its own release tag in this repository:
`<name> @ git+https://github.com/<owner>/groundwork@<name>-vX.Y.Z#subdirectory=packages/<name>`.
Inside the workspace the root `[tool.uv.sources]` still wins, so the lock and the locked tests
keep using the member on disk.

The dependency groups in the root `pyproject.toml` are not published, so they may stay bare.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "git+https://github.com/mjdevaccount/groundwork"


def members(root: Path = ROOT) -> dict[str, Path]:
    """Workspace package name -> its directory, from the root's `[tool.uv.workspace] members`."""
    globs = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["uv"]["workspace"]["members"]
    found: dict[str, Path] = {}
    for pattern in globs:
        for path in sorted(root.glob(pattern)):
            meta = path / "pyproject.toml"
            if meta.is_file():
                name = tomllib.loads(meta.read_text(encoding="utf-8"))["project"]["name"]
                found[canonicalize_name(name)] = path
    return found


def requirements(project: dict[str, Any]) -> list[tuple[str, Requirement]]:
    """(where, requirement) for every requirement a `[project]` table publishes."""
    reqs = [("dependencies", Requirement(r)) for r in project.get("dependencies", [])]
    extras: dict[str, list[str]] = project.get("optional-dependencies", {})
    return reqs + [(f"[{extra}]", Requirement(r)) for extra, rs in extras.items() for r in rs]


def findings(project: dict[str, Any], internal: dict[str, Path], root: Path = ROOT) -> list[str]:
    """Every internal requirement in one `[project]` table that is not a direct reference to its
    own release tag and directory."""
    out: list[str] = []
    for where, req in requirements(project):
        name = canonicalize_name(req.name)
        if name not in internal:
            continue
        subdir = internal[name].relative_to(root).as_posix()
        want = re.compile(rf"{re.escape(REPO_URL)}@{re.escape(name)}-v\d+\.\d+\.\d+#subdirectory={re.escape(subdir)}")
        if req.url is None:
            out.append(f"{project['name']} {where}: {req.name!r} is a bare name -- an index would resolve it")
        elif not want.fullmatch(req.url):
            out.append(f"{project['name']} {where}: {req.name!r} -> {req.url} is not {REPO_URL}@{name}-vX.Y.Z"
                       f"#subdirectory={subdir}")  # fmt: skip
    return out


def test_no_workspace_package_names_another_by_bare_name() -> None:
    internal = members()
    assert {"primitives-kit", "platform-kit"} <= set(internal)  # the walk found the workspace
    problems: list[str] = []
    for path in internal.values():
        meta = tomllib.loads((path / "pyproject.toml").read_text(encoding="utf-8"))
        problems += findings(meta["project"], internal)
        if any(req.url for _, req in requirements(meta["project"])):
            hatch = meta.get("tool", {}).get("hatch", {}).get("metadata", {})
            if not hatch.get("allow-direct-references"):
                problems.append(f"{meta['project']['name']}: a direct reference needs allow-direct-references")
    assert problems == []


def test_the_check_fires_on_a_bare_name_and_on_a_wrong_tag() -> None:
    internal = members()
    good = f"primitives-kit @ {REPO_URL}@primitives-kit-v0.1.0#subdirectory=packages/primitives-kit"
    assert findings({"name": "x", "dependencies": [good, "pydantic>=2.9"]}, internal) == []
    bare = findings({"name": "x", "optional-dependencies": {"sql": ["primitives-kit>=0.1.0"]}}, internal)
    assert len(bare) == 1 and "bare name" in bare[0]
    wrong_tag = good.replace("primitives-kit-v0.1.0", "platform-kit-v0.1.0")
    assert len(findings({"name": "x", "dependencies": [wrong_tag]}, internal)) == 1
    wrong_dir = good.replace("packages/primitives-kit", "packages/platform-kit")
    assert len(findings({"name": "x", "dependencies": [wrong_dir]}, internal)) == 1
    normalized = findings({"name": "x", "dependencies": ["Primitives_Kit"]}, internal)
    assert len(normalized) == 1
