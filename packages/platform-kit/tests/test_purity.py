"""The package is general: what it imports is declared, and nothing in it names a consumer.

Two rules, each read from the files (so a new import or a pasted name fails the moment it is
written, not when a consumer first notices), and each proven to fire:

1. IMPORTS. The core modules import the standard library only; a module behind an extra imports
   only that extra's declared dependencies. Imports between the package's own modules follow the
   same rule (a core module may not reach into an extra's module, at import time or inside a
   function), and `import platform_kit.notify` really loads no third-party module.
2. METADATA. The installed distribution declares exactly `DECLARED`, per extra, and every import
   root the allowlist grants an extra is one that extra installs.

The third rule, NO CONSUMER KNOWLEDGE, is the workspace's: `tests/test_no_consumer_knowledge.py`
at the repository root scans every package with one deny-list.
"""

from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import sys
from importlib.metadata import requires

import platform_kit

SRC = pathlib.Path(platform_kit.__file__).parent
PKG_DIR = pathlib.Path(__file__).resolve().parents[1]

#: what the distribution declares: None = the core requirements, else the extra's name
DECLARED: dict[str | None, set[str]] = {
    None: {"tzdata"},
    "sql": {"sqlalchemy", "primitives-kit"},
    "config": {"pydantic", "pydantic-settings"},
    "service": {"fastapi", "pydantic", "pydantic-settings", "sqlalchemy", "structlog"},
    "plugins": {"pluggy"},
}

#: module path (relative to the package, "/"-separated, no ".py"; a trailing "/" = the subpackage) -> its extra
MODULE_EXTRA: dict[str, str] = {
    "budget": "sql",
    "notify/ledger": "sql",
    "watch/state": "sql",
    "config/": "config",
    "service/": "service",
    "plugins": "plugins",
    "testing/plugin_conformance": "plugins",
}

#: import root -> the distribution that installs it (a declared dependency, or the one that pulls it in)
ROOT_DIST: dict[str, str] = {
    "sqlalchemy": "sqlalchemy",
    "primitives_kit": "primitives-kit",
    "pydantic": "pydantic",
    "pydantic_core": "pydantic",  # pydantic pins it
    "pydantic_settings": "pydantic-settings",
    "fastapi": "fastapi",
    "starlette": "fastapi",  # fastapi pins it
    "structlog": "structlog",
    "pluggy": "pluggy",
}

#: the conformance suite is a test helper: it runs under the consumer's pytest, never in production
TEST_HELPER_ROOTS: dict[str, frozenset[str]] = {"testing/plugin_conformance": frozenset({"pytest"})}

_CORE_PROBE = ["platform_kit", "platform_kit.registry", "platform_kit.stamp", "platform_kit.sqlkit",
               "platform_kit.notify", "platform_kit.watch", "platform_kit.watch.runner",
               "platform_kit.watch.pager"]  # fmt: skip


# -- imports ---------------------------------------------------------------------------------------
def _rel(path: pathlib.Path) -> str:
    return path.relative_to(SRC).with_suffix("").as_posix()


def _extra_of(rel: str) -> str | None:
    for prefix, extra in MODULE_EXTRA.items():
        if rel == prefix or (prefix.endswith("/") and rel.startswith(prefix)):
            return extra
    return None


