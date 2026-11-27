# plugins: one loader contract, a conformance suite, pluggy underneath

Design record for `platform_kit.plugins` and `platform_kit.testing.plugin_conformance`. The module
docstring is the authority for behaviour; this file holds the reasons and what was ruled out.

## Purpose

Code enters a registry by NAME, from the app itself or from another installed distribution, and a
plugin that fails to load stops the process. A plugin that silently did not load is
indistinguishable from one nobody installed, so "warn and continue" is the defect this module
exists to prevent.

## Decision: pluggy is the transport, `Registry` is the store, the contract is shared

- **pluggy (>= 1.7)** does hook dispatch and validates a hookimpl's arguments against its hookspec.
  Discovery is NOT pluggy's `load_setuptools_entrypoints`: that walks distributions unsorted, its
  exception names no plugin, and it skips an already-registered name silently. The loader runs its
  own sorted loop over `importlib.metadata.entry_points`.
- **`platform_kit.registry.Registry`** is the store: a duplicate key raises, and `freeze()` closes
  it after boot.
- **What is shared is the contract and its conformance suite, not one package.** A library that
  must not depend on platform-kit (a public port library on its own release channel) keeps a small
  loader of its own and subclasses `PluginConformance` in its tests, so every implementation is held
  to the same ten rules.
- Checked and not chosen: stevedore 5.9 (logs and continues on a load failure, warns on a name
  conflict unless two callbacks are passed, reads entry points only, so in-repo built-ins would
  need distribution metadata); raw `importlib.metadata.entry_points` alone (it is what the sorted
  loop uses underneath, but pluggy's hook validation and the `register_*(register)` idiom are worth
  keeping).

Hookspec shape, every registry:

```python
class Spec:
    @hookspec
    def register_things(self, register: Callable[[Thing], None]) -> None: ...
```

## The contract (R1-R10)

The rules are listed in the `platform_kit.plugins` docstring; the reason for each:

| # | rule | why |
|---|---|---|
| R1 | hookspecs are added BEFORE any plugin registers | pluggy validates a hookimpl's arguments only against a spec that already exists |
| R2 | built-ins register by `pm.register(obj, name=)`; entry points are for OTHER distributions | an app run from a checkout has no distribution metadata |
| R3 | entry points load in the loader's own loop, sorted by name | `load_setuptools_entrypoints` is unsorted and its failure names no plugin |
| R4 | every failure raises `PluginLoadError(group, plugin, stage)` | a loader that warns and continues is a guard that cannot fire |
| R5 | a duplicate key raises and names both plugins | silent overwrite means the last install wins |
| R6 | pin: `None` = built-ins + every installed plugin; `""` = built-ins only; `"a,b"` = built-ins + exactly those, and a listed name that is not installed raises | the missing-plugin case is made fatal |
| R7 | `pm.check_pending()` after loading | a misspelled hookimpl otherwise loads and contributes nothing |
| R8 | `load` returns `Loaded` (names in load order + origin) and logs it | "which plugins is this process running" is otherwise unanswerable |
| R9 | test suites pin the set | a developer's stray installed plugin must not change CI |
| R10 | no order derives from a set or from install order | `pm.get_plugins()` is a set |

## Invariants

1. Loading happens once, at the composition root (app lifespan, daemon main, CLI main). A module
   import never triggers discovery.
2. A registry is frozen after load: a `register` call after the composition root has finished
   raises.
3. A plugin's key namespace is flat and global; a plugin may not shadow a built-in.
4. Blocking (`pm.set_blocked`) is for tests only; production control is the pin.
5. The pin is an ARGUMENT (`load(..., pin=)`). The consumer reads it from its own configuration;
   no library reads an environment variable for it.
6. A public library ships no entry point for a private package, and its CI runs with `pin=""` at
   least once.

## Failure semantics

One exception type, `PluginLoadError`, a subclass of `ImportError`, raised at boot, with `stage` one
of `import`, `register`, `hook`, `duplicate`, `pin`, `pending`. There is no degraded mode: a process
that cannot load a pinned plugin exits non-zero, and the supervisor's restart count is the signal.

## Telemetry

| signal | where it lands | what should watch it |
|---|---|---|
| `plugins_loaded` boot log line (group, names, origin) | the process log | evidence only |
| `Loaded.series()`: `plugins_loaded{group,plugin,origin} = 1` | the consumer's metrics exporter | a consumer watchdog comparing the live set with the pin in its deploy config (a plugin that is simply absent is the one failure that does not raise) |
| a boot failure | the container restart count | the consumer's restart alert |

## Configuration

One pin per group, a deploy-topology value: it names what is installed, not how it behaves.
Production sets it explicitly; unset is for development, and the watchdog above compares against it.

## Conformance suite (`PluginConformance`, every implementation carries all ten)

1. R1: a hookimpl with an argument not in the spec fails at register.
2. R3/R10: two fake entry points returned in both orders give identical `Loaded.plugins`.
3. R4 import: a module that raises on import -> `stage="import"`, naming it; the same set without it
   loads clean.
4. R4 hook: a plugin whose `register_*` raises -> `stage="hook"`.
5. R4 non-conforming: `register(object())` -> `stage="register"`.
6. R5: two plugins registering key `x` -> `stage="duplicate"`, the message names both.
7. R6: pin `""` -> built-ins only with fakes installed; pin `"a"` with `a` absent raises; unset -> all.
8. R7: a misspelled hook name raises at `check_pending`.
9. R2: built-ins load with `entry_points=lambda: ()`.
10. Freeze: `register` after load raises.

## Ruled out

| option | why |
|---|---|
| warn and continue | a guard that cannot fire (OpenBB `provider/registry.py`; stevedore's default) |
| class paths in config (`module:Class`) | config becomes code loading, and a typo is an import error at use time |
| silent overwrite on a duplicate | last install wins (simonw/llm aliases; dramatiq actor redeclare) |
| `pm.load_setuptools_entrypoints` | unsorted, an unnamed failure, skips a registered name silently (pluggy 1.7 `_manager.py`) |
