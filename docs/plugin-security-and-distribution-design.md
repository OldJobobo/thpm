# Plugin security and distribution design

Status: research and architecture proposal

## Executive recommendation

THPM should not treat “security check” as a malware scanner or a boolean claim that a plugin is safe. It should build a layered admission pipeline and report what is known:

1. validate the package and manifest;
2. verify integrity and, when available, publisher identity;
3. derive and enforce a capability policy;
4. show the exact install/apply/remove plan;
5. install atomically into a managed store;
6. keep an ownership ledger so removal is reversible;
7. execute only through constrained THPM operations.

The most important product decision is to make the first external plugin format **declarative and data-only**. It may contain templates and assets, but it may not contain arbitrary Python or shell entry points. THPM should broker file writes, managed blocks, reloads, and other supported actions. Arbitrary executable plugins create a much larger sandboxing and review problem and should be a separate, explicitly unsafe tier if they are ever supported.

Build one service-layer workflow first, then expose it through the CLI, QML panel, and Textual TUI. Do not implement three independent installers.

## What THPM has today

THPM already has the right high-level frontend boundary:

- the CLI calls `Service` directly (`src/thpm/cli.py`);
- the Textual TUI calls the same `Service` in workers (`src/thpm/tui.py`);
- the QML panel invokes CLI JSON operations (`assets/qml/Panel.qml.in`).

There is also useful security groundwork:

- state mutations are locked and atomically replaced (`src/thpm/state.py`);
- managed files are generally written atomically (`src/thpm/files.py`);
- subprocesses use argument arrays rather than `shell=True` (`src/thpm/integrations.py`);
- hook failures are isolated per integration (`apply_enabled`);
- THPM self-updates verify SHA-256, reject archive links/path traversal, stage a runtime, and roll back integration surfaces (`src/thpm/update.py`).

However, today’s “plugins” are compiled-in records plus ID-specific Python branches:

- metadata is a static tuple in `src/thpm/registry.py`;
- behavior is a large `apply(plugin_id, paths)` branch in `src/thpm/integrations.py`;
- templates can only come from packaged THPM assets (`src/thpm/templates.py`);
- state loading only recognizes IDs present in the static registry (`src/thpm/state.py`).

Consequently, the project currently supports **enable/disable of built-in integrations**, not installation/removal of plugin packages.

## Current security and lifecycle gaps

### 1. Confirmation metadata is not enforced

`Plugin.confirmation` is exposed as `confirmationRequired`, but `Service.set_enabled()` does not check it and neither frontend presents a plugin-specific confirmation. Firefox, Zen, and Steam therefore have security-sensitive metadata that is currently informational only.

Enforcement belongs in `Service`, not only in UI code. A caller of `--json` must not bypass policy.

### 2. Availability is enforced by the frontends, not the service

The GUI and TUI disable unavailable rows, but `Service.set_enabled()` accepts an unavailable built-in plugin. Policy must be identical for every caller.

### 3. Disable is not remove or cleanup

Disabling reconciles packaged templates, but it does not generally remove already-applied outputs, managed imports, selected themes, or other integration artifacts. This is acceptable for a toggle-only built-in registry, but it is insufficient for a package manager.

A real remove operation needs a per-plugin ownership ledger, cleanup behavior, modification detection, and rollback.

### 4. Existing inputs are already more powerful than “theme data”

Several theme-provided files can become executable or active application configuration:

- generated Fish and Qutebrowser files are code-like inputs;
- browser CSS and Vencord CSS may load remote resources;
- Zellij KDL and editor JSON affect application behavior;
- Steam invokes an existing user-local `install.py`.

External plugin packages therefore expand an existing trust boundary; they do not create the first one. Security reporting should inspect both package contents and declared destinations/actions.

### 5. Checksums are integrity, not publisher authentication

The self-updater’s release checksum catches corruption and accidental mismatch. If an archive and its checksum are controlled through the same compromised account/channel, the checksum alone does not establish publisher identity. External plugin support should record digests immediately and add signature/attestation verification as a separate trust signal.

### 6. The current safe extractor is a useful base, not a complete package extractor

`update._safe_extract()` rejects links and traversal. A reusable plugin extractor should additionally reject devices/FIFOs, absolute and ambiguous paths, duplicate normalized names, case-colliding names, oversized files, excessive file counts, excessive expanded size, setuid/setgid bits, and unsupported archive formats.

