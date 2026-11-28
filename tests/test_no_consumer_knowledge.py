"""No package names a consumer: the workspace rule (`CLAUDE.md`, "No consumer knowledge"), held
over EVERY package under `packages/` with one deny-list.

No word on the deny-list (application, host and account names, market symbols and vocabulary) in
any file of any package (source, data files, tests, docs, README, CHANGELOG, pyproject); no email
address and no IPv4 address outside the documentation ranges. The deny-list is kept as sha256
digests so this file does not itself carry the words it refuses. A package added under `packages/`
is scanned the moment it exists; the test also names the three packages it must find, so a walk
that found nothing cannot pass.
"""

from __future__ import annotations

import hashlib
import ipaddress
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: sha256 of lowercase words no file in the package may contain. A word is checked whole, with its
#: `-`/`_` separators normalised to `-` and removed, and as every run of its `-`/`_`/camelCase/digit
#: pieces. The publishing account in the repository URL is the publisher, not a consumer: not listed.
DENIED = frozenset({
    "01edf10f168c23a08b07b00906e93edb2dd2c88566f303726b25fc9df3130ed2",
    "0d515cb693e7dfb00cf046c08bab8be9fcc9100fa935f76ec911528428b5a94c",
    "11c129e2a6fc99eedb769ca921a2434ed61a9ef8b02746a7252cf98df0d3afea",
    "11c7931bf20b1a9816ee71b707ed69108291c2625f66524296971be9c6d621ce",
    "1f4f4954cb64b1723252fd0090cc461eaf0162bbea0bb541402961e68104c5b7",
    "20117354b841cfa80d2c329d926de03410e6e2282bfb987d7f0021251e826541",
    "209d20e9119f6d7ede04399f1432b71f5a3636270a7718b39eea7b362c42bd9d",
    "21f6712b3774ab4c21774084d15e0d31d7798edb66959a6802ceeafcb5789a43",
    "36c7f830afd6684d4cfa7a00b04d082569bf1e666a9393bb5e692acb5e9454bd",
    "41d24adbe212d610120077b07a9490991116d1bea3caba127e3f6193c71adf28",
    "46e0d11c3c04338a8afa1ed3ce94a675243451788e2ecd1310ff1290e11c8eb1",
    "4f31fa50e5bd5ff45684e560fc24aeee527a43739ab611c49c51098a33e2b469",
    "53776c4a336c02beede45bdf04a9b2d9cef1a4304f31115c5a6b4a45f0590c69",
    "56fc442eacff56b644b3e7489295a5364ec172c0d794c9d6ae39d9a4598aa9a6",
    "573a8b06a55516233cf73c9e86fd97538b7537d462928360bee7d0cebccbcccc",
    "57d4aa377250296d19d9f55f132db4bc2725c657672b0c3e54467839e6c05356",
    "70c725414d7c88128cf47376b0e3322b38730ce4d9dc311ad2e7f84ede3a6f59",
    "7327d4d86dcf6bd569c05303ab188992c7ed923898b393c1cddf63973d7245ff",
    "77518d3ae4a62eeffee4868fd54927b127b7df71ad3ef66fb7f3f1e4b4974c8e",
    "78a59b7f715421da93ba0bb271b488ed10d1f20d73b5040daeb6f6a64ec201e6",
    "7f20733dc6b3635765ba16ba8be201b7b95e0b2903e8b5971b2f0a012d75408c",
    "843415fc8e7e835444fe9bdf92a43a4e5d552ad47465f8f6fc19eed0363671e5",
    "87d9a3103d716fe61e7b45ece99fb9cc8bae6952d0a9eaaeaae8a41902a9001f",
    "896f3a9248eadbb6bb4f2f8553791256e7c06e0d05d715e161d7ac819521c161",
    "8a7240ae4a1327a4a8a5c5e3bf15292e2a9bcc7c267d8710e05e2f191cba1a53",
    "8e1e444726cad61d492dd656bde91a33460109ef89448f9f251d58d6bd2efb35",
    "95728ccce2aa38e92ed750c57520e663c687f8ddc1fc9e743ae377795d338573",
    "9cc7de53400de22b7c037731be3ec169730546ffa8ce1d869bca509ce9aaf096",
    "a452edccdb85434e6cdd874116d8e3ad1b3c1f24351519a2c59e171530bfb651",
    "a65c7c024a58c4b4593735d717fce3ced17180609edb936a7911d0440dd1d670",
    "a95bc16631ae2b6fadb455ee018da0adc2703e56d89e3eed074ce56d2f7b1b6a",
    "b36262d570d74229ebfb879743731e71fa4419e029ad69c28a25b91df23c1c83",
    "b733a73fb7e04647579dcaa23087708c97e2662f2cb0c1b55028af119c1eb0ab",
    "be9d587defa1f0c09ef49eb17e206983a5f8f8289e4281860bd0ee5a19592c67",
    "c0c1c54c2a31c57a7761f17a80e9c27585c5bbae136e5dfda691505957ea6356",
    "d20dbd6a870c25193970ab56921ac6c12c60f19b53ca5cf7d8d30e89adf83cda",
    "dc795218d7f74fd68b0cd3c44c1a2f3116559c769384e979f9bebe7f78aa41f7",
    "f51e6c5dbcf106cd1d3255700b82ff9222408e3febce8715b27579b6b9b168e8",
})  # fmt: skip
#: sha256 of upper-case tokens denied case-sensitively (the lower-case word is ordinary English)
DENIED_EXACT = frozenset({"b5833faa1c49a66619348169b4ec14a2df8f05ff5d1ec47aefdf95b829ffa11c"})

