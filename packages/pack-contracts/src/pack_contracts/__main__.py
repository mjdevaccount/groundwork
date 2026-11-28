"""`python -m pack_contracts schema | surface | validate FILE...`

- `schema`: print the manifest's JSON Schema (what `pack-manifest.schema.json` must hold).
- `surface`: print the live contract surface (the entry `surface-ledger.json` must end with).
- `validate FILE...`: validate manifest files (.toml / .json) on their own, for a pack's CI.
  Exit 0 = every file valid, 1 = at least one refused (each refusal printed), 2 = usage.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pack_contracts.discovery import ManifestError, parse_manifest
from pack_contracts.schema import manifest_json_schema, render
from pack_contracts.surface import live_surface

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    """The CLI; returns the exit code."""
    parser = argparse.ArgumentParser(prog="python -m pack_contracts")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("schema", help="print the manifest JSON Schema")
    sub.add_parser("surface", help="print the live contract surface")
    check = sub.add_parser("validate", help="validate manifest files")
    check.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args(argv)
    if args.command == "schema":
        sys.stdout.write(render(manifest_json_schema()))
        return 0
    if args.command == "surface":
        sys.stdout.write(json.dumps(live_surface(), indent=2) + "\n")
        return 0
    refused = 0
    for path in args.files:
        try:
            manifest = parse_manifest(path.read_text(encoding="utf-8"), suffix=path.suffix, pack=path.name)
        except (ManifestError, OSError, UnicodeDecodeError) as exc:
            refused += 1
            print(f"REFUSED {path}: {exc}", file=sys.stderr)
            continue
        print(f"ok {path}: {manifest.id} {manifest.version} contract {manifest.contract} tier {manifest.tier}")
    return 1 if refused else 0


if __name__ == "__main__":  # pragma: no cover - the module entry; `main` is tested in-process
    raise SystemExit(main())