## Terminology

Use distinct verbs consistently across all surfaces:

- **add**: acquire, check, and register a plugin package;
- **remove**: disable, clean up owned effects, and unregister its package;
- **enable**: opt an installed plugin into theme-hook execution;
- **disable**: stop future execution without claiming all effects were removed;
- **apply**: execute the enabled plugin for the active theme;
- **check**: inspect a source/package without installing it;
- **verify**: re-check installed bytes, provenance, and policy.

Reserve `install`/`uninstall` without `plugin` for THPM itself to avoid the current ambiguity.

## Threat model

The admission design should address at least:

- archive traversal, links, special files, decompression bombs, and parser abuse;
- a malicious manifest requesting broad filesystem writes or command execution;
- command injection through interpolated arguments;
- replacing another plugin’s files or THPM-owned files;
- plugin ID/source squatting;
- mutable Git branches/tags changing after approval;
- repository or publisher account compromise;
- update-time permission escalation;
- TOCTOU between review and install;
- cleanup deleting user-modified or foreign files;
- a plugin blocking the theme-set hook indefinitely;
- accidental network access or secret exposure during plugin execution.

Out of scope for an initial release: proving arbitrary native or shell code safe. Static scanning cannot provide that guarantee.

## Proposed package format

Use a directory or a `.thpm` tar archive with one root directory and a required `thpm-plugin.toml`.

A first schema could look like:

```toml
schema_version = 1

[plugin]
id = "io.example.superfile"
name = "Superfile Theme"
version = "1.2.0"
description = "Installs a semantic Superfile theme"
license = "MIT"
api = ">=1,<2"
default_enabled = false

[compatibility]
thpm = ">=1.1"
omarchy = ">=4,<5"

[[inputs]]
name = "fallback"
kind = "template"
path = "templates/superfile.toml.tpl"

[[operations]]
kind = "render-copy"
input = "fallback"
target = "superfile.theme"

[[operations]]
kind = "reload"
action = "superfile"
```

Important constraints:

- external plugins default to disabled;
- unknown keys are rejected in schema v1, avoiding silent policy bypasses;
- IDs use a stable reverse-domain namespace;
- paths are relative, normalized, and contained in the package;
- destinations are logical THPM target IDs, not arbitrary `$HOME` paths;
- reload/action IDs map to reviewed THPM implementations;
- no `shell`, Python module, executable entry point, or free-form command exists in v1;
- conflicts and replacement relationships are manifest data, not hard-coded pairs;
- manifest permissions are derived from operations and displayed to users.

THPM should own a target registry such as `superfile.theme`, `fish.conf.d`, or `firefox.userChromeImport`. Each target defines allowed roots, write strategy, cleanup strategy, and whether explicit confirmation is required. This prevents a plugin author from requesting `~/.ssh/config` merely by spelling that path in TOML.

## Trust tiers

Present trust as evidence, not as a single score:

1. **Bundled** — ships with THPM and is covered by THPM’s release process.
2. **Verified publisher** — artifact digest plus a valid signature/attestation for an approved identity.
3. **Pinned remote** — fetched from a remote repository and pinned to an immutable commit/digest, but not cryptographically tied to a trusted publisher.
4. **Local** — loaded from a user-selected local file/directory; digest recorded, publisher unverified.
5. **Modified** — installed bytes no longer match the recorded digest.
6. **Blocked** — malformed package, forbidden capability, unsafe archive, incompatible API, or failed required verification.

Avoid labels such as “safe”. A useful result says, for example: “Package is structurally valid, requests two config-file writes and one app reload, contains no executable entry point, and has an unverified local publisher.”

## Admission and security-check pipeline

Implement a source-independent pipeline:

```text
SourceRef
  -> resolver
  -> immutable staged artifact
  -> safe extractor
  -> manifest/schema validator
  -> content inspector
  -> capability/policy evaluator
  -> trust verifier
  -> InstallPlan(digest, risks, permissions, conflicts, file effects)
  -> user approval bound to digest
  -> atomic store activation
```

### Structural checks

