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
    # What the bare interpreter already loaded (site hooks, .pth files) is not the package's. The
    # standard library is `sys.stdlib_module_names` PLUS any module whose file lives in the stdlib
    # directories: the name list omits per-platform modules such as Linux's
    # `_sysconfigdata_<abi>_<platform>`, which `sysconfig` loads by a generated name.
    probe = (
        "import importlib, sys\n"
        "before = {m.split('.')[0] for m in sys.modules}\n"
        f"for m in {modules!r}: importlib.import_module(m)\n"
        "after = {m.split('.')[0] for m in sys.modules}\n"
        "import os, sysconfig\n"
        "def under(keys):\n"
        "    return tuple(os.path.normcase(os.path.realpath(sysconfig.get_path(k))) + os.sep for k in keys)\n"
        "std, site = under(('stdlib', 'platstdlib')), under(('purelib', 'platlib'))\n"
        "def stdlib(name):\n"
        "    if name in sys.stdlib_module_names:\n"
        "        return True\n"
        "    f = getattr(sys.modules.get(name), '__file__', None)\n"
        "    p = os.path.normcase(os.path.realpath(f)) if f else ''\n"
        "    return bool(p) and p.startswith(std) and not p.startswith(site)  # a system site-packages nests\n"
        "print(' '.join(sorted(m for m in after - before if not stdlib(m))))\n"
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
