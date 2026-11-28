"""The committed JSON Schema is the projection of `PackManifest`, and it refuses what the model refuses."""

from __future__ import annotations

import copy
import json
import tomllib
from importlib.resources import files

from pack_contracts.manifest import SLUG_PATTERN
from pack_contracts.schema import SCHEMA_ID, SCHEMA_RESOURCE, committed_schema, manifest_json_schema, render


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
    assert schema["properties"]["provides"]["additionalProperties"] is False
    assert schema["properties"]["needs"]["additionalProperties"] is False
    assert schema["properties"]["provides"]["propertyNames"]["pattern"] == SLUG_PATTERN
    assert set(schema["required"]) == {"id", "version", "contract", "tier", "provides"}


def test_the_drift_gate_fires() -> None:
    drifted = copy.deepcopy(manifest_json_schema())
    drifted["properties"]["id"]["maxLength"] = 65
    assert drifted != manifest_json_schema()


def test_the_example_manifest_uses_only_schema_properties(example_manifest: str) -> None:
    assert set(tomllib.loads(example_manifest)) <= set(manifest_json_schema()["properties"])