- strict TOML schema and supported schema/API versions;
- valid namespaced ID and normalized version;
- package ID/version matches requested catalog coordinates;
- all referenced files exist and all unreferenced executable-like files are reported;
- MIME/type and extension checks for expected assets;
- UTF-8/text size checks where applicable;
- syntax checks where reliable (`ast.parse` for Python-like data, format-specific parsers, `bash -n` only as syntax—not safety);
- package and expanded-size quotas;
- no symlinks, hardlinks, devices, FIFOs, sockets, absolute paths, `..`, or path collisions.

### Policy checks

- derive capabilities from operations rather than trusting a hand-written permission list;
- reject undeclared destinations and free-form process execution;
- identify code-like outputs and remote imports as elevated risk;
- detect collisions with another installed plugin’s targets;
- require extra confirmation for shared-file edits, browser chrome, executable outputs, signals, and external processes;
- require renewed approval when an update adds capabilities or broadens destinations.

Heuristic secret/malware scans can be supplemental warnings, but they must not be the security boundary. A clean scan is not proof of safety.

### Review and TOCTOU protection

`plugin check` should return an `InstallPlan` containing the artifact SHA-256. Approval must refer to that digest. The installer must re-hash the staged artifact immediately before activation and reject a mismatch.

For JSON clients, return a plan token bound to the digest and policy version. QML/TUI can show the plan and submit the token. The service still validates it. Do not implement confirmation only as a frontend modal.

## Installation store and ownership

Suggested layout:

```text
$XDG_DATA_HOME/thpm/plugins/<plugin-id>/<digest>/
  thpm-plugin.toml
  payload/...
  install.json

$XDG_STATE_HOME/thpm/plugins.toml
$XDG_STATE_HOME/thpm/ownership/<plugin-id>.json
$XDG_CACHE_HOME/thpm/downloads/<digest>
$XDG_CONFIG_HOME/thpm/trust.toml
```

`plugins.toml` should be an inventory, not only a map of booleans. Record ID, version, enabled state, source kind, original locator, resolved revision, digest, trust evidence, accepted capability set, install time, and schema version.

The ownership ledger should record every effect:

- target path or logical target;
- operation type (`create`, `replace`, `managed-block`, `selection-change`);
- pre-image hash/backup where appropriate;
- installed post-image hash;
- cleanup handler and plugin digest.

On remove:

1. disable the plugin;
2. build and display a removal plan;
3. remove a created file only if its current hash matches the installed hash;
4. remove only THPM’s delimited block from shared files;
5. restore a backup only when doing so will not overwrite newer user changes;
6. retain modified artifacts and report them instead of deleting them;
7. remove package inventory/store data only after cleanup commits successfully.

Use the existing mutation lock and atomic-write helpers, but add a transaction/journal because package installation spans multiple files.

## Source resolvers

Define a small resolver protocol now even if only local sources ship initially:

```python
class PluginSource(Protocol):
    def resolve(self, ref: SourceRef, staging: Path) -> ResolvedArtifact: ...
```

`ResolvedArtifact` should contain staged path, source kind, canonical locator, requested revision, resolved immutable revision, digest, and available provenance evidence. Everything after resolution is shared.

### Local file or directory — first

Support:

- `thpm plugin check ./plugin.thpm`
- `thpm plugin add ./plugin.thpm`
- optionally `--dev ./plugin-directory` for an explicitly mutable development link.

Normal local installs copy bytes into the managed store and pin their digest. They must not execute from the original path. Development links should be visibly marked unverified/mutable and should not be marketplace-eligible.

### GitHub-like repository — second

Accept a generic Git URL syntax rather than baking all behavior into GitHub:

```text
https://github.com/owner/repo.git#<tag-or-commit>
```

Recommended behavior:

- allow HTTPS by default; reject local/file/SSH transports unless explicitly requested;
- resolve a tag/branch to a commit and record the commit hash;
- fetch into a private staging directory with no Git hooks and no submodules by default;
- never run repository build/install scripts;
- package only the declared plugin root;
- prefer signed release artifacts for normal users and reserve repository snapshots for development;
- show mutable branch/tag input as pinned to the resolved commit;
- on update, compare manifests, capabilities, and publisher evidence before approval.

GitHub-generated source archives are convenient discovery inputs but are weaker release artifacts than publisher-built, checksummed/signed `.thpm` bundles. The latter should be the preferred path.

