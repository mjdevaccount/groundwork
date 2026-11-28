"""The synthetic pack's plugin: it registers exactly the keys its manifest `provides`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pack_contracts import hookimpl

if TYPE_CHECKING:
    from collections.abc import Callable

    from pack_contracts import Contribution


@dataclass(frozen=True, slots=True)
class Greeting:
    """A contribution of kind `greeting`."""

    kind: str
    name: str
    text: str


@hookimpl
def register_contributions(register: Callable[[Contribution], None]) -> None:
    """Register both greetings the manifest declares."""
    register(Greeting("greeting", "hello", "Hello."))
    register(Greeting("greeting", "goodbye", "Goodbye."))
