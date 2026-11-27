"""Small shared contracts: protocols, error trees and value types, with no behaviour of their own.

A contract lives here only when two libraries that cannot import each other each carried a copy
and the copies had already drifted apart. Today that is one contract:

- `budget`: the rate-budget protocol (`RateBudget`), its error tree (`BudgetError` >
  `BudgetExhausted` / `BudgetUnavailable`) and the vendor's quota report (`QuotaReading`).

The package depends on the standard library and pydantic, nothing else.
"""

from importlib.metadata import version

from primitives_kit.budget import BudgetError, BudgetExhausted, BudgetUnavailable, QuotaReading, RateBudget

__all__ = [
    "BudgetError",
    "BudgetExhausted",
    "BudgetUnavailable",
    "QuotaReading",
    "RateBudget",
    "__version__",
]

__version__: str = version("primitives-kit")
