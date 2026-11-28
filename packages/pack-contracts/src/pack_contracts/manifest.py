"""`PackManifest`: what a pack declares about itself, read and validated before any of its code runs.

A pack ships one manifest file (TOML or JSON) inside its package and names it under the entry-point
group `pack_contracts.manifest` (`pack_contracts.discovery`). The host reads every manifest first,
so it can refuse a pack, or two packs that collide, without importing either.

    id = "example"                  # == the entry-point name; a slug
    version = "1.0.0"               # == the distribution's version
    contract = "1.0"                # the contract MAJOR.MINOR it is written against
    tier = "loads"                  # the conformance tier it claims
    title = "Example pack"          # optional

    [provides]                      # kind -> names: every key the pack registers, and nothing else
    greeting = ["hello", "goodbye"]

    [needs]                         # kind -> names: keys the host or another pack must provide
    clock = ["utc"]

BORROWED, and from where:

- napari npe2 `PluginManifest` (npe2 0.10.2, `npe2/manifest/schema.py`): a manifest named by its
  own entry-point group and read before the plugin is imported; `schema_version` as the contract
  the plugin targets; the manifest's `name` must equal the package's. HARDENED: npe2 only WARNS
  when a manifest targets a newer schema than the host and ignores unknown keys
  (`extra="ignore"`); here a contract the host does not satisfy and an unknown key both refuse.
- Home Assistant `manifest.json` (hassfest `script/hassfest/manifest.py`): `domain` as a slug id,
  `dependencies` as what the integration needs, `quality_scale` as a cumulative tier
  (bronze < silver < gold < platinum) that rules are checked against. Here `needs` names
  CAPABILITIES (`kind` + name), not other packs: packs stay independent of each other, and any
  provider satisfies a need.
- Apache Airflow `provider_info` (`airflow-core/src/airflow/provider_info.schema.json`): one list
  per contribution kind (`operators`, `hooks`, `connection-types`, ...), and `lifecycle`
  (incubation < production < mature) as a declared maturity. Here the kinds are not a closed list:
  the contracts know no domain, so `kind` is any slug and the host decides what each kind means.

Every value type here is frozen; unknown is `None`, never an empty string.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_serializer, field_validator, model_validator

from pack_contracts.contract import ContractVersion

__all__ = ["SLUG_PATTERN", "Keys", "PackManifest", "Slug", "Tier"]

#: a lower-case identifier: a letter, then letters/digits, `-` or `_` between runs
SLUG_PATTERN = r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$"
Slug = Annotated[str, StringConstraints(pattern=SLUG_PATTERN, max_length=64)]
#: kind -> the names of that kind, each list non-empty and without repeats
Keys = Mapping[Slug, Annotated[tuple[Slug, ...], Field(min_length=1, json_schema_extra={"uniqueItems": True})]]
# A kind that is not a slug is refused by the JSON Schema too, not only by the model. Spelled out
# because pydantic's own projection of a constrained key differs between versions.
_KEYS_SCHEMA: dict[str, Any] = {
    "additionalProperties": False,
    "propertyNames": {"pattern": SLUG_PATTERN, "maxLength": 64},
}


class Tier(StrEnum):
    """The conformance tier a pack CLAIMS. Cumulative: each tier includes the ones before it. The
    claim is checked by whoever owns that tier's check; a host may require a minimum.

    - `declared`: the manifest validates (this package's reader).
    - `loads`: the pack loads through the host's strict loader and registers exactly the keys its
      manifest `provides` (the loader's check).
    - `conformant`: the pack passes the contract conformance kit.
    """

    DECLARED = "declared"
    LOADS = "loads"
    CONFORMANT = "conformant"

    @property
    def rank(self) -> int:
        """0, 1, 2 in the order above."""
        return list(Tier).index(self)

    def at_least(self, other: Tier) -> bool:
        """True when this tier includes `other`."""
        return self.rank >= other.rank


class PackManifest(BaseModel):
    """One pack's declaration. Unknown keys are refused (`extra="forbid"`)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    id: Slug = Field(description="The pack's id: a slug, equal to its entry-point name in both groups.")
    version: Annotated[str, StringConstraints(pattern=r"^[0-9]+(?:\.[0-9]+)*[0-9A-Za-z.+!-]*$", max_length=64)] = Field(
        description="The pack's version. The reader holds it equal to the installed distribution's."
    )
    contract: Annotated[str, StringConstraints(pattern=r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")] = Field(
        description="The contract MAJOR.MINOR the pack is written against. The host must speak the same "
        "MAJOR and at least this MINOR."
    )
    tier: Tier = Field(description="The conformance tier the pack claims (cumulative).")
    provides: Keys = Field(
        json_schema_extra={**_KEYS_SCHEMA, "minProperties": 1},
        description="Every key the pack registers, as kind -> names. A key registered and not declared, or "
        "declared and not registered, is a load failure.",
    )
    needs: Keys = Field(
        default_factory=dict,
        validate_default=True,
        json_schema_extra=_KEYS_SCHEMA,
        description="Keys the host or another pack must provide, as kind -> names. A need nobody provides "
        "is a load failure.",
    )
    title: Annotated[str, StringConstraints(min_length=1, max_length=90)] | None = Field(
        default=None, description="A display name. None = show the id."
    )
    description: Annotated[str, StringConstraints(min_length=1)] | None = Field(
        default=None, description="One paragraph on what the pack is for."
    )

    @field_validator("provides", "needs", mode="after")
    @classmethod
    def _unique_and_frozen(cls, value: Mapping[str, tuple[str, ...]]) -> Mapping[str, tuple[str, ...]]:
        for kind, names in value.items():
            dupes = sorted({n for n in names if names.count(n) > 1})
            if dupes:
                raise ValueError(f"kind {kind!r} lists {dupes} more than once")
        return MappingProxyType(dict(value))

    @field_validator("provides", mode="after")
    @classmethod
    def _provides_something(cls, value: Mapping[str, tuple[str, ...]]) -> Mapping[str, tuple[str, ...]]:
        if not value:
            raise ValueError("a pack provides at least one key")
        return value

    @model_validator(mode="after")
    def _no_self_need(self) -> PackManifest:
        own = self.provided() & self.needed()
        if own:
            raise ValueError(f"a pack does not need what it provides itself: {sorted(own)}")
        return self

    @field_serializer("provides", "needs")
    def _plain(self, value: Mapping[str, tuple[str, ...]]) -> dict[str, list[str]]:
        return {kind: list(names) for kind, names in value.items()}

    def __hash__(self) -> int:
        """By value, so a host can keep manifests in a set or key a mapping by them. pydantic's
        frozen hash would hash the field values, and a read-only mapping (`provides`, `needs`) is
        not hashable."""
        return hash(
            (
                self.id,
                self.version,
                self.contract,
                self.tier,
                self.provided(),
                self.needed(),
                self.title,
                self.description,
            )
        )

    @property
    def contract_version(self) -> ContractVersion:
        """`contract` parsed."""
        return ContractVersion.parse(self.contract)

    def provided(self) -> frozenset[tuple[str, str]]:
        """Every `(kind, name)` the pack declares it registers."""
        return frozenset((kind, name) for kind, names in self.provides.items() for name in names)

    def needed(self) -> frozenset[tuple[str, str]]:
        """Every `(kind, name)` the pack declares it needs."""
        return frozenset((kind, name) for kind, names in self.needs.items() for name in names)
