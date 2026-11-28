"""What a pack pulls in by depending on this package: the standard library, pydantic and pluggy.

Read two ways: the installed metadata (what a consumer's resolver installs) and, in a FRESH
interpreter, every third-party module that importing each of this package's modules loads (what a
host pays at boot). A new dependency, or a module reaching into a host library, fails here.
"""

from __future__ import annotations

import pkgutil
import re
import subprocess
import sys
from importlib.metadata import requires

import pack_contracts

DECLARED = {"pydantic", "pluggy"}
#: import roots those two install (pydantic pins the other four)
ALLOWED_ROOTS = {"pydantic", "pydantic_core", "annotated_types", "typing_extensions", "typing_inspection", "pluggy"}
MODULES = ["pack_contracts", *(f"pack_contracts.{m.name}" for m in pkgutil.iter_modules(pack_contracts.__path__))]


def _loaded_roots(modules: list[str]) -> set[str]:
    probe = (  # what the bare interpreter already loaded (site hooks, .pth files) is not the package's
        "import importlib, sys\n"
        "before = {m.split('.')[0] for m in sys.modules}\n"
        f"for m in {modules!r}: importlib.import_module(m)\n"
        "after = {m.split('.')[0] for m in sys.modules}\n"
        "print(' '.join(sorted(after - before - set(sys.stdlib_module_names))))\n"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True).stdout
    return set(out.split())


def test_the_distribution_declares_pydantic_and_pluggy_only() -> None:
    names = {re.split(r"[\s;<>=!~\[]", req, maxsplit=1)[0].lower() for req in requires("pack-contracts") or []}
    assert names == DECLARED, names


def test_importing_every_module_loads_only_the_declared_libraries() -> None:
    assert "pack_contracts.discovery" in MODULES and "pack_contracts.__main__" in MODULES
    loaded = _loaded_roots(MODULES) - {"pack_contracts", "__main__", "__mp_main__"}
    assert loaded <= ALLOWED_ROOTS, sorted(loaded - ALLOWED_ROOTS)


def test_the_probe_sees_a_foreign_library() -> None:
    """Must-fire: a module outside the allowed set is reported by the same probe."""
    assert "pytest" in _loaded_roots(["pytest"])