### Marketplace — later

A marketplace should initially be a signed metadata/catalog service, not a second package format and not a server that causes THPM to execute arbitrary code. Catalog entries should point to the same immutable `.thpm` artifact accepted by local and repository flows.

Use a TUF-style metadata model when the marketplace becomes real: root trust, delegated publisher roles, timestamp/snapshot/targets metadata, expiry, rollback protection, and artifact hashes. Sigstore-compatible keyless signatures or GitHub artifact attestations can provide publisher/build identity evidence, but marketplace policy still decides which identities are accepted.

Do not design ranking, reviews, payment, or recommendation systems into the core installer. The installer needs only a `MarketplaceSource` resolver returning the same `ResolvedArtifact`.

## Execution model

### Recommended v1: brokered declarative operations

External plugins describe desired effects. THPM performs them through reviewed operations:

- render a template using the semantic palette;
- copy an asset to an allowlisted logical destination;
- insert/remove a managed block;
- select a named theme through a fixed argument-vector command;
- reload a known application through a fixed action;
- emit diagnostics.

This aligns with THPM’s existing integration patterns while moving ID-specific behavior into reusable handlers.

### If executable plugins are later required

Treat them as a separate trust and UX tier. A reasonable design is:

- run a plugin worker with an empty/minimal environment;
- no inherited secrets, SSH agent, session bus, or broad `$HOME`;
- read-only plugin package and palette input;
- no network by default;
- strict timeout/output/resource limits;
- worker emits a declarative change set;
- THPM validates and applies that change set through the broker;
- app reloads remain broker actions.

Bubblewrap/systemd sandboxing can reduce exposure on Linux, but it does not make arbitrary code safe and can be difficult when plugins need desktop-session access. Marketplace eligibility should remain data-only until there is a mature review and containment story.

## One backend, three user surfaces

Add canonical service operations first:

- `plugin_sources()` / supported source kinds;
- `plugin_check(source)` -> install plan;
- `plugin_add(plan_token)`;
- `plugin_remove_plan(id)`;
- `plugin_remove(plan_token)`;
- `plugin_inspect(id)`;
- `plugin_verify(id | all)`;
- existing `set_enabled(id, value)`, hardened with availability, confirmation, trust, and compatibility policy.

Use the same JSON envelope everywhere and bump its schema version when fields become incompatible.

### CLI

Proposed commands:

```text
thpm plugin list [--installed|--available]
thpm plugin check SOURCE
thpm plugin add SOURCE
thpm plugin inspect ID
thpm plugin enable ID
thpm plugin disable ID
thpm plugin remove ID
thpm plugin verify [ID]
thpm plugin update [ID]
```

Human mode can prompt. JSON mode should never wait for stdin: return `confirmationRequired`, an exact plan, and a plan token; require an explicit follow-up/accept flag. This makes automation deterministic.

Keep the existing top-level `enable`/`disable` aliases for compatibility, but document `plugin ...` as canonical.

### Textual TUI

Add an Installed/Discover distinction rather than overloading the current toggle list. The first iteration only needs:

- Add button opening a local path/source input;
- review modal showing identity, source, digest/trust, capabilities, warnings, conflicts, and file effects;
- Remove action on an installed plugin detail screen;
- progress and final changed/retained-file summary;
- confirmation when enabling elevated capabilities.

All work remains in background workers and calls `Service`.

### QML panel

Use the same staged flow through `thpm --json`. QML already passes argv arrays, which avoids shell interpolation. Add dedicated `Process` objects for check/add/remove and parse their result instead of discarding mutation output.

The current `mutate` process refreshes state without surfacing the command response. Before package operations, make mutation results visible so policy errors, confirmation requirements, and cleanup warnings are not lost.

A native file picker can come later; a source text field plus paste/drop support is enough for the first release. Never construct a command string from the source—continue passing each argument as a separate QML process argument.

## Suggested internal architecture

A small set of focused modules avoids expanding `registry.py` and `integrations.py` into more ID branches:

```text
src/thpm/plugins/
  manifest.py       strict schema and model
  catalog.py        built-in + installed plugin views
  sources.py        SourceRef and resolver protocol
  source_local.py
  source_git.py     later
  package.py        hashing and safe extraction
  security.py       inspection, trust evidence, policy decisions
  plans.py          install/remove plans and token binding
  store.py          inventory, content store, ownership ledger
  operations.py     brokered operation registry
  lifecycle.py      add/remove/enable/disable/apply transactions
```