_RAW = re.compile(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*")
_PIECE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})")
_IPV4 = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?!\.?\d)")
_RESERVED_TLDS = (".example", ".invalid", ".test", ".localhost")  # RFC 2606 / 6761
_DOC_NETS = tuple(ipaddress.ip_network(n) for n in ("127.0.0.0/8", "0.0.0.0/32", "192.0.2.0/24", "198.51.100.0/24",
                                                     "203.0.113.0/24"))  # fmt: skip
_SKIP_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
_SKIP_SUFFIXES = {".pyc", ".pyo"}


def _sha(word: str) -> str:
    return hashlib.sha256(word.encode()).hexdigest()


def _candidates(raw: str) -> set[str]:
    pieces = [p.lower() for part in re.split(r"[-_]", raw) for p in _PIECE.findall(part)]
    out = {raw.lower(), re.sub(r"[-_]", "-", raw.lower()), re.sub(r"[-_]", "", raw.lower())}
    for i in range(len(pieces)):
        for j in range(i + 1, min(len(pieces), i + 4) + 1):
            run = pieces[i:j]
            out |= {"-".join(run), "".join(run)}
    return out


def _findings(text: str, denied: frozenset[str] = DENIED, exact: frozenset[str] = DENIED_EXACT) -> set[str]:
    """Every deny-listed word, email and non-documentation IPv4 in `text`, by kind and digest prefix."""
    found: set[str] = set()
    for raw in _RAW.findall(text):
        found |= {f"word sha256:{_sha(w)[:12]}" for w in _candidates(raw) if _sha(w) in denied}
        tokens = {t for part in re.split(r"[-_]", raw) for t in (part, *_PIECE.findall(part))}
        found |= {f"word sha256:{_sha(t)[:12]}" for t in tokens if _sha(t) in exact}
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


def members() -> dict[str, pathlib.Path]:
    """Every workspace package directory (each `packages/*` with a `pyproject.toml`), by name."""
    return {p.name: p for p in sorted((ROOT / "packages").iterdir()) if (p / "pyproject.toml").is_file()}


def _scanned(pkg_dir: pathlib.Path) -> list[pathlib.Path]:
    """Every text file of one package: the source tree (data files included), the tests, the docs
    and the project metadata."""
    files = [
        p
        for top in ("src", "tests", "docs")
        for p in sorted((pkg_dir / top).rglob("*"))
        if p.is_file() and p.suffix not in _SKIP_SUFFIXES and not (_SKIP_DIRS & set(p.parts))
    ]
    return [*files, *(pkg_dir / n for n in ("README.md", "CHANGELOG.md", "pyproject.toml"))]


def test_no_file_names_a_consumer() -> None:
    packages = members()
    assert {"primitives-kit", "platform-kit", "pack-contracts"} <= set(packages), packages
    hits: set[str] = set()
    for pkg_dir in packages.values():
        files = _scanned(pkg_dir)
        # each walk must find its own files: the three metadata files are always appended, so a
        # total count alone passes a package whose source walk found nothing
        for top in ("src", "tests"):
            assert any(p.suffix == ".py" and (pkg_dir / top) in p.parents for p in files), (pkg_dir, top)
        hits |= {
            f"{p.relative_to(ROOT).as_posix()}: {f}"
            for p in files
            for f in _findings(p.read_text(encoding="utf-8"))
        }  # fmt: skip
    assert not hits, sorted(hits)


def test_the_name_checker_fires_both_ways() -> None:
    """Must-fire: a deny-listed word (assembled, so this file does not spell it) in every shape the
    tokenizer claims, the case-sensitive token, a real-looking email and a private address (also at a
    sentence end) are each found; the reserved and documentation forms, and the word inside a longer
    word, are not."""
    word, token = "q" * 3, "".join(reversed("EGDE"))
    pair = ("".join(reversed("edart")), "".join(reversed("atad")))  # a two-word deny-listed name
    hit = {f"word sha256:{_sha(word)[:12]}"}
    pair_hit = {f"word sha256:{_sha('-'.join(pair))[:12]}", f"word sha256:{_sha(''.join(pair))[:12]}"}
    assert _sha(word) in DENIED and _sha(token) in DENIED_EXACT and _sha("-".join(pair)) in DENIED
    for shape in (f"symbol {word.upper()} here", f"{word.upper()}Chain", f"{word}0dte", f"a_{word}_b"):
        assert _findings(shape) == hit, shape
    for joined in ("-".join(pair), "_".join(pair), "".join(pair), pair[0].title() + pair[1].title(),
                   f"x_{pair[0]}_{pair[1]}_test"):  # fmt: skip
        assert _findings(joined) >= {f"word sha256:{_sha(''.join(pair))[:12]}"}, joined
        assert _findings(joined) <= pair_hit, joined
    assert _findings(f"an {token}_FLAG env") == {f"word sha256:{_sha(token)[:12]}"}
    assert {f"word sha256:{_sha(token)[:12]}"} <= _findings(f"{token}Host")  # and the host-name run itself
    assert _findings(f"the {token.lower()} of the cliff, {word}x, {word}ueue") == set()
    mail, ip = "@".join(("ops", "corp.io")), ".".join(("10", "1", "2", "3"))  # neither spelled whole here
    assert _findings(f"{mail} and {ip}") == {"email at @corp.io", f"ipv4 {ip}"}
    assert _findings(f"connect to {ip}.") == {f"ipv4 {ip}"}
    assert _findings("ops@vendor.example, u:pw@db:5432, 127.0.0.1, 192.0.2.7, 300.1.1.1, 1.2.3.4.5") == set()
    assert _findings("zebra", denied=frozenset({_sha("zebra")})) == {f"word sha256:{_sha('zebra')[:12]}"}
