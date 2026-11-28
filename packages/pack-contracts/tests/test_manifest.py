"""`PackManifest`: what it accepts, what it refuses (each refusal proven to fire), and that it is frozen."""

from __future__ import annotations

import tomllib
from typing import Any

import pytest
from pydantic import ValidationError

from pack_contracts.contract import ContractVersion
from pack_contracts.manifest import PackManifest, Tier


def _base(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "example",
        "version": "1.0.0",
        "contract": "1.0",
        "tier": "declared",
        "provides": {"greeting": ["hello"]},
    }
    data.update(over)
    return data


def test_the_example_manifest_validates(example_manifest: str) -> None:
    m = PackManifest.model_validate(tomllib.loads(example_manifest))
    assert (m.id, m.version, m.contract, m.tier) == ("example", "1.0.0", "1.0", Tier.LOADS)
    assert m.provided() == {("greeting", "hello"), ("greeting", "goodbye")}
    assert m.needed() == {("clock", "utc")}
    assert m.contract_version == ContractVersion(1, 0)
    assert m.title == "Example pack"


def test_the_minimal_manifest_defaults_unknown_to_none() -> None:
    m = PackManifest.model_validate(_base())
    assert m.title is None and m.description is None
    assert dict(m.needs) == {} and m.needed() == frozenset()


def test_it_round_trips_through_json() -> None:
    m = PackManifest.model_validate(_base(needs={"clock": ["utc"]}))
    assert m.model_dump()["provides"] == {"greeting": ["hello"]}
    assert PackManifest.model_validate_json(m.model_dump_json()) == m


def test_it_is_frozen_all_the_way_down() -> None:
    m = PackManifest.model_validate(_base())
    with pytest.raises(ValidationError):
        m.id = "other"  # type: ignore[misc]
    with pytest.raises(TypeError):
        m.provides["more"] = ("x",)  # type: ignore[index]
    with pytest.raises(TypeError):
        m.needs["more"] = ("x",)  # type: ignore[index]


@pytest.mark.parametrize(
    ("over", "needle"),
    [
        ({"unknown": 1}, "extra_forbidden"),
        ({"id": "Example"}, "string_pattern_mismatch"),
        ({"id": "-x"}, "string_pattern_mismatch"),
        ({"id": "a" * 65}, "string_too_long"),
        ({"version": "v1"}, "string_pattern_mismatch"),
        ({"contract": "1"}, "string_pattern_mismatch"),
        ({"contract": "01.0"}, "string_pattern_mismatch"),
        ({"contract": "1.0.0"}, "string_pattern_mismatch"),
        ({"tier": "gold"}, "enum"),
        ({"provides": {}}, "provides at least one key"),
        ({"provides": {"greeting": []}}, "too_short"),
        ({"provides": {"Greeting": ["hello"]}}, "string_pattern_mismatch"),
        ({"provides": {"greeting": ["hello", "hello"]}}, "more than once"),
        ({"needs": {"clock": ["utc", "utc"]}}, "more than once"),
        ({"needs": {"greeting": ["hello"]}}, "does not need what it provides"),
        ({"title": ""}, "string_too_short"),
        ({"description": ""}, "string_too_short"),
    ],
)
def test_each_refusal_fires(over: dict[str, Any], needle: str) -> None:
    with pytest.raises(ValidationError) as caught:
        PackManifest.model_validate(_base(**over))
    assert needle in str(caught.value) or needle in {e["type"] for e in caught.value.errors()}


@pytest.mark.parametrize("missing", ["id", "version", "contract", "tier", "provides"])
def test_every_required_field_is_required(missing: str) -> None:
    data = _base()
    del data[missing]
    with pytest.raises(ValidationError, match=missing):
        PackManifest.model_validate(data)


def test_tiers_are_cumulative() -> None:
    assert [t.rank for t in Tier] == [0, 1, 2]
    assert Tier.CONFORMANT.at_least(Tier.LOADS) and Tier.LOADS.at_least(Tier.LOADS)
    assert not Tier.DECLARED.at_least(Tier.LOADS)
