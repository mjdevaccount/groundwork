"""platform_kit.watch -- the watchdog plane: declare absence detectors, run them, remember.

    spec     Status, Probe, WatchdogSpec, WatchVocab (the consumer's owners / watch kinds / push
             severities), WatchRegistry (strict, duplicate id raises) -- stdlib
    runner   WatchRunner: one market gate (injected), probe-per-savepoint, DB-backed transition
             dedup + re-alert, never-raising pager, the stored read with staleness -- stdlib
    pager    notify_pager(notifier, channel): page through `platform_kit.notify` -- stdlib
    state    WatchdogStateStore over the consumer's state table + its `ddl` -- extra `[sql]`

Every consumer fact is an input: the owner list, the watch kinds, the market gate,
the state table, the pager, the investigation trigger and the sweep's timeline unit as inputs.
"""
