# pack-contracts

The contracts a **pack** is written against, and nothing that runs one. A pack is an installed
distribution that contributes to a host application through two entry points of the same name: a
manifest file, which the host reads before importing anything, and a pluggy plugin. A pack depends
on this distribution only, never on the host's loader, so the loader can change without a pack
noticing (the rule Backstage keeps with its `*-node` extension-point packages).

Standard library, pydantic and pluggy; nothing else.

| module | what it holds |
|---|---|
| `contract` | `CONTRACT_VERSION` (one `MAJOR.MINOR` for the hooks and the manifest), `satisfies()`, the versioning rule |
| `manifest` | `PackManifest` (pydantic v2, `extra="forbid"`, frozen) and `Tier` |
| `discovery` | `MANIFEST_GROUP`, `read_manifests()` / `read_manifest()` (no pack code imported), `ManifestError` |
| `hooks` | `PROJECT_NAME`, `PLUGIN_GROUP`, the `hookspec` / `hookimpl` markers, `PackSpec`, the `Contribution` protocol |
| `surface` | the contract surface as data, and `verify_ledger()` over the committed `surface-ledger.json` |
| `schema` | the JSON Schema (2020-12) projection of `PackManifest`, committed as `pack-manifest.schema.json` |

## Writing a pack

```toml
# pyproject.toml of the pack's distribution
[project]
name = "example-pack"
version = "1.0.0"
dependencies = ["pack-contracts"]   # pin it by tag, see "Using a package" in the workspace README

[project.entry-points."pack_contracts.manifest"]
example = "example_pack:pack.toml"  # <package>:<file in that package's directory>

[project.entry-points."pack_contracts.plugin"]
example = "example_pack.plugin"     # the same name: the module that holds the hookimpls
```

```toml
# example_pack/pack.toml
id = "example"          # equals the entry-point name
version = "1.0.0"       # equals the distribution's version
contract = "1.0"        # the contract MAJOR.MINOR the pack is written against
tier = "loads"          # declared < loads < conformant: what the pack claims

[provides]              # every key it registers, as kind -> names, and nothing else
greeting = ["hello", "goodbye"]

[needs]                 # keys the host or another pack must provide
clock = ["utc"]
```

```python
# example_pack/plugin.py
from dataclasses import dataclass
from pack_contracts import hookimpl


@dataclass(frozen=True)
class Greeting:
    kind: str
    name: str


@hookimpl
def register_contributions(register):
    register(Greeting("greeting", "hello"))
    register(Greeting("greeting", "goodbye"))
```

`python -m pack_contracts validate example_pack/pack.toml` checks a manifest in the pack's own CI
(exit 1 on a refusal). The suite's synthetic pack, `tests/example_pack/`, is this example.

## Reading manifests without importing a pack

`read_manifests()` walks the `pack_contracts.manifest` entry points, sorted by name. For each it
locates the package directory with `importlib.util.find_spec` (the top-level name) and
`importlib.machinery.PathFinder` (each level below), which find a package without executing it,
then reads and validates the file. A pack whose import would fail can still be listed or refused.

Every failure is a `ManifestError(pack, stage)`, a subclass of `ImportError`; there is no "skip the
bad one". The stages, in check order: `duplicate`, `locate`, `read` (a JSON object that repeats
a key is refused here, as TOML refuses one), `contract` (another major, or a newer minor than this
host speaks; checked on the parsed data BEFORE validation, so a pack written for a newer minor that
uses a field this host does not know is told to upgrade the host, not to fix a typo), `validate`,
`identity` (the id is not the entry-point name, or the version is not the distribution's).

**Telemetry.** `read_manifests` logs `pack_manifests_read` at INFO and returns `Manifests`, whose
`series()` renders `pack_manifest{group,pack,version,contract,tier,origin} = 1` per pack for the
host's exporter. A refusal raises at boot, so the supervisor's restart count is the signal. A pack
that is simply absent raises nothing; the host's watchdog compares the series with the allow-list
in its deploy config.

## Versioning: the rule and its ledger

The contract version is independent of the distribution version. Inside one major, a version may
only **add**: a hook, a **defaulted** parameter on a hook (pluggy 1.7 fills a hookspec's defaults
when the caller omits them, and passes an implementation only the parameters it names), a protocol,
or an **optional** manifest property. Everything already there stays exactly as it was. Anything
else is a new major: a renamed project name or entry-point group, a removed or renamed hook or
parameter, a new required parameter, a changed annotation or default, a changed `firstresult` /
`historic`, a member added to or changed on a protocol, and any change to an existing manifest
property (its type, pattern, bounds, enum or default) or to the required set.

`src/pack_contracts/surface-ledger.json` is append-only, one entry per contract version. An entry
is the whole surface: the three names, each hook's parameters with their annotations and defaults,
each protocol's members, the manifest's JSON Schema without its prose (`description`, `title`),
and the model's validators by name and target fields (a validator's body is not compared: a body
change that refuses what used to pass is a new major by the rule, held in review).
`tests/test_surface.py` holds it two ways:

