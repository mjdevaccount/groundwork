"""The package is general: what it imports is declared, and nothing in it names a consumer.

Three rules, each read from the files (so a new import or a pasted name fails the moment it is
written, not when a consumer first notices):

1. IMPORTS. The core modules import the standard library only; each extra's modules import only
   that extra's declared dependencies. A consumer that installs no extra gets a stdlib package, and
   `import platform_kit.notify` really loads no third-party module (checked in a fresh interpreter).
2. METADATA. The installed distribution declares exactly the dependencies listed here, per extra.
3. NO CONSUMER KNOWLEDGE. No word on a deny-list (application, host and account names, market
   symbols and vocabulary) in the source, the tests or the docs; no email address and no IPv4
   address outside the documentation ranges. The deny-list is kept as sha256 digests so this file
   does not itself carry the words it refuses.
"""

from __future__ import annotations

import ast
import hashlib
import ipaddress
import pathlib
import re
import subprocess
import sys
from importlib.metadata import requires

import platform_kit

SRC = pathlib.Path(platform_kit.__file__).parent
PKG_DIR = pathlib.Path(__file__).resolve().parents[1]

#: module path (relative to the package, "/"-separated, no ".py") prefix -> third-party roots it may import
EXTRA_IMPORTS: dict[str, frozenset[str]] = {
    "budget": frozenset({"sqlalchemy", "primitives_kit"}),
    "notify/ledger": frozenset({"sqlalchemy"}),
    "watch/state": frozenset({"sqlalchemy"}),
    "config/": frozenset({"pydantic", "pydantic_core", "pydantic_settings"}),
    "service/": frozenset({"fastapi", "starlette", "pydantic", "pydantic_settings", "sqlalchemy", "structlog"}),
    "plugins": frozenset({"pluggy"}),
    "testing/plugin_conformance": frozenset({"pluggy", "pytest"}),  # a test helper: runs under pytest
}

#: what the distribution declares: None = the core requirements, else the extra's name
DECLARED: dict[str | None, set[str]] = {
    None: {"tzdata"},
    "sql": {"sqlalchemy", "primitives-kit"},
    "config": {"pydantic", "pydantic-settings"},
    "service": {"fastapi", "pydantic", "pydantic-settings", "sqlalchemy", "structlog"},
    "plugins": {"pluggy"},
}

