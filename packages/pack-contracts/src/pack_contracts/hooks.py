"""The pluggy surface a pack implements: the project name, the markers, the hookspecs.

A pack imports `hookimpl` from HERE and nothing from the host's implementation (the rule
Backstage's `*-node` packages keep: extensions depend on the extension-point package, never on the
backend that runs them).

    from pack_contracts import hookimpl

    @hookimpl
    def register_contributions(register):
        register(Greeting(kind="greeting", name="hello"))

The host builds `pluggy.PluginManager(PROJECT_NAME)`, adds `PackSpec` BEFORE any pack registers,
and registers each pack's module under the entry-point group `PLUGIN_GROUP`, by the same name its
manifest has under `pack_contracts.manifest`.

Versioning is `pack_contracts.contract`'s rule, held by the committed ledger
(`pack_contracts.surface`): a MINOR adds a hook or a DEFAULTED parameter, nothing else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

import pluggy

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["PLUGIN_GROUP", "PROJECT_NAME", "Contribution", "PackSpec", "contribution_key", "hookimpl", "hookspec"]

#: the pluggy project name: hosts build `PluginManager(PROJECT_NAME)`; the markers below carry it
PROJECT_NAME = "pack"
#: the entry-point group that names a pack's plugin object (its module, usually)
PLUGIN_GROUP = "pack_contracts.plugin"

hookspec: pluggy.HookspecMarker = pluggy.HookspecMarker(PROJECT_NAME)
hookimpl: pluggy.HookimplMarker = pluggy.HookimplMarker(PROJECT_NAME)


@runtime_checkable
class Contribution(Protocol):
    """Anything a pack registers: it names its `kind` and its `name`. `(kind, name)` is the key the
    pack's manifest declares under `provides`; a frozen dataclass or a frozen pydantic model with
    those two fields conforms."""

    @property
    def kind(self) -> str:
        """The contribution's kind: a slug the host gives a meaning to."""
        ...

    @property
    def name(self) -> str:
        """The contribution's name, unique within its kind across every loaded pack."""
        ...


def contribution_key(thing: Contribution) -> tuple[str, str]:
    """`(kind, name)`: the key a contribution registers under, and the one its manifest declares."""
    return (thing.kind, thing.name)


class PackSpec:
    """The hookspecs of contract 1.x. Each one is in the committed surface ledger."""

    @hookspec
    def register_contributions(self, register: Callable[[Contribution], None]) -> None:
        """Call `register(thing)` once for every key the pack's manifest `provides`, and for no
        other. The host collects them into one registry keyed by `contribution_key` and refuses a
        duplicate key, an undeclared key, and a declared key never registered."""
