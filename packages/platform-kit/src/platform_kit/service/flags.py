"""Typed raw-env flag families: one env PREFIX declared once, parsed strictly (extra `[service]`).

In the application this came from, these families
had been read as bare `os.environ.get(...)` at ~26 sites, and a typo'd VALUE there was a silent
default: `WORKER_APPLY_RETRY=true` compared `== "1"` and quietly stayed OFF. Declared once in a
`Family` subclass and parsed strictly, a value the old read could only misread is a pydantic
ValidationError at construction -- which is process start for a consumer that builds its families
in the lifespan or at import, so a health gate sees a crashed boot instead of a wrong flag.

The two boolean shapes keep the old reads' semantics byte for byte on every value the old read
could take meaningfully:

  * `Flag01`   was `os.environ.get(K, d) == "1"`: "1" -> True; "0" / "" -> False; else ERROR.
  * `Truthy`   was `.lower() in ("1","true","yes")`: those -> True; "", "0", "false", "no" -> False;
               else ERROR.

Deliberately NOT a service's main Settings class: no `.env` file (the raw reads never saw one),
exact-case names (os.environ is case-sensitive on Linux), `extra="ignore"` (the process env holds
every other family too). Every field carries its exact-case `alias` -- the ENV NAMES are the
consumer's; this module names none.

    class WorkerFlags(Family):
        apply_retry: Flag01 = Field(False, alias="WORKER_APPLY_RETRY")
        min_score: float = Field(0.02, alias="RANKER_MIN_SCORE")

    WorkerFlags().apply_retry      # reads the environment NOW (no cache)

Instantiate per read: an import-time consumer builds one at import, a call-time consumer builds one
per call. No cache, so a test's `monkeypatch.setenv` is honored where it was.
"""

from __future__ import annotations

from typing import Annotated, ClassVar

from pydantic import BeforeValidator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Family", "Flag01", "Truthy", "parse_flag01", "parse_truthy"]


def parse_flag01(v: object) -> object:
    """`== "1"` made strict: "1" / "0" / "" (and real bools) parse; anything else raises."""
    if isinstance(v, bool):
        return v
    s = str(v)
    if s in ("1", "0", ""):
        return s == "1"
    raise ValueError(f"expected '1' or '0' (was read as == '1', so {s!r} silently meant OFF)")


def parse_truthy(v: object) -> object:
    """`.lower() in ("1","true","yes")` made strict: the off-words are listed, anything else raises."""
    if isinstance(v, bool):
        return v
    s = str(v).lower()
    if s in ("1", "true", "yes"):
        return True
    if s in ("", "0", "false", "no"):
        return False
    raise ValueError(f"expected 1/true/yes or 0/false/no/empty (so {s!r} silently meant OFF)")


Flag01 = Annotated[bool, BeforeValidator(parse_flag01)]
Truthy = Annotated[bool, BeforeValidator(parse_truthy)]


class Family(BaseSettings):
    """One env PREFIX, declared once, parsed strictly. Subclass per prefix; every field carries its
    exact-case `alias`. Instantiating reads the environment at that moment (no cache)."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        case_sensitive=True, extra="ignore", populate_by_name=True
    )
