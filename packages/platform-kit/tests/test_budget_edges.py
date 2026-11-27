"""PgWindowBudget without a database: argument checks, the create race, a broken wait hook, a
repeated config conflict and the flush throttle. A scripted session stands in for the row."""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import types
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any

import pytest

import primitives_kit
from platform_kit.budget import BudgetExhausted, BudgetUnavailable, PgWindowBudget, Window

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable


class _Result:
    def __init__(self, rows: list[tuple[Any, ...]], scalar: Any = None) -> None:
        self._rows, self._scalar = rows, scalar

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows

    def scalar(self) -> Any:
        return self._scalar


class _Session:
    """Answers the acquire statement from `rows` (one entry per attempt) and the flush with False."""

    def __init__(self, rows: list[list[tuple[Any, ...]]], on_flush: Callable[[], None] | None = None) -> None:
        self.rows, self.on_flush, self.flushes = rows, on_flush, 0

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> _Result:
        sql = str(stmt)
        if "set_config" in sql:
            return _Result([])
        if "refused" in (params or {}):
            self.flushes += 1
            if self.on_flush is not None:
                self.on_flush()
            return _Result([], scalar=False)
        return _Result(self.rows.pop(0) if len(self.rows) > 1 else self.rows[0])

    async def commit(self) -> None:
        return None


def _maker(session: _Session) -> Callable[[], AbstractAsyncContextManager[_Session]]:
    @contextlib.asynccontextmanager
    async def make() -> AsyncIterator[_Session]:
        yield session

    return make


async def _no_sleep(_s: float) -> None:
    return None


def _budget(session: _Session, **kw: Any) -> PgWindowBudget:
    kw.setdefault("max_wait", 5.0)
    return PgWindowBudget(_maker(session), "s.t", "v:k", Window(5, 60), sleep=_no_sleep, **kw)


@pytest.mark.parametrize(
    ("kw", "exc"),
    [
        ({"key": " "}, ValueError),
        ({"window": (5, 60)}, TypeError),
        ({"max_wait": -1}, ValueError),
    ],
)
def test_the_constructor_refuses_a_bad_argument(kw: dict[str, Any], exc: type[Exception]) -> None:
    args: dict[str, Any] = {"key": "v:k", "window": Window(5, 60), "max_wait": 1.0, **kw}
    with pytest.raises(exc):
        PgWindowBudget(_maker(_Session([[]])), "s.t", args["key"], args["window"], max_wait=args["max_wait"])


def test_a_create_race_that_never_settles_is_unavailable() -> None:
    b = _budget(_Session([[]]))  # every attempt returns no row
    with pytest.raises(BudgetUnavailable, match="row create raced"):
        asyncio.run(b.acquire())
    assert b.stats.unavailable == 1


def test_a_broken_wait_hook_is_logged_and_the_wait_goes_on(caplog: pytest.LogCaptureFixture) -> None:
    def hook(_key: str, _wait: float) -> None:
        raise RuntimeError("telemetry down")

    b = _budget(_Session([[(False, 0.01, None, None)], [(True, 0.0, None, None)]]), on_wait=hook)
    with caplog.at_level(logging.WARNING, logger="platform_kit.budget"):
        waited = asyncio.run(b.acquire())
    assert waited > 0 and b.stats.grants == 1 and b.stats.wait_events == 1
    assert "budget_on_wait_hook_failed" in caplog.text


def test_a_config_conflict_is_counted_every_time_and_logged_once(caplog: pytest.LogCaptureFixture) -> None:
    b = _budget(_Session([[(True, 0.0, 9, 30)]]))
    with caplog.at_level(logging.WARNING, logger="platform_kit.budget"):
        asyncio.run(b.acquire())
        asyncio.run(b.acquire())
    assert b.stats.config_conflict == 2
    assert caplog.text.count("budget_config_conflict") == 1


def _reading(used: int) -> types.SimpleNamespace:
    return types.SimpleNamespace(used=used, available=None, resets_at=dt.datetime.now(dt.UTC))


def test_flush_with_nothing_pending_and_inside_the_interval_writes_nothing() -> None:
    s = _Session([[(True, 0.0, None, None)]])
    b = _budget(s, min_flush_interval_s=3600)
    assert asyncio.run(b.flush_observed()) is False  # nothing observed yet
    b.observe(_reading(1))
    assert asyncio.run(b.flush_observed()) is True
    b.observe(_reading(2))
    assert asyncio.run(b.flush_observed()) is False  # throttled: inside min_flush_interval_s
    assert s.flushes == 1
    assert asyncio.run(b.flush_observed(force=True)) is True
    assert s.flushes == 2


def test_a_reading_that_arrives_during_a_flush_is_kept_for_the_next() -> None:
    holder: dict[str, PgWindowBudget] = {}
    s = _Session([[(True, 0.0, None, None)]], on_flush=lambda: holder["b"].observe(_reading(7)))
    b = holder["b"] = _budget(s)
    b.observe(_reading(3))
    assert asyncio.run(b.flush_observed()) is True
    assert asyncio.run(b.flush_observed(force=True)) is True  # the reading observed mid-flush landed now
    assert s.flushes == 2


def test_the_errors_are_primitives_kits_budget_tree() -> None:
    """A caller that catches the shared tree catches this budget's refusals, both kinds, untranslated."""
    assert issubclass(BudgetExhausted, primitives_kit.BudgetExhausted)
    assert issubclass(BudgetUnavailable, primitives_kit.BudgetUnavailable)
    assert not issubclass(BudgetExhausted, primitives_kit.BudgetUnavailable)
    exhausted = _budget(_Session([[(False, 60.0, None, None)]]), max_wait=0.5)
    with pytest.raises(primitives_kit.BudgetError) as ei:
        asyncio.run(exhausted.acquire())
    assert isinstance(ei.value, primitives_kit.BudgetExhausted) and isinstance(ei.value, RuntimeError)
    raced = _budget(_Session([[]]))
    with pytest.raises(primitives_kit.BudgetError) as eu:
        asyncio.run(raced.acquire())
    assert isinstance(eu.value, primitives_kit.BudgetUnavailable)