def _imports(path: pathlib.Path, rel: str) -> tuple[set[str], set[str]]:
    """(third-party roots, first-party module paths) imported ANYWHERE in the file, function bodies
    included. Relative imports resolve against the module's package."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    pkg = rel.split("/")[:-1]  # a module's package; for `x/__init__` that is `x` itself
    roots: set[str] = set()
    first: set[str] = set()

    def own(parts: list[str]) -> None:
        first.add("/".join(p for p in parts if p) or "__init__")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top, *rest = alias.name.split(".")
                (own(rest) if top == "platform_kit" else roots.add(top))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                top, *rest = node.module.split(".")
                if top != "platform_kit":
                    roots.add(top)
                    continue
                base = rest
            elif node.level > 0:
                up = pkg[: len(pkg) - (node.level - 1)] if node.level > 1 else pkg
                base = [*up, *(node.module.split(".") if node.module else [])]
            else:  # pragma: no cover - `from . import` always has a level
                continue
            for alias in node.names:
                cand = [*base, alias.name]
                is_mod = SRC.joinpath(*cand).with_suffix(".py").is_file() or SRC.joinpath(*cand).is_dir()
                own(cand if is_mod else base)
    return roots, first


def _module_extra(target: str) -> str | None:
    if (SRC / target).is_dir():
        return _extra_of(target + "/")
    return _extra_of(target)


def _may_use(source_extra: str | None, target_extra: str | None) -> bool:
    if target_extra is None or target_extra == source_extra:
        return True
    return source_extra is not None and DECLARED[target_extra] <= DECLARED[source_extra]


def _roots_for(rel: str) -> frozenset[str]:
    extra = _extra_of(rel)
    dists = DECLARED.get(extra, set()) if extra else set()
    granted = {root for root, dist in ROOT_DIST.items() if dist in dists}
    return frozenset(granted | TEST_HELPER_ROOTS.get(rel, frozenset()))


def _import_offences(path: pathlib.Path) -> set[str]:
    rel = _rel(path)
    roots, first = _imports(path, rel)
    allowed = set(sys.stdlib_module_names) | {"__future__"} | _roots_for(rel)
    bad = {f"{rel}: imports {r}" for r in roots if r not in allowed}
    src_extra = _extra_of(rel)
    bad |= {f"{rel}: reaches into {t} ([{_module_extra(t)}])" for t in first
            if not _may_use(src_extra, _module_extra(t))}  # fmt: skip
    return bad


def _loaded_third_party(modules: list[str]) -> list[str]:
    """In a FRESH interpreter, import `modules` and return the third-party roots that got loaded."""
    probe = (
        f"import importlib, sys\nfor m in {modules!r}: importlib.import_module(m)\n"
        f"print(' '.join(sorted({{m.split('.')[0] for m in sys.modules}} & set({sorted(ROOT_DIST)!r}))))\n"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True).stdout
    return out.split()


def test_every_import_is_stdlib_or_its_extras_declared_dependency() -> None:
    files = sorted(SRC.rglob("*.py"))
    assert len(files) > 20, f"no source found under {SRC}"
    offenders = set().union(*(_import_offences(p) for p in files))
    assert not offenders, sorted(offenders)


def test_the_core_planes_load_no_third_party_module() -> None:
    assert _loaded_third_party(_CORE_PROBE) == []


def test_the_import_checks_fire(tmp_path: pathlib.Path) -> None:
    """Must-fire, each way: a third-party import in a core module, a core module reaching into an
    extra's module (at import time, relatively, and inside a function body), and the fresh-interpreter
    probe seeing an extra's library load. The allowed shapes pass."""
    bad = tmp_path / "stamp.py"
    bad.write_text(
        "import httpx\nfrom platform_kit.budget import PgWindowBudget\n"
        "def f():\n    from .service import db\n    from . import sqlkit\n",
        encoding="utf-8",
    )
    roots, first = _imports(bad, "stamp")
    assert roots == {"httpx"} and first == {"budget", "service/db", "sqlkit"}
    assert not _may_use(None, _module_extra("budget")) and not _may_use(None, _module_extra("service/db"))
    assert _may_use(None, _module_extra("sqlkit")) and _may_use("service", _module_extra("sqlkit"))
    assert not _may_use("service", "sql")  # service does not install primitives-kit
    assert "sqlalchemy" not in _roots_for("registry") and "sqlalchemy" in _roots_for("service/db")
    assert "pytest" in _roots_for("testing/plugin_conformance") and "pytest" not in _roots_for("plugins")
    assert "sqlalchemy" in _loaded_third_party(["platform_kit.budget"])


# -- metadata --------------------------------------------------------------------------------------
def test_the_distribution_declares_exactly_these_dependencies() -> None:
    got: dict[str | None, set[str]] = {}
    for req in requires("platform-kit") or []:
        name = re.split(r"[\s;<>=!~\[]", req, maxsplit=1)[0].lower()
        extra = re.search(r"extra\s*==\s*['\"]([^'\"]+)['\"]", req)
        got.setdefault(extra.group(1) if extra else None, set()).add(name)
    assert got == DECLARED, got


def test_every_granted_root_is_installed_by_its_extra() -> None:
    assert set(MODULE_EXTRA.values()) <= {k for k in DECLARED if k}
    assert set(ROOT_DIST.values()) <= set().union(*DECLARED.values())