#: sha256 of lowercase words (whole tokens, or `-`/`_` compounds) no file in the package may contain.
#: The publishing account in the repository URL is the publisher, not a consumer: it is not listed.
DENIED = frozenset({
    "1f4f4954cb64b1723252fd0090cc461eaf0162bbea0bb541402961e68104c5b7",
    "b733a73fb7e04647579dcaa23087708c97e2662f2cb0c1b55028af119c1eb0ab",
    "9cc7de53400de22b7c037731be3ec169730546ffa8ce1d869bca509ce9aaf096",
    "f1d861f87bcd70157d7fb09fd551fa7342b56653c5f87c2a8c6961e103b954a8",
    "d6290d14e825b9681d46b7140525fde9ac48cd069bbc40cddbf807795cd82771",
    "20117354b841cfa80d2c329d926de03410e6e2282bfb987d7f0021251e826541",
    "0d515cb693e7dfb00cf046c08bab8be9fcc9100fa935f76ec911528428b5a94c",
    "be9d587defa1f0c09ef49eb17e206983a5f8f8289e4281860bd0ee5a19592c67",
    "8a7240ae4a1327a4a8a5c5e3bf15292e2a9bcc7c267d8710e05e2f191cba1a53",
    "78a59b7f715421da93ba0bb271b488ed10d1f20d73b5040daeb6f6a64ec201e6",
    "1ef4d96def52a9591b42924f44cf2d59c75fee971c536e3bb8163dfc7f6df5c8",
    "70c725414d7c88128cf47376b0e3322b38730ce4d9dc311ad2e7f84ede3a6f59",
    "4f31fa50e5bd5ff45684e560fc24aeee527a43739ab611c49c51098a33e2b469",
    "77518d3ae4a62eeffee4868fd54927b127b7df71ad3ef66fb7f3f1e4b4974c8e",
    "d20dbd6a870c25193970ab56921ac6c12c60f19b53ca5cf7d8d30e89adf83cda",
    "a95bc16631ae2b6fadb455ee018da0adc2703e56d89e3eed074ce56d2f7b1b6a",
    "7327d4d86dcf6bd569c05303ab188992c7ed923898b393c1cddf63973d7245ff",
    "a65c7c024a58c4b4593735d717fce3ced17180609edb936a7911d0440dd1d670",
    "57d4aa377250296d19d9f55f132db4bc2725c657672b0c3e54467839e6c05356",
    "027056a5f0ed3a3516246027c860580ca5d931c5d677ab1d01057e0bee42009d",
    "41d24adbe212d610120077b07a9490991116d1bea3caba127e3f6193c71adf28",
    "573a8b06a55516233cf73c9e86fd97538b7537d462928360bee7d0cebccbcccc",
    "87d9a3103d716fe61e7b45ece99fb9cc8bae6952d0a9eaaeaae8a41902a9001f",
    "843415fc8e7e835444fe9bdf92a43a4e5d552ad47465f8f6fc19eed0363671e5",
    "06c070e17a38217b470fe79a33da6b66f5836e7070a5001fb2706123a7969127",
    "2877e0f6f601dc4622bc2571e6fb4237ff1f44f6236ed5f9656337ec1abe02c0",
    "3a4a82f2cca872acc469a03c04e4e38389b84971b9fff4c9e1b4dfb222e33339",
    "95728ccce2aa38e92ed750c57520e663c687f8ddc1fc9e743ae377795d338573",
    "21f6712b3774ab4c21774084d15e0d31d7798edb66959a6802ceeafcb5789a43",
    "01edf10f168c23a08b07b00906e93edb2dd2c88566f303726b25fc9df3130ed2",
    "8e1e444726cad61d492dd656bde91a33460109ef89448f9f251d58d6bd2efb35",
})  # fmt: skip
#: sha256 of upper-case tokens denied case-sensitively (the lower-case word is ordinary English)
DENIED_EXACT = frozenset({"b5833faa1c49a66619348169b4ec14a2df8f05ff5d1ec47aefdf95b829ffa11c"})

_WORD = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")
_TOKEN = re.compile(r"[A-Za-z0-9]+")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})")
_IPV4 = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
_RESERVED_TLDS = (".example", ".invalid", ".test", ".localhost")  # RFC 2606 / 6761
_DOC_NETS = tuple(ipaddress.ip_network(n) for n in ("127.0.0.0/8", "0.0.0.0/32", "192.0.2.0/24", "198.51.100.0/24",
                                                     "203.0.113.0/24"))  # fmt: skip


def _sha(word: str) -> str:
    return hashlib.sha256(word.encode()).hexdigest()


def _top_level_imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def _allowed_for(rel: str) -> frozenset[str]:
    out: set[str] = set()
    for prefix, roots in EXTRA_IMPORTS.items():
        if rel == prefix or (prefix.endswith("/") and rel.startswith(prefix)):
            out |= roots
    return frozenset(out)


def _findings(text: str, denied: frozenset[str] = DENIED, exact: frozenset[str] = DENIED_EXACT) -> set[str]:
    """Every deny-listed word, email and non-documentation IPv4 in `text`, by kind and digest prefix."""
    found: set[str] = set()
    for word in _WORD.findall(text.lower()):
        for w in {word, *re.split(r"[-_]", word)}:
            if _sha(w) in denied:
                found.add(f"word sha256:{_sha(w)[:12]}")
    found.update(f"word sha256:{_sha(t)[:12]}" for t in _TOKEN.findall(text) if _sha(t) in exact)
    for m in _EMAIL.finditer(text):
        if not m.group(1).lower().endswith(_RESERVED_TLDS):
            found.add(f"email at @{m.group(1)}")
    for ip in _IPV4.findall(text):
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if not any(addr in net for net in _DOC_NETS):
            found.add(f"ipv4 {ip}")
    return found


def _scanned() -> list[pathlib.Path]:
    files = [*sorted((PKG_DIR / "src").rglob("*.py")), *sorted((PKG_DIR / "tests").rglob("*.py"))]
    return [*files, *(p for p in (PKG_DIR / "README.md", PKG_DIR / "CHANGELOG.md") if p.is_file())]


