# primitives-kit

Small shared contracts with no behaviour of their own. A contract lives here only when two
libraries that cannot import each other each carried a copy, and the copies had already drifted
apart. The package depends on the standard library and pydantic, nothing else.

## The rate-budget contract

```python
from primitives_kit import BudgetError, BudgetExhausted, BudgetUnavailable, QuotaReading, RateBudget
```

- **`RateBudget`** is a protocol. A request awaits `acquire(weight)` before it is sent, and the
  vendor's own count of the window goes to `observe(reading)`.
- **`BudgetError`** is the base of the two ways a budget says "no permit":
  - `BudgetExhausted`: the window had no room inside the maximum wait;
  - `BudgetUnavailable`: the budget's store could not answer, so the budget fails closed.

  Either way the request was never sent. Nobody looked at the vendor, so the caller has no answer
  rather than a wrong one.
- **`QuotaReading`** is the vendor's report of its window, taken from one response. It is frozen
  and validated: counts are non-negative, and the reset time must carry a timezone.

A library with its own error family joins the tree by subclassing, so a caller that catches
`BudgetError` catches every budget's refusal:

```python
class BudgetUnavailable(MyLibraryError, primitives_kit.BudgetUnavailable): ...
```

## Install

Pin a release tag of this package. The source sits in a subdirectory of the workspace repository:

```toml
# uv
[tool.uv.sources]
primitives-kit = { git = "https://github.com/mjdevaccount/groundwork", tag = "primitives-kit-v0.1.0", subdirectory = "packages/primitives-kit" }
```

```text
# pip / PEP 508
primitives-kit @ git+https://github.com/mjdevaccount/groundwork@primitives-kit-v0.1.0#subdirectory=packages/primitives-kit
```
