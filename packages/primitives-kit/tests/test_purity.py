"""The package is pure: every import is the standard library, pydantic, or the package itself.

This is the rule that makes the package safe for any library to depend on, at the bottom of the
graph. It reads the source, so a new import anywhere in the package is checked the moment it is
written, not when some consumer's install first breaks.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys
from importlib.metadata import requires

import primitives_kit

ALLOWED_THIRD_PARTY = frozenset({"pydantic"})
PACKAGE = pathlib.Path(primitives_kit.__file__).parent


def _top_level_imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_every_import_is_stdlib_pydantic_or_the_package() -> None:
    files = sorted(PACKAGE.rglob("*.py"))
    assert files, f"no source found under {PACKAGE}"
    allowed = set(sys.stdlib_module_names) | ALLOWED_THIRD_PARTY | {"primitives_kit", "__future__"}
    offenders = {
        f"{path.relative_to(PACKAGE)}: {name}"
        for path in files
        for name in _top_level_imports(path)
        if name not in allowed
    }
    assert not offenders, f"imports outside stdlib + pydantic: {sorted(offenders)}"


def test_the_checker_sees_a_forbidden_import(tmp_path: pathlib.Path) -> None:
    """The guard can fire: a file importing a third-party library is reported."""
    bad = tmp_path / "bad.py"
    bad.write_text("import httpx\nfrom sqlalchemy import text\nfrom . import sibling\n", encoding="utf-8")
    assert _top_level_imports(bad) == {"httpx", "sqlalchemy"}


def test_the_distribution_declares_pydantic_and_nothing_else() -> None:
    """The installed metadata, not the source: what a consumer's resolver actually pulls in."""
    names = {re.split(r"[\s;<>=!~\[]", req, maxsplit=1)[0] for req in requires("primitives-kit") or []}
    assert names == {"pydantic"}, names