- `verify_ledger()`: consecutive entries inside a major must be compatible, and the last entry must
  be `CONTRACT_VERSION` and equal the live surface. So a surface change fails the suite until it is
  entered as a new version (`python -m pack_contracts surface` prints the entry), and an
  incompatible one fails unless that version is a new major.
- `append_only_errors()` over git: the ledger at every `pack-contracts-v*` tag and on `base` must
  be a prefix of the committed one, so an entry edited in place (live surface and entry changed
  together) fails too. CI's pytest job checks out full history and sets
  `PACK_CONTRACTS_LEDGER_HISTORY_REQUIRED=1`, which turns "no history here, skip" (or a missing
  `origin/base`) into a failure. Only refs that are ancestors of HEAD are compared, so a release
  tagged on an older commit is not mistaken for a removal.

Because the manifest entry is pydantic's JSON Schema projection, a pydantic upgrade that writes an
existing property differently fails `verify_ledger` although no contract changed. The response is
to read the diff: if the meaning is the same (a keyword spelled differently), the projection is
pinned back (a `json_schema_extra` on the field) rather than a contract version entered for a
change nothing made.

`src/pack_contracts/pack-manifest.schema.json` is generated from `PackManifest`
(`python -m pack_contracts schema`) and `tests/test_schema.py` fails when they differ. The schema
holds the shapes a schema can express (unknown keys, slugs, non-empty name lists without repeats);
cross-field rules, such as a pack needing what it provides itself, are the model's alone.

## Where it came from

- **napari npe2 0.10.2** `PluginManifest`: a manifest behind its own entry-point group
  (`napari.manifest`), read before the plugin is imported; `schema_version` as the contract the
  plugin targets; the manifest name must match the package. Not used as-is: npe2's
  `discover()` resolves `<pkg>.<sub>` with `importlib.util.find_spec`, which imports the parent
  packages; a manifest that fails validation is logged and yielded as an error result; a newer
  schema only warns; unknown keys are ignored; and the model carries napari's own contribution
  points.
- **Home Assistant** `manifest.json` (hassfest): a slug `domain` as the id, `dependencies` as
  needs, and `quality_scale` as a cumulative tier. `needs` here names capabilities, not other
  packs, so packs stay independent of each other.
- **Apache Airflow** `provider_info`: one list per contribution kind, and `lifecycle` as a declared
  maturity. The kinds here are open slugs: these contracts know no domain.
- **stevedore 5.10**: not used. It reads entry points by loading them (importing the target), has
  no manifest, and logs and continues on a failed load.
- **pluggy 1.7** is the transport and supplies the markers. It has no manifest and no notion of a
  contract version; its `load_setuptools_entrypoints` imports every plugin to discover it.

## The C2 seam: what plugs into this

The host side is platform-kit's strict loader (`platform_kit.plugins`, R1-R10), and the loader
that wires it to these contracts is `platform_kit.packs` (platform-kit 0.2.0, extra `[packs]`;
its design record is `packages/platform-kit/docs/packs.md`). These contracts were shaped for it:

- `read_manifests()` runs FIRST; the allow-list pin (`*_LOAD_PACKS`) filters `Manifests.packs`,
  and only then does `plugins.load(pm, group=PLUGIN_GROUP, hookspecs=PackSpec, pin=...)` import
  code, with `pm = pluggy.PluginManager(PROJECT_NAME)`. A manifest entry point without a plugin
  entry point of the same name, or the reverse, is a load failure.
- The merge step refuses a key two packs `provide` (from the manifests alone, before any import),
  and a `needs` key nobody provides.
- `plugins.collect(pm, "register_contributions", store, kind=Contribution)` with
  `store.key_of = contribution_key`; then the registered keys must equal the pack's
  `PackManifest.provided()` exactly (that is what tier `loads` claims).
- `collect` calls `impl.function(register=...)` directly, not through pluggy's `HookCaller`, so
  pluggy's hookspec defaults are not applied there. When a minor version adds a defaulted
  parameter, `collect` must pass the spec's defaults (`HookSpec.kwargdefaults`) or call the hook
  through `pm.hook`.
- `list-packs` (`python -m platform_kit.packs list`) prints every installed pack's state, with its
  manifest version and origin, including the packs the pin excluded and the ones that failed.