Keep `Service` as orchestration and response-envelope code. Keep frontend-specific behavior outside these modules.

Built-ins can migrate incrementally: wrap the current records in a `BuiltInCatalog`, retain existing `apply()` handlers, then move common patterns into declarative operations one plugin at a time. External plugins should only reference operations already judged safe for external use.

## Delivery sequence

### Phase 0 — close present policy gaps

- enforce `confirmationRequired` in `Service`;
- enforce availability/compatibility in `Service`;
- make QML display mutation failures;
- define add/remove/enable/disable terminology;
- document current theme-asset trust assumptions.

### Phase 1 — package core and local source

- strict manifest models and package fixtures;
- safe extraction with quotas and special-file rejection;
- local file/directory resolver;
- content-addressed store and inventory;
- install/remove plans bound to digest;
- ownership ledger and safe cleanup;
- data-only operations;
- CLI `check`, `add`, `inspect`, `remove`, and `verify`.

Do not add Git/network behavior before local lifecycle and cleanup are reliable.

### Phase 2 — all frontend support

- TUI add/review/remove flows;
- QML add/review/remove flows;
- contract tests asserting all surfaces call the same service operations and represent warnings consistently;
- interruption/lock/error UX.

### Phase 3 — Git repository resolver

- HTTPS-only default, immutable commit resolution, no hooks/submodules/scripts;
- source metadata and update comparison;
- release-artifact preference;
- network limits and clear offline/error behavior.

### Phase 4 — provenance and hardening

- publisher trust store;
- signature/attestation verification;
- permission-delta approvals on update;
- optional static analyzers as warning providers;
- audit log and `doctor`/`verify` integration.

### Phase 5 — marketplace

- signed catalog metadata with expiry and rollback protection;
- publisher identity/delegation policy;
- moderation/revocation process;
- same package, resolver, plan, store, and lifecycle APIs as local/Git sources.

## Minimum test matrix

Security tests:

- traversal, absolute path, symlink, hardlink, device, FIFO, duplicate/case-collision, and archive-bomb rejection;
- malformed/unknown manifest keys and incompatible API versions;
- undeclared files and forbidden target/action rejection;
- digest change between plan and commit;
- modified tag resolving to a new commit;
- signature valid, invalid, unknown identity, expired/revoked policy;
- permission escalation on update;
- timeout and oversized worker output if executable workers ever exist.

Lifecycle tests:

- add is atomic and disabled by default;
- interrupted add leaves no active inventory entry;
- disable stops future runs;
- remove only deletes matching owned files/blocks;
- modified user files are retained and reported;
- conflicts are handled through manifest policy;
- state migration preserves current built-ins;
- rollback restores inventory and effects.

Surface tests:

- CLI human and JSON two-step confirmation;
- TUI review/confirm/cancel/error paths;
- QML command arrays and parsed mutation errors;
- identical service result semantics across all three surfaces.

## Decisions to make before implementation

1. Are marketplace-eligible plugins permanently data-only, or merely data-only for v1?
2. Which current integration patterns become public broker operations?
3. Which logical destinations are safe for third-party plugins?
4. Should local development directories be copied snapshots by default, with `--dev` as the only mutable link mode? Recommended: yes.
5. What identity policy will qualify a publisher as verified?
6. How long should cleanup backups and audit records be retained?

## Reference models

- The Update Framework: signed metadata, delegation, expiry, rollback/freeze protection — <https://theupdateframework.io/>
- Sigstore documentation: artifact signing and identity-based verification — <https://docs.sigstore.dev/>
- GitHub artifact attestations: build provenance tied to repository/workflow identity — <https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations>
- SLSA provenance model — <https://slsa.dev/spec/>
- Python archive extraction filters and warnings — <https://docs.python.org/3/library/tarfile.html#extraction-filters>
- OpenSSF Scorecard: useful repository risk signals, not a substitute for package policy — <https://securityscorecards.dev/>

These systems support the same core conclusion: immutable digests, authenticated metadata, least privilege, explicit policy, and safe updates are stronger controls than a one-time source-code scan.
