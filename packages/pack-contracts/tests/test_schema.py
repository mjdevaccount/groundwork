"""The committed JSON Schema is the projection of `PackManifest`, and it refuses the shapes a schema
can express: unknown keys, bad slugs, empty or repeated name lists. (Cross-field rules, such as a
pack needing what it provides itself, are the model's alone.)"""

from __future__ import annotations

import json
import tomllib
from importlib.resources import files
from typing import TYPE_CHECKING, Any

from pack_contracts import schema as schema_module
from pack_contracts.manifest import SLUG_PATTERN
from pack_contracts.schema import SCHEMA_ID, SCHEMA_RESOURCE, committed_schema, manifest_json_schema, render

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_the_committed_schema_is_the_models_projection() -> None:
    """Drift gate: regenerate with `python -m pack_contracts schema > src/pack_contracts/pack-manifest.schema.json`."""
    assert committed_schema() == manifest_json_schema()


def test_the_committed_file_is_in_the_rendered_form() -> None:
    """Formatting only (key order is pydantic's and varies by version; content is the test above)."""
    text = files("pack_contracts").joinpath(SCHEMA_RESOURCE).read_text(encoding="utf-8").replace("\r\n", "\n")
    assert text == render(json.loads(text))


def test_the_schema_names_its_dialect_and_itself() -> None:
    schema = manifest_json_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == SCHEMA_ID and SCHEMA_ID.endswith(SCHEMA_RESOURCE)
    assert schema["additionalProperties"] is False
    for field in ("provides", "needs"):
        keys = schema["properties"][field]
        assert keys["additionalProperties"] is False
        assert keys["propertyNames"]["pattern"] == SLUG_PATTERN
        (names,) = keys["patternProperties"].values()
        assert names["minItems"] == 1 and names["uniqueItems"] is True
    assert set(schema["required"]) == {"id", "version", "contract", "tier", "provides"}


def test_the_drift_gate_fires(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Must-fire: a committed file one keyword away from the model fails the comparison the gate makes."""
    drifted: dict[str, Any] = json.loads(render(manifest_json_schema()))
    drifted["properties"]["id"]["maxLength"] = 65
    (tmp_path / SCHEMA_RESOURCE).write_text(render(drifted), encoding="utf-8")
    monkeypatch.setattr(schema_module, "files", lambda _pkg: tmp_path)
    assert committed_schema() == drifted
    assert committed_schema() != manifest_json_schema()


def test_the_example_manifest_uses_only_schema_properties(example_manifest: str) -> None:
    assert set(tomllib.loads(example_manifest)) <= set(manifest_json_schema()["properties"])
