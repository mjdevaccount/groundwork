"""The rate-budget contract shared by every library that paces calls to a quota.

Three things, and nothing that implements them:

- `RateBudget`: the protocol a budget satisfies. A caller awaits `acquire` before it sends a
  request and hands the vendor's own count of the window to `observe`.
- `BudgetError`, the base of the two ways a budget says "no permit": `BudgetExhausted` (the
  window had no room inside the maximum wait) and `BudgetUnavailable` (the budget's store could
  not answer, so it fails closed). Both mean the request was never sent: nobody looked.
- `QuotaReading`: the vendor's report of its own window, taken from a response.

A library that raises its own error family subclasses these (`class BudgetExhausted(MyError,
primitives_kit.BudgetExhausted)`), so a caller that catches `BudgetError` catches every budget's
refusal without importing the library that raised it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import AwareDatetime, ConfigDict, NonNegativeInt
from pydantic.dataclasses import dataclass

__all__ = [
    "BudgetError",
    "BudgetExhausted",
    "BudgetUnavailable",
    "QuotaReading",
    "RateBudget",
]


class BudgetError(Exception):
    """A rate budget gave no permit, so the request was never sent. Raise a subclass."""


class BudgetExhausted(BudgetError):
    """No permit was granted within the budget's maximum wait: the window is full."""


class BudgetUnavailable(BudgetError):
    """The budget's store could not answer (unreachable, timed out, a lock held too long).

    A budget fails CLOSED: it raises this instead of granting a permit it could not account for.
    """


@dataclass(frozen=True, slots=True, config=ConfigDict(extra="forbid"))
class QuotaReading:
    """The vendor reported its request quota on a response.

    Attributes:
        provider: whose quota.
        allowed: requests allowed in the vendor's window, None when not reported.
        used: requests used in the window, None when not reported.
        available: requests left in the window, None when not reported.
        resets_at: when the vendor's window resets (timezone-aware), None when not reported.
        endpoint: the request path the report came on (no query string).
        refused: the vendor REFUSED this request for quota, rather than only reporting its
            count. A budget should hold until `resets_at`. A refusal with no count carries
            `available=0`: by refusing, the vendor said nothing is left.
        category: the vendor's quota bucket the endpoint draws on, in the vendor's own words.
            None when the vendor has one bucket.
    """

    provider: str
    allowed: NonNegativeInt | None
    used: NonNegativeInt | None
    available: NonNegativeInt | None
    resets_at: AwareDatetime | None
    endpoint: str
    refused: bool = False
    category: str | None = None


@runtime_checkable
class RateBudget(Protocol):
    """A rate budget: a request waits here for a permit before it is sent."""

    async def acquire(self, weight: int = 1) -> float:
        """Wait for `weight` permits and return the seconds waited.

        Raises:
            BudgetExhausted: no permit within the budget's maximum wait.
            BudgetUnavailable: the budget's store could not answer.
        """
        ...

    def observe(self, quota: QuotaReading) -> None:
        """Take the vendor's own count of the window. May do nothing; never raises."""
        ...
