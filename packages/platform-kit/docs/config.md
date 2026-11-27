# config: every knob has a class, a home, a source and a fingerprint

Design record for `platform_kit.config` (extra `[config]`). The package docstring is the authority
for behaviour; this file holds the reasons, the invariants a consumer is expected to keep, and what
was ruled out.

## Purpose

Answer four questions for any knob without reading code: what is it, where does its value come from
right now, how is it changed, and which recorded results did a given value produce.

The defects this ends, as found in a real service before it adopted the pattern: stacked default
layers nobody could see (code default, a compose `${VAR:-default}`, the host's env file), almost
every tunable living in env (so retuning a result-changing number was a hand edit outside version
control), runtime-mutable rows with no history, and graded rows carrying no config identity.

## The taxonomy: every knob is exactly one class

| class | what | its one home | change path | in the fingerprint |
|---|---|---|---|---|
| `secret` | credentials, tokens, DSNs with passwords | the host's secret store, read as `SecretStr` | placed by the operator's tooling, never committed | no (presence only) |
| `topology` | hosts, ports, paths, DSN shapes, plugin sets | env from the deployment; a code default for local dev only | a deploy change | no |
| `tunable` | a number or switch that changes behaviour or results | the CODE DEFAULT in its typed domain; a deploy may override by env, visibly | a code change | yes |
| `policy` | structured declarations (lanes, budgets, tiers, schedules) | a committed file or code registry, schema-validated | a code change | yes |
| `operational` | on/off, pause, budget dials the operator moves while the system runs | the consumer's append-only override store, over a typed default | runtime, with an audit row | yes |
| `sealed` | pre-registered gates and their pinned documents | the doc plus its sha constant | a revision: doc and constant in one commit | yes (doc sha) |

Not config: learned state (weights, calibrations), which is versioned model output with its own
ledger; and plain module constants (invariant 7).

## Shape

`knob(default, *, cls, doc, env, unit=, affects=, ge=, le=, on_unreadable=, not_secret=)` declares a
field. `Domain` is one config domain: frozen, `extra="forbid"` for committed files, case-sensitive
env, no prefix and no nested-delimiter magic. `load_all(domains, overrides=, on_boot=)` builds every
domain once, at the composition root. `effective(domain)` returns one `Effective` per knob (value,
`Source`, default, doc, unit, affects; secrets masked). `fingerprint(domain)` hashes the
TUNABLE/POLICY/OPERATIONAL/SEALED values. `schema()`, `catalog()` and `lint()` render the JSON
Schema, the knob catalog and the declaration findings, also as `python -m platform_kit.config`.

The consumer owns two tables, if it uses the runtime layer and row stamping: an append-only
dictionary from a fingerprint to the values it means, and an append-only override log whose newest
row per (domain, knob) wins. Their names are the consumer's.

## Invariants

1. **One precedence order everywhere:** code default < committed file (POLICY only) < env <
   runtime override (OPERATIONAL only) < constructor arguments. Every effective value reports its
   `Source`.
2. **Deployment files default topology only.** A tunable's default lives in code; a deployment
   template that defaults a tunable hides a third layer.
3. **A tunable set by env is a visible deviation.** The consumer's watchdog lists every TUNABLE
   whose source is `ENV`; the intended steady state is zero.
4. **Runtime overrides exist only for `operational` knobs.** A value that changes what a recorded
   result means must be reviewable and must move the fingerprint through a deploy, not a table.
5. **Every graded or learned row carries the fingerprint of the domains that shaped it.** NULL
   means written before stamping existed: unknown, never backfilled with a guess. The fingerprint
   dictionary resolves it to values.
6. **Every knob is declared** with `cls`, `doc` and `env`; `lint()` refuses a field without them,
   an env name declared twice, and a duplicate domain.
7. **A constant is code, not a knob.** It is promoted to a tunable only when someone needs to vary
   it per deploy or sweep it, one knob per change, with the constant as its default.
8. **Sealed stays sealed.** A sealed doc's sha is pinned by a constant AND stamped on the rows it
   governs, so an edit fails CI rather than only changing a stamp.
9. **Secrets never render.** Masking is by class, not by name pattern; a field NAMED like a
   credential but classed otherwise fails `lint()` unless it declares `not_secret="<why>"`.
10. **One knob, one domain.** A prefix split across domains, or an env name in two, is refused.
11. **The catalog is generated** from the declarations and drift-gated. It never holds a live
    value; the consumer's `effective()` endpoint does.

## Failure semantics

| situation | outcome |
|---|---|
| an invalid value from any source | boot fails; every error listed with domain, knob, env name and source |
| an unknown key in a committed file | boot fails (`extra="forbid"`) |
| an override for a non-operational knob, or an invalid one | ignored, `on_degraded("config_override_refused:...")` and a WARNING |
| the override store unreadable | defaults and env apply; `source` never claims `RUNTIME`; each OPERATIONAL knob uses its `on_unreadable` value (how a cost gate fails CLOSED) |
| schema or catalog drift | the CLI exits 1; 2 when it could not load the domains |

## Telemetry

| signal | where | what should watch it |
|---|---|---|
| `config_loaded` per domain (fingerprint + every value with its source, secrets masked) | the boot log | a daily diff of fingerprints names the knobs that moved |
| `effective()` | the consumer's config endpoint | a config-drift watchdog: any TUNABLE from `ENV`; any override with no expiry older than a stated age; any override by an unknown actor |
| rows with a NULL fingerprint written after stamping shipped | the consumer's graded tables | an unstamped-rows watchdog (a writer forgot the stamp) |

## Acceptance tests (`tests/config/`)

1. Precedence: default, file, env and runtime each win in order; `Effective.source` says which.
2. Must-fire both ways on runtime scope: an override for a TUNABLE is ignored and reported; the same
   override for an OPERATIONAL knob applies.
3. `fingerprint` changes with a TUNABLE and does NOT change with a TOPOLOGY or SECRET value.
4. A SECRET's value never appears in `effective()`, the boot line, the schema or the catalog (a
   planted canary value is grepped for).
5. `lint()`: a field without `cls`/`doc` fails; a duplicate env name fails; a secret-looking name
   classed TUNABLE fails; a clean set passes.
6. Catalog and schema drift fail on an un-regenerated change.

## Ruled out

| option | why |
|---|---|
| Hydra / OmegaConf | a second type system and an interpolation language beside pydantic |
| dynaconf | layered but untyped at the edge; validators are a parallel schema |
| OpenFeature and a flag service | built for per-user targeting and vendor backends; its one idea is kept (an evaluation returns its reason, here `Source`) |
| everything in env (strict 12-factor) | right for secrets and topology; for tunables it puts behaviour outside version control |
| a config language (templating, includes) | grows its own migration framework |
| runtime-tunable result-changing knobs | grades would mix configs between deploys with no review |
| `CliSettingsSource` for services | services are not CLIs |
