"""LocalLedger's corners: a window claim restored when the budget refuses, and the bounded maps
pruned past `max_keys`; the Notifier's per-call transport and ledger overrides."""

from __future__ import annotations

import asyncio
import datetime as dt

from platform_kit.notify import Budget, Channel, Dedup, LocalLedger, Notice, Notifier, Outcome

from .fakes import MemoryLedger, RecordingTransport

NOW = dt.datetime(2026, 3, 2, 12, 0, tzinfo=dt.UTC)


def _n(ch: Channel, key: str = "k") -> Notice:
    return Notice(ch, key=key, title="T", body="B")


def test_an_expired_window_claim_is_restored_when_the_budget_refuses() -> None:
    led = LocalLedger()
    ch = Channel("s", dedup=Dedup.window(60), budget=Budget(cap=1))
    assert asyncio.run(led.admit(_n(ch, "a"), NOW)) == (None, None)  # spends the one slot
    later = NOW + dt.timedelta(seconds=120)
    first = led.claims[("s", "a")]
    out, _ = asyncio.run(led.admit(_n(ch, "a"), later))  # window expired, but the budget is spent
    assert out is Outcome.BUDGET_REFUSED
    assert led.claims[("s", "a")] == first  # the expired claim is put back, not moved to `later`


def test_every_map_is_pruned_past_max_keys() -> None:
    led = LocalLedger(max_keys=4)
    once = Channel("o", dedup=Dedup.once())
    for i in range(6):
        asyncio.run(led.admit(_n(once, f"k{i}"), NOW + dt.timedelta(seconds=i)))
        asyncio.run(led.admit(_n(once, f"k{i}"), NOW + dt.timedelta(seconds=i)))  # suppressed
    assert len(led.claims) <= 4 and set(led.suppressed) <= set(led.claims)
    for i in range(6):
        ch = Channel(f"b{i}", budget=Budget(cap=1))
        asyncio.run(led.admit(_n(ch), NOW))
        asyncio.run(led.admit(_n(ch), NOW))  # refused
    assert len(led.spent) <= 4 and len(led.refused) <= 4


def test_a_per_call_transport_and_ledger_win_over_the_configured_ones() -> None:
    configured, override = RecordingTransport(), RecordingTransport()
    base, led = MemoryLedger(), MemoryLedger()
    n = Notifier(transport=configured, ledger=base)
    d = asyncio.run(
        n.notify(Notice(Channel("s"), key="k", title="T", body="B", tier="p3"), transport=override, ledger=led, now=NOW)
    )
    assert d.delivered
    assert override.sent and not configured.sent
