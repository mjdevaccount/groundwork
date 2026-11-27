"""The budget contract: the error tree, the quota reading's validation, the protocol's shape."""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt

import pytest
from pydantic import ValidationError

import primitives_kit
from primitives_kit import BudgetError, BudgetExhausted, BudgetUnavailable, QuotaReading, RateBudget

RESETS = dt.datetime(2030, 1, 2, 15, 30, tzinfo=dt.UTC)


def test_both_refusals_are_one_budget_error() -> None:
    for kind in (BudgetExhausted, BudgetUnavailable):
        with pytest.raises(BudgetError):
            raise kind("no permit")
    assert not issubclass(BudgetExhausted, BudgetUnavailable)
    assert not issubclass(BudgetUnavailable, BudgetExhausted)


def test_a_library_family_subclasses_the_tree_and_stays_catchable() -> None:
    """A library keeps its own base AND joins the tree, so either catch sees its refusal."""

    class LibraryError(Exception):
        pass

    class LibraryUnavailable(LibraryError, BudgetUnavailable):
        def __init__(self, key: str, why: str) -> None:
            super().__init__(f"budget {key} unavailable: {why}")
            self.key = key

    exc = LibraryUnavailable("k", "store slow")
    assert isinstance(exc, LibraryError) and isinstance(exc, BudgetError)
    assert str(exc) == "budget k unavailable: store slow"


def test_a_reading_is_positional_frozen_and_complete() -> None:
    q = QuotaReading("vendor", 120, 100, 20, RESETS, "/v1/quotes", refused=True, category="market")
    assert (q.available, q.refused, q.category) == (20, True, "market")
    with pytest.raises(dataclasses.FrozenInstanceError):
        q.used = 0  # type: ignore[misc]
    unreported = QuotaReading("vendor", None, None, None, None, "/v1/quotes")
    assert unreported.refused is False and unreported.category is None


@pytest.mark.parametrize(
    "bad",
    [
        {"used": -1},
        {"available": -5},
        {"allowed": "many"},
        {"resets_at": dt.datetime(2030, 1, 2, 15, 30)},  # naive: unknowable instant  # noqa: DTZ001
    ],
    ids=["negative-used", "negative-available", "not-a-count", "naive-reset"],
)
def test_a_reading_refuses_what_cannot_be_a_quota(bad: dict[str, object]) -> None:
    fields = {"provider": "v", "allowed": 1, "used": 0, "available": 1, "resets_at": RESETS, "endpoint": "/"}
    with pytest.raises(ValidationError):
        QuotaReading(**{**fields, **bad})  # type: ignore[arg-type]


def test_a_reading_refuses_an_unknown_field() -> None:
    with pytest.raises(ValidationError):
        QuotaReading("v", 1, 0, 1, RESETS, "/", surprise=1)  # type: ignore[call-arg]


class _Window:
    def __init__(self) -> None:
        self.seen: list[QuotaReading] = []

    async def acquire(self, weight: int = 1) -> float:
        return 0.0 * weight

    def observe(self, quota: QuotaReading) -> None:
        self.seen.append(quota)


class _NoObserve:
    async def acquire(self, weight: int = 1) -> float:
        return 0.0 * weight


def test_the_protocol_is_acquire_and_observe() -> None:
    budget = _Window()
    assert isinstance(budget, RateBudget)
    assert not isinstance(_NoObserve(), RateBudget)
    assert asyncio.run(budget.acquire(3)) == 0.0
    budget.observe(QuotaReading("v", None, None, 0, RESETS, "/", refused=True))
    assert budget.seen[0].refused


def test_the_package_exports_the_contract_and_its_version() -> None:
    assert set(primitives_kit.__all__) == {
        "BudgetError",
        "BudgetExhausted",
        "BudgetUnavailable",
        "QuotaReading",
        "RateBudget",
        "__version__",
    }
    assert primitives_kit.__version__.count(".") == 2
