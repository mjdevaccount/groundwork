"""The watch plane's corners: a streak counter stored as garbage, a runner with no degraded hook, a
subset run nobody contends, an empty claim and an empty watchdog id."""

from __future__ import annotations

import asyncio

import pytest

from platform_kit.watch import runner as wr
from platform_kit.watch.spec import Status
from platform_kit.watch.state import WatchdogStateStore

from .rig import Rig, now, returning, spec


@pytest.mark.parametrize(
    ("prior", "want"),
    [
        ({"last_status": "ok"}, 1),
        ({"last_status": "unknown", "last_metrics": {"unknown_runs": 3}}, 4),
        ({"last_status": "unknown", "last_metrics": {"unknown_runs": "many"}}, 2),
    ],
)
def test_the_unknown_streak_survives_a_garbage_stored_counter(prior: dict[str, object], want: int) -> None:
    assert wr._unknown_runs(prior) == want


@pytest.mark.parametrize(
    ("metrics", "want"), [({"unknown_runs": 2}, 2), (None, 0), ("garbage", 0), ({"unknown_runs": "x"}, 0)]
)
def test_a_stored_streak_reads_zero_from_garbage(metrics: object, want: int) -> None:
    assert wr._stored_streak(metrics) == want


def test_a_runner_without_a_degraded_hook_does_not_fail() -> None:
    rig = Rig(on_degraded=None)
    rig.runner._degraded("anything")  # no hook: a no-op, never an error


def test_a_subset_run_nobody_contends_is_returned_as_run() -> None:
    rig = Rig()
    rig.register(spec("t-one", returning(Status.OK)))
    res = asyncio.run(rig.runner.run_subset(object(), ["t-one"], notify=False))
    assert res["contended"] == [] and [r["id"] for r in res["results"]] == ["t-one"]
    assert now() is not None


def test_claiming_no_ids_touches_no_session() -> None:
    store = WatchdogStateStore(None, "app.watchdog_state")
    assert asyncio.run(store.claim([])) == set()


def test_a_watchdog_needs_an_id() -> None:
    with pytest.raises(ValueError, match="non-empty id"):
        spec(" ", returning(Status.OK))
