"""The contract version: one `MAJOR.MINOR` for the hook surface and the manifest schema together.

It versions what a pack is written against, and it is independent of the distribution's own
version (a docs fix ships a new distribution and leaves the contract alone).

THE RULE (enforced by `pack_contracts.surface.verify_ledger` over the committed ledger):

- A MINOR version may only ADD: a new hook, a new DEFAULTED parameter on an existing hook (pluggy
  >= 1.7 fills a hookspec's defaults when the caller omits them, and passes an implementation only
  the parameters it names), a new protocol, or a new OPTIONAL manifest property. Everything already
  there stays exactly as it was. A pack written against `1.0` loads unchanged on a `1.3` host.
- Anything else is a new MAJOR: renaming the project or an entry-point group, removing or renaming
  a hook or a parameter, a new REQUIRED parameter, a changed annotation or default, a changed
  `firstresult`/`historic`, a protocol member added or changed, and any change to an existing
  manifest property (type, pattern, bounds, enum, default) or to the required set.

A pack declares the version it needs as `contract = "MAJOR.MINOR"`: the host must speak the same
MAJOR and at least that MINOR (`satisfies`).
"""

from __future__ import annotations

import re
from typing import NamedTuple

__all__ = ["CONTRACT_MAJOR", "CONTRACT_MINOR", "CONTRACT_VERSION", "ContractVersion", "satisfies"]

_PATTERN = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


class ContractVersion(NamedTuple):
    """A parsed `MAJOR.MINOR`; tuples order the way versions do."""

    major: int
    minor: int

    @classmethod
    def parse(cls, text: str) -> ContractVersion:
        """`"1.2"` -> `ContractVersion(1, 2)`; anything that is not two plain integers raises ValueError."""
        hit = _PATTERN.fullmatch(text)
        if hit is None:
            raise ValueError(f"contract version {text!r} is not MAJOR.MINOR (two integers, no leading zeros)")
        return cls(int(hit.group(1)), int(hit.group(2)))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


#: the contract this distribution defines
CONTRACT_VERSION: ContractVersion = ContractVersion(1, 0)
CONTRACT_MAJOR: int = CONTRACT_VERSION.major
CONTRACT_MINOR: int = CONTRACT_VERSION.minor


def satisfies(host: ContractVersion, wanted: ContractVersion) -> bool:
    """True when a host speaking `host` can load a pack that declared `wanted`: same major, and the
    host's minor is at least the pack's."""
    return host.major == wanted.major and host.minor >= wanted.minor
