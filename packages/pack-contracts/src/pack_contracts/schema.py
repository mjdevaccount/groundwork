"""The JSON Schema (2020-12) projection of `PackManifest`, committed beside the model.

`PackManifest` is the source; `pack-manifest.schema.json` (shipped in this package) is generated
from it with `python -m pack_contracts schema`, and the suite fails when the two differ. Editors,
non-Python tooling and a host that validates a manifest without this package read the file.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from pack_contracts.manifest import PackManifest

__all__ = ["SCHEMA_ID", "SCHEMA_RESOURCE", "committed_schema", "manifest_json_schema", "render"]

SCHEMA_RESOURCE = "pack-manifest.schema.json"
SCHEMA_ID = "https://github.com/mjdevaccount/groundwork/blob/base/packages/pack-contracts/src/pack_contracts/" + (
    SCHEMA_RESOURCE
)
_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def manifest_json_schema() -> dict[str, Any]:
    """`PackManifest.model_json_schema()` (validation mode) with `$schema` and `$id` set."""
    return {"$schema": _DIALECT, "$id": SCHEMA_ID, **PackManifest.model_json_schema(mode="validation")}


def committed_schema() -> dict[str, Any]:
    """The schema file shipped in this package."""
    data: dict[str, Any] = json.loads(files("pack_contracts").joinpath(SCHEMA_RESOURCE).read_text(encoding="utf-8"))
    return data


def render(document: dict[str, Any]) -> str:
    """The committed text form: two-space indent, keys in model order, a trailing newline."""
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