# -- 1. imports ------------------------------------------------------------------------------------
def test_every_import_is_stdlib_or_its_extras_declared_dependency() -> None:
    files = sorted(SRC.rglob("*.py"))
    assert files, f"no source found under {SRC}"
    base = set(sys.stdlib_module_names) | {"platform_kit", "__future__"}
    offenders = set()
    for path in files:
        rel = path.relative_to(SRC).with_suffix("").as_posix()
        allowed = base | _allowed_for(rel)
        offenders |= {f"{rel}: {name}" for name in _top_level_imports(path) if name not in allowed}
    assert not offenders, f"imports outside the module's extra: {sorted(offenders)}"


def test_the_core_planes_load_no_third_party_module() -> None:
    probe = (
        "import sys, platform_kit, platform_kit.registry, platform_kit.stamp, platform_kit.sqlkit, "
        "platform_kit.notify, platform_kit.watch, platform_kit.watch.runner, platform_kit.watch.pager\n"
        "roots = {'sqlalchemy', 'pydantic', 'pydantic_settings', 'fastapi', 'starlette', 'pluggy', 'structlog',"
        " 'primitives_kit'}\n"
        "print(sorted({m.split('.')[0] for m in sys.modules} & roots))\n"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]", out


def test_the_import_checker_sees_a_forbidden_import(tmp_path: pathlib.Path) -> None:
    """The guard can fire: a core module importing an extra's library is reported."""
    bad = tmp_path / "bad.py"
    bad.write_text("import httpx\nfrom sqlalchemy import text\nfrom . import sibling\n", encoding="utf-8")
    assert _top_level_imports(bad) == {"httpx", "sqlalchemy"}
    assert "sqlalchemy" not in _allowed_for("registry")
    assert "sqlalchemy" in _allowed_for("service/db") and "pydantic" in _allowed_for("config/knobs")


# -- 2. metadata -----------------------------------------------------------------------------------
def test_the_distribution_declares_exactly_these_dependencies() -> None:
    got: dict[str | None, set[str]] = {}
    for req in requires("platform-kit") or []:
        name = re.split(r"[\s;<>=!~\[]", req, maxsplit=1)[0].lower()
        extra = re.search(r"extra\s*==\s*['\"]([^'\"]+)['\"]", req)
        got.setdefault(extra.group(1) if extra else None, set()).add(name)
    assert got == DECLARED, got


# -- 3. no consumer knowledge ----------------------------------------------------------------------
def test_no_file_names_a_consumer() -> None:
    files = _scanned()
    assert len(files) > 20, files
    hits = {
        f"{p.relative_to(PKG_DIR).as_posix()}: {f}" for p in files for f in _findings(p.read_text(encoding="utf-8"))
    }
    assert not hits, sorted(hits)


def test_the_name_checker_fires_both_ways() -> None:
    """Must-fire: a deny-listed word (assembled, so this file does not spell it), the case-sensitive
    token, a real-looking email and a private address are each found; the reserved and documentation
    forms, and the word as part of a longer one, are not."""
    word, token = "q" * 3, "".join(reversed("EGDE"))
    assert _sha(word) in DENIED and _sha(token) in DENIED_EXACT
    assert _findings(f"symbol {word.upper()} here") == {f"word sha256:{_sha(word)[:12]}"}
    assert _findings(f"an {token}_FLAG env") == {f"word sha256:{_sha(token)[:12]}"}
    assert _findings(f"the {token.lower()} of the cliff, {word}x") == set()
    mail, ip = "@".join(("ops", "corp.io")), ".".join(("10", "1", "2", "3"))  # neither spelled whole here
    assert _findings(f"{mail} and {ip}") == {"email at @corp.io", f"ipv4 {ip}"}
    assert _findings("ops@vendor.example, u:pw@db:5432, 127.0.0.1, 192.0.2.7, 300.1.1.1") == set()
    assert _findings("zebra", denied=frozenset({_sha("zebra")})) == {f"word sha256:{_sha('zebra')[:12]}"}
