# THPM Product Requirements Document

Status: Approved

Approved: 2026-08-01 through maintainer product-decision review

Last updated: 2026-08-01

Target baseline: THPM 1.0 and post-1.0 planning

## 1. Executive summary

THPM is the theme integration manager for applications that Omarchy 4 does not
theme natively. It preserves user intent, installs one Omarchy theme hook,
coordinates authored assets and semantic-palette fallbacks, and applies enabled
integrations after theme changes. Its service is the shared policy boundary for
the CLI, graphical panel, and terminal UI; complete outcome parity across those
surfaces is a target that is not yet fully implemented.

THPM is not a replacement theme engine. Omarchy remains the authority for the
active theme, semantic `colors.toml` palette, template rendering, and native
application integrations. THPM begins where that native ownership ends.

The product's intended primary differentiator is not the number of applications.
It is trustworthy lifecycle management:

- clear ownership boundaries;
- explicit enabled intent;
- authored-asset precedence with generated fallbacks where appropriate;
- idempotent application and honest outcomes;
- guarded restoration on disable, retirement, and uninstall;
- isolation of integration application failures;
- one policy and service contract across every frontend.

The implementation has strong groundwork for these guarantees but does not yet
meet all of them consistently. The first priority is to close those gaps for
built-in integrations and ship a stable 1.0. External plugin packages and a
marketplace are post-1.0 initiatives and must not weaken the ownership or safety
model.

### 1.1 How to read this document

This is a proposed target-state PRD, not a statement that every `shall` requirement
is already shipped. Sections 1 through 9 define product intent and scope. Section
10 and later define normative target requirements, recommended decisions, release
gates, and roadmap. Section 10 begins with an explicit current-state gap register.

Where this document says an integration is active, it means the integration is
present in the current registry. It does not mean end-to-end support certification
has been completed. Support status is not yet encoded in registry metadata.

## 2. Product vision

An Omarchy user should be able to switch themes once and have every supported
non-native application follow that theme without maintaining per-application
scripts, losing personal configuration, or guessing whether an integration
succeeded.

Theme authors should be able to provide richer application-specific assets while
ordinary themes remain useful through semantic palette generation. Maintainers
should be able to add, deprecate, and retire integrations through a documented
lifecycle instead of accumulating unsupported adapters indefinitely.

## 3. Problem statement

Omarchy owns a coherent core theme pipeline, but optional applications have
different configuration formats, reload behavior, profile layouts, and ownership
risks. Ad hoc theme hooks commonly create the following problems:

- each application has an independent script and state model;
- theme switching can block or fail halfway through;
- generated files can be mistaken for user-owned files;
- disabling a hook does not restore displaced settings;
- graphical and terminal controls can disagree;
- missing applications create recurring errors;
- application or package changes leave integrations stale;
- users cannot tell whether a warning means unavailable, unchanged, or failed.

THPM solves this by brokering a bounded set of integration effects through one
state model, one service layer, one hook, and explicit ownership records.

## 4. Target users

### 4.1 Primary users

- Omarchy 4 users who want optional applications to follow the active theme.
- Users who need CLI automation as well as graphical and terminal interfaces.
- Users migrating from earlier theme-hook implementations.
- Theme authors who provide optional authored assets such as CSS, JSON, or KDL.
- THPM maintainers adding and retiring built-in integrations.

### 4.2 Future users

- Authors of declarative third-party THPM packages.
- Reviewers and catalog maintainers evaluating package provenance and effects.

Future users do not expand the 1.0 scope. The current product supports built-in
integrations, not installable third-party plugin packages.

## 5. Jobs to be done

### JTBD-1: Keep applications synchronized

When I change my Omarchy theme, I want enabled non-native applications to receive
the appropriate authored or generated theme so the desktop remains coherent.

### JTBD-2: Preserve my configuration

When THPM takes over or relinquishes a target, I want my prior file, symlink,
mode, or selection restored when safe, and I never want THPM to delete a file it
cannot prove it owns.

### JTBD-3: Understand the result

When a theme is applied, I want to know which integrations were applied,
unchanged, skipped, or failed, what changed, and what action I must take next.

### JTBD-4: Control integration intent

When I enable or disable an integration, I want that intent to persist across
themes and frontends without being inferred from generated output.

### JTBD-5: Diagnose coverage

When an application is not themed, I want Doctor and the integration view to
distinguish missing prerequisites, non-applicability, invalid theme output,
pending restart, and actual adapter failure.

### JTBD-6: Install and update safely

When I install or update THPM, I want package-manager ownership respected, source
updates verified and rollbackable, and user-level hooks and UI synchronized
without root-owned desktop files.

### JTBD-7: Develop and validate integrations

When a maintainer changes an adapter, I want automated lifecycle tests and an
isolated live-test path that exercise the same code shipped in the package.

## 6. Product principles

### 6.1 Omarchy remains authoritative

THPM must consume the active Omarchy 4 theme and the palette resolved by
`omarchy-theme-color`. It must not maintain a competing palette derivation system
or take ownership of Omarchy-native outputs.

### 6.2 State is intent

Enabled state is explicit user intent. It must not be inferred from target files,
rendered templates, application installation, or the current theme.

### 6.3 Preserve before replacing

Every writable effect must declare its ownership and cleanup behavior. Unknown,
modified, malformed, or unverifiable targets must be preserved and reported.

### 6.4 Prefer authored assets, then semantic fallbacks

An explicit asset from the active theme has priority. A generated fallback may be
used only when the integration defines a complete semantic mapping and validates
the rendered output before deployment.

### 6.5 One service, multiple surfaces

CLI, JSON, QML, and TUI are presentations of the same service operations and
policy. Frontends must not implement independent readiness, confirmation,
ownership, or mutation rules.

### 6.6 Honest partial failure

THPM must distinguish state commitment, file changes, application reload, and
post-commit refresh. It must never report a full success merely because part of
an operation completed.

### 6.7 Support means observable effect

Writing a plausible file is not sufficient for claiming support. An active
integration must have a verified loader, import, selector, command, or application
path that causes the target application to use the installed theme.

### 6.8 Retire unsupported integrations deliberately

An integration whose application contract no longer exists must leave the active
registry. Guarded cleanup knowledge must remain indefinitely unless retaining it
becomes unsafe.

## 7. Scope

### 7.1 1.0 scope

- The current stable Omarchy release at the time of each THPM release.
- Built-in integration registry and native ownership records.
- Persistent enable/disable state.
- Omarchy template reconciliation and one `theme-set` hook.
- Authored assets and generated semantic fallbacks.
- Guarded file, symlink, mode, and managed-block lifecycle, plus explicit
  classification of selection and other external effects.
- CLI, schema-versioned JSON, QML panel, and Textual TUI.
- Doctor, reconciliation, installation, migration, update, and uninstall flows.
- Stable AUR, VCS AUR, source runtime, and local Arch package workflows.
- Explicit deprecation and retirement process for built-in integrations.

### 7.2 Post-1.0 scope

- Declarative data-only external plugin packages.
- Local package inspection and installation.
- Content-addressed package storage and effect inventory.
- Digest-bound install and removal plans.
- Immutable Git resolution.
- Publisher signatures or attestations.
- A signed metadata catalog after local and Git lifecycle reliability.

## 8. Non-goals

- Supporting Omarchy versions before 4.0.
- Replacing Omarchy theme selection, palette resolution, or template rendering.
- Managing applications Omarchy already themes natively without a verified gap.
- Supporting arbitrary shell, Python, native, or extension code in external plugin
  package version 1.
- Allowing external plugins to declare arbitrary paths under `$HOME`.
- Claiming that checksums prove publisher identity.
- Guaranteeing live reload for applications that do not support it.
- Removing application packages when an integration is disabled.
- Deleting user-modified targets during cleanup.
- Treating graphical, terminal, and JSON clients as separate products.
- Building marketplace rankings, payments, reviews, or recommendations into the
  integration manager.

## 9. Terminology

- **Integration:** A built-in THPM record with readiness, apply, and lifecycle
  behavior for one application capability.
- **Native record:** Read-only visibility for behavior owned by Omarchy.
- **Authored asset:** An application-specific file supplied by the active theme.
- **Generated fallback:** Output derived from Omarchy semantic colors when no
  authored asset is present.
- **Intent:** Persisted enabled or disabled state.
- **Available:** Required application and inputs are actionable now.
- **Applicable:** The active theme requests a conditional compatibility adapter.
- **Managed target:** A file, symlink, block, selection, or external effect THPM
  records as its responsibility.
- **Relinquish:** Stop selecting or managing an effect while restoring a prior
  state when safe.
- **Retired integration:** Removed from active enablement and apply behavior while
  guarded cleanup remains.
- **Committed partial failure:** State or package changes committed, but a later
  refresh, reload, or cleanup step failed.

## 10. Functional requirements

### 10.1 Current-state gap register

The following gaps are known at the time of this proposal and must not be read as
already-satisfied guarantees:

- readiness inspection occurs outside the per-adapter exception boundary and can
  abort later integrations;
- QML and TUI use the shared service but reduce some detailed outcomes, changed
  paths, partial-commit state, and recovery information;
- availability is overloaded to keep cleanup actionable when an application or
  authored asset is absent;
- Zellij restores prior selection, while Zed and Vicinae selection effects do not
  yet have equivalent guarded restoration;
- state writes `version = 1` but loading does not enforce schema compatibility;
- Discord conflict policy is enforced during normal mutation but not against a
  manually conflicting persisted state;
- uninstall can collect restoration warnings and still return overall success;
- the source uninstaller can remove the runtime after service cleanup failure;
- source archives are checksummed, but source installation still resolves broad,
  unhashed Python dependency ranges from the configured package index;
- ownership is currently conflated with availability in snapshot presentation;
- confirmation metadata is a Boolean and does not yet carry a common risk
  description or reversibility class;
- SwayNC output needs an end-to-end loader and isolated visual validation path;
- Arch package, executable QML, locking, and complete installed-artifact tests are
  not current CI gates.

The requirements below define the proposed resolution of these gaps.

### FR-1: Platform and palette contract

1. THPM shall support the current stable Omarchy release at the time of each THPM
   release and Python 3.11 or newer.
2. THPM shall use `omarchy-theme-color --all` when available.
3. Canonical long semantic color names shall override conflicting compatibility
   aliases when non-empty.
4. Missing or invalid required semantic colors shall fail the dependent operation
   with an actionable error.
5. Palette failures shall not make the TUI unusable; the TUI shall use a readable
   fallback and show degraded status.

### FR-2: Registry contract

Every active integration shall have a complete declared contract covering:

- stable unique ID;
- user-facing label, category, and description;
- integration kind;
- required commands;
- authored assets and generated inputs;
- default enabled state;
- confirmation policy;
- target effects;
- readiness and applicability rules;
- apply behavior;
- disable and uninstall behavior;
- reversibility classification;
- conflict set;
- live reload or restart behavior;
- behavioral and package tests.

Registry validation shall fail CI for duplicate IDs, missing templates, undeclared
targets, target collisions without conflict policy, active records without apply
behavior, or writable effects without cleanup classification.

For 1.0, this contract may be represented across registry metadata, adapter code,
documentation, and tests. A centralized machine-readable effect model is a later
refactor unless a release-critical safety gap requires it sooner.

### FR-3: State

1. State shall be stored under `$XDG_STATE_HOME/thpm` and written atomically.
2. Missing state shall resolve to registry defaults.
3. Malformed state shall fail closed and must not be silently replaced.
4. Unknown plugin IDs shall not become active.
5. State schema versions newer than the running binary supports shall fail closed.
6. Renamed and retired IDs shall have explicit migration rules.
7. A downgrade shall not silently rewrite a newer unsupported state schema.

### FR-4: Readiness and applicability

1. Snapshot, enable policy, Doctor, and hook application shall use the same
   readiness implementation.
2. Readiness, cleanup capability, ownership, applicability, and enabled intent
   shall remain separate fields.
3. An unavailable disabled integration cannot be enabled.
4. An enabled unavailable integration remains disableable for cleanup.
5. Missing authored assets shall not block cleanup of prior managed output.
6. Conditional compatibility integrations shall be non-applicable, not unhealthy,
   when the active theme does not request them.
7. Exceptions during readiness inspection shall be isolated to that integration.

### FR-5: Theme application

1. The theme hook shall attempt each enabled active integration in registry order.
2. Each attempted integration shall return exactly one status: `applied`,
   `unchanged`, `skipped`, or `failed`.
3. One integration failure shall not prevent later integrations from running.
4. Changed files and completed actions shall remain visible when a later reload
   fails.
5. Repeated application with unchanged inputs shall not rewrite files or emit
   false restart warnings.
6. Generated output containing unresolved template placeholders shall never be
   deployed.
7. External commands shall use argument vectors, bounded timeouts, and explicit
   nonzero-exit diagnostics.

### FR-6: Authored and generated precedence

1. Authored active-theme assets shall take precedence over generated fallbacks.
2. Generated fallbacks shall map from semantic roles, not scrape another
   application's generated output.
3. Every fallback shall have deterministic output and validation tests.
4. Applications with independent native or third-party fallback systems shall not
   be modified unless THPM explicitly owns that effect.

### FR-7: Ownership and restoration

1. THPM shall remove a target only when ownership is proven by valid state,
   digest, managed marker, or positive legacy match.
2. Before first takeover, THPM shall record whether the target existed.
3. Regular files shall record prior digest and mode and retain a validated backup.
4. Symlinks shall record and restore the link target.
5. Managed output shall record installed digest and mode.
6. Interrupted replacement shall remain recoverable without losing the original
   backup.
7. A user-modified target shall be preserved with a warning.
8. Invalid restoration state or backup shall fail closed.
9. Shared files shall use bounded managed blocks or a format-aware edit with a
   recorded pre-image.
10. Multi-file effects shall declare whether they are transactional, retryable,
    or committed with residual cleanup.

### FR-8: Enable and disable

1. Enabling shall validate readiness and required confirmation before mutation.
2. Enabling shall persist intent, reconcile inputs, and refresh the active theme.
3. If state commits but refresh fails, the response shall state `committed: true`,
   retain the saved setting, and provide a recovery command.
4. Disabling shall stop future hook execution immediately.
5. Disabling shall remove rendered THPM input and relinquish managed effects.
6. Cleanup failure after state commitment shall return `cleanupIncomplete`,
   retained paths, and a retry command.
7. Shared-target conflicts shall be enforced during state mutation, state load,
   and hook application.

### FR-9: Uninstall

1. Uninstall shall apply the same guarded cleanup rules as disable.
2. Uninstall shall include retired integration cleanup.
3. Uninstall shall preserve user-modified and unknown targets.
4. Retaining a user-modified file is a successful cleanup with a warning.
5. Missing or invalid restoration data that prevents a promised restoration is an
   incomplete cleanup and shall make the operation unsuccessful.
6. Runtime removal shall not hide an incomplete cleanup result.
7. Uninstall shall distinguish integration cleanup, source-runtime removal, and
   package removal.
8. A successful full uninstall shall remove integration preferences, backups,
   restoration records, and other THPM product state.
9. If cleanup is incomplete, uninstall shall retain the recovery data needed to
   inspect and retry the operation rather than claiming a complete uninstall.

### FR-10: Confirmation and risk

1. Confirmation shall be registry or operation metadata enforced by the service.
2. JSON mode shall never prompt or launch an interactive terminal.
3. Human CLI may prompt only with interactive stdin and stdout.
4. TUI and QML shall present the same risk description before resubmitting a
   confirmed operation.
5. External or non-reversible actions shall be labeled separately from reversible
   managed-file effects.
6. An irreversible effect shall require a clear warning and explicit confirmation
   that states what will persist after disable or uninstall.

### FR-11: Service and JSON contract

Every service response shall include:

- `schemaVersion`;
- `ok`;
- `operation`;
- `busy`;
- `summary`.

Operation responses shall use stable structured fields for results, counts,
changed paths, actions, warnings, errors, commitment, pending work, retained
files, and recovery commands. Breaking changes require a schema version increase.

CLI exit codes shall be:

- `0` when `ok` is true;
- `1` when an operation completes with `ok` false;
- `2` for command-line parsing errors.

### FR-12: User interfaces

CLI, QML, and TUI shall expose the same four product areas:

- overview;
- integrations;
- Doctor;
- system and update actions.

Each integration view shall show intent, availability, applicability, ownership,
missing prerequisites, active authored assets, warnings, confirmation, and restart
requirements. Native records shall be read-only.

The Omarchy Menu launch target shall be a separate GUI or TUI preference and must
not duplicate integration state.

### FR-13: Doctor

Doctor shall inspect:

- required Omarchy capabilities;
- active palette validity;
- state validity and schema compatibility;
- integration readiness;
- conditional compatibility synchronization;
- managed target and restoration-state health;
- pending migrations;
- retired integration residual output;
- package and user UI synchronization where detectable.

Doctor shall provide separate errors and warnings and support filtering by active
integration ID.

### FR-14: Installation and migration

1. Pacman shall own system files; per-user setup shall run as the desktop user.
2. Source installation shall stage and validate a private runtime before user
   mutation.
3. Recognized legacy files shall be archived under THPM state.
4. Unknown legacy files and custom hooks shall remain untouched.
5. Migration shall use recognition and positive matching, never execute legacy
   content.
6. Versioned migrations shall write completion markers only after successful
   completion.
7. Refresh work inside a rollback boundary shall be deferrable and retryable.

### FR-15: Updates and packaging

1. Package-managed installs shall update through AUR tooling.
2. Source-managed installs shall update through verified GitHub release artifacts.
3. Source archives require a SHA-256 companion and bounded safe extraction.
4. Runtime activation, reconciliation, and UI deployment shall roll back together
   before the commit boundary.
5. A post-commit theme refresh failure shall retain the new runtime and provide an
   exact recovery command.
6. AUR update results shall separately report package commitment, theme refresh,
   and per-user QML refresh outcomes. `thpm update` shall automatically reconcile
   integrations and refresh the invoking user's QML installation after a committed
   update; failures shall be explicit and retryable.
7. Local Arch packages shall be buildable from the exact working tree without
   publishing or replacing the public release metadata.
8. Release checks shall verify version consistency across Python, QML, Git tags,
   archives, AUR metadata, and release notes.
9. Source releases shall include an exact dependency lock with hashes for the
   private runtime, and source installation/update shall require those hashes.
   Arch packages may continue using signed repository packages within declared
   compatible ranges.

### FR-16: Integration support lifecycle

An integration progresses through these stages:

1. **Candidate:** contract and ownership design only; not exposed.
2. **Experimental:** opt-in, explicitly labeled, end-to-end validation incomplete.
3. **Supported:** verified application loading path, full lifecycle, docs, and tests.
4. **Deprecated:** still functional, replacement or removal announced.
5. **Retired:** removed from active registry; apply disabled; guarded cleanup kept.
6. **Cleanup withdrawn for safety:** exceptional removal of cleanup code only when
   retaining it is demonstrably unsafe and the migration impact is documented.

A status for every active integration shall be documented or machine-readable
before 1.0. Experimental integrations shall be visibly labeled and are exempt from
supported-certification gates, but they still require safe ownership, disable, and
uninstall behavior. They may not be presented as fully supported.

A supported integration must have an automated artifact/lifecycle test, a
documented real-application validation procedure against recorded application and
Omarchy versions, and maintainer signoff. A file-copy test alone does not qualify it
as supported.

Retired cleanup shall remain indefinitely unless retaining it creates a security or
data-safety issue.

## 11. Supported integration policy

### 11.1 Native records

Native records communicate Omarchy ownership and are never writable through
ordinary THPM enable/disable operations. A native gap may be covered only through
a narrow compatibility integration with explicit applicability detection.

### 11.2 Active built-in integrations

The registry is the source of truth for the active list. Documentation should
describe capabilities and precedence but should not maintain an independent count
that can drift.

### 11.3 Current validation priority

The following classes require real-application validation before 1.0 support is
considered complete:

- reload-based integrations such as SwayNC and Spicetify;
- application selection integrations such as Vicinae and Zed;
- profile-based browser integrations;
- local editor extension installation;
- integrations that require process restart rather than reload;
- action integrations with effects THPM cannot reverse.

SwayNC is a concrete support-definition test: deploying `colors.css` is not enough
unless an active stylesheet imports it and a real or isolated SwayNC process loads
that stylesheet. SwayNC shall be labeled experimental and disabled by default until
that import path and isolated visual validation are complete.

### 11.4 Retired integrations

Windsurf is the first retired-integration precedent. It no longer belongs
in the active registry after replacement by a product with a different command,
profile, and extension lifecycle. THPM retains guarded cleanup for its historical
`.windsurf` managed destination.

The current implementation is an initial precedent, not yet a complete generic
retirement framework. Retirement metadata, state migration, retention dates,
Doctor reporting, user-modification coverage, and uninstall coverage remain to be
formalized.

## 12. Nonfunctional requirements

### NFR-1: Reliability

- Individual file writes shall be atomic.
- Mutations, migrations, and updates shall use separate non-blocking locks.
- Integration and readiness failures shall be isolated per plugin.
- Every partial commit shall be machine-readable and recoverable.
- No-op application shall be idempotent.

### NFR-2: Security

- Process execution shall avoid `shell=True` and use fixed argument vectors.
- Every external process shall have a bounded timeout.
- Paths derived from application configuration shall remain inside approved roots.
- Data-only editor and theme assets shall be structurally validated and size
  bounded.
- Sensitive effects shall require service-level confirmation.
- External plugin package version 1 shall prohibit executable content and arbitrary
  destinations.
- Runtime locks, restoration metadata, and backups shall live in private
  user-owned directories with restrictive modes. Fallback lock creation must not
  follow attacker-controlled symlinks or use a cross-user predictable file in
  shared `/tmp`.

### NFR-3: Data preservation

- THPM shall have zero known code paths that delete an unverifiable user target.
- Backups and restoration metadata shall be validated before use.
- User modifications shall be retained and surfaced.
- Cleanup shall be safely retryable.

### NFR-4: Performance and bounded work

- State listing and local snapshots should complete within 250 ms on a documented
  benchmark fixture, excluding application probes explicitly classified as
  expensive.
- A no-op hook should complete within 2 seconds on that fixture when enabled
  integrations do not invoke reload commands.
- Application reloads should use a 5-second default timeout unless the integration
  contract documents another bound.
- Theme refresh shall remain bounded at 180 seconds.
- Source downloads, extraction, runtime staging, and package updates shall retain
  explicit size and wall-clock limits.
- TUI work shall run in background workers; QML processes shall have a defined
  timeout or cancellation path.

The benchmark fixture must define hardware class, warm or cold cache, registry
size, enabled integrations, and probe behavior. These are proposed target service
levels and require benchmark tests before becoming release gates.

### NFR-5: Compatibility

- CI shall cover supported Python versions.
- Dependency ranges shall stay synchronized across project metadata, source
  installer, updater, stable package, VCS package, and local package builder.
- Source-runtime dependency locks and hashes shall be generated from an approved
  release process and verified during installation and update.
- Package tests shall import and invoke the installed artifact, not an unrelated
  system package or source directory.
- Omarchy command and palette compatibility shall be tested against the then-current
  stable Omarchy release before each THPM release.
- Runtime support is Linux with the current stable Omarchy release and Unix
  facilities such as `fcntl`.
  Stable binary distribution is Arch Linux through AUR; source installation on
  another Omarchy-compatible Linux environment is best effort unless explicitly
  certified.
- Supported runtime dependency ranges include Rich 14 through 15 and Textual
  8.2.8 through the supported 8.x series.

### NFR-6: Accessibility and usability

- Human output shall remain readable without color.
- Redirected output shall not contain terminal animation.
- TUI shall retain its small-terminal guard and keyboard navigation.
- Frontends shall use plain language for ownership, retained files, partial
  commitment, restart requirements, and recovery actions.

## 13. Approved product decisions

### Decision 1: Stabilize built-ins before external plugins

External plugin installation should not enter the 1.0 critical path. The ownership
ledger, removal semantics, and transaction model should first be made consistent
for built-ins.

### Decision 2: Use the standard Zed lifecycle

Zed shall use standard enable and disable operations. `thpm zed setup` shall be
deprecated rather than remain a separate one-shot lifecycle. Zed and Vicinae shall
restore a prior selection only when the application still selects THPM's value.

### Decision 3: Treat application selection as an owned effect

When THPM changes an application selection, it should record the prior selection
and restore it only if the current selection still equals the THPM value. If an
application cannot support safe restoration, the integration must disclose that
its selection effect persists after disable.

### Decision 4: Separate ownership from availability

An unavailable integration can still be THPM-owned. Snapshot ownership should not
change to `unavailable`; availability should remain an independent field.

### Decision 5: Use committed disable with explicit residual cleanup

Disabling should commit intent promptly so future hooks stop running. Cleanup
failures should not silently roll the integration back to enabled. They should
return `cleanupIncomplete`, residual effects, and a retry command.

### Decision 6: Formalize reversible effect classes

Registry/effect metadata should distinguish:

- fully reversible managed files;
- managed blocks or selections;
- relinquishable but persistent effects;
- external non-reversible actions.

UI and uninstall summaries should reflect these classes.

### Decision 7: Require end-to-end validation for support claims

Every supported integration must prove that the application loads the installed
theme. Integrations that only copy output without verified loading must be labeled
experimental or retired.

### Decision 8: Keep ordinary external plugins data-only

External plugins begin after a stable 1.0 and use declarative, brokered operations.
Built-in adapters remain trusted executable THPM package code. Arbitrary third-party
code is not part of the ordinary plugin model; a future executable tier may be
considered only as a separate, explicitly unsafe product with its own approval and
threat model. A marketplace is optional and is the final distribution phase.

### Decision 9: Fail closed across trust boundaries

Older THPM versions shall reject newer state schemas. Cryptographic release
attestations are required before external plugin distribution begins. Irreversible
effects require warning, confirmation, and honest persistence disclosure.

### Decision 10: Support the current stable platform

Each THPM release targets the then-current stable Omarchy release. Promotion of an
integration to supported requires automated lifecycle coverage, real-application
validation with documented versions, and maintainer signoff. Experimental
integrations remain visible but disabled by default.

## 14. Success metrics and release gates

### 14.1 1.0 release gates

- All automated tests pass on every supported Python version.
- Every active integration has readiness, apply, no-op, disable, uninstall, and
  user-modification preservation coverage appropriate to its effect class.
- Every supported integration has a documented end-to-end validation path.
- Every supported integration records validated application and Omarchy versions
  and has maintainer signoff.
- Readiness exceptions cannot abort later integrations.
- Lock contention is covered by cross-process tests.
- Invalid state and restoration metadata fail closed.
- Source update failure injection covers every rollback boundary.
- Stable and VCS Arch packages build in a clean Arch environment.
- Installed package smoke tests invoke packaged code and assets.
- CLI JSON responses validate against operation schemas.
- Maintained docs contain no contradictory install, update, enable, or retirement
  instructions.
- Windsurf no longer appears as an active integration and legacy cleanup remains
  tested.
- SwayNC is visibly experimental and disabled by default until its stylesheet import
  and isolated visual validation are verified.

### 14.2 Reliability metrics

- Zero confirmed deletion or overwrite of unverifiable user-owned content.
- 100 percent of attempted integrations receive an explicit result status.
- 100 percent of external subprocesses have documented timeouts.
- 100 percent of committed partial failures provide a recovery action.
- 100 percent of active registry entries declare cleanup and reversibility.

### 14.3 Product quality metrics

- Theme changes produce no false success for an application that did not load the
  installed output.
- No-op theme application produces no unnecessary writes or restart warnings.
- Doctor identifies missing prerequisites and unhealthy managed state without
  requiring users to inspect files manually.
- CLI, QML, and TUI represent the same fixture with equivalent policy and outcome
  semantics.

## 15. Acceptance criteria

### AC-1: Normal theme change

Given multiple integrations are enabled, when Omarchy emits `theme-set`, then THPM
applies every actionable integration, skips unavailable ones, isolates failures,
and returns complete per-status counts and per-plugin outcomes.

### AC-2: Authored precedence

Given both an authored asset and generated fallback exist, when the integration is
applied, then the authored asset is installed and the generated fallback is not
used.

### AC-3: Safe disable

Given THPM displaced a user file, when the integration is disabled and the current
target still matches THPM's installed digest, then the original file and mode are
restored.

### AC-4: User modification

Given a user modified a THPM-managed target, when disable or uninstall runs, then
the modified target remains and the operation reports it as retained.

### AC-5: Invalid restoration state

Given restoration metadata or backup is invalid, when cleanup runs, then THPM does
not overwrite or remove the target and reports incomplete cleanup.

### AC-6: Partial refresh failure

Given enablement state commits, when Omarchy refresh fails, then the setting remains
saved and the response reports `ok: false`, `committed: true`, and a recovery
command.

### AC-7: Frontend policy parity

Given the same service fixture, when displayed in CLI JSON, QML, and TUI, then
ownership, intent, availability, applicability, confirmation, warnings, and result
meaning are equivalent.

### AC-8: Retired integration

Given a retired integration exists in old state or managed output, when THPM
reconciles, then it is absent from active enablement and guarded cleanup restores
or preserves its legacy target according to ownership evidence.

### AC-9: Package ownership

Given `/usr/bin/thpm` is pacman-owned, when update is requested, then THPM uses the
AUR update path and never activates a source runtime over package-owned files.

### AC-10: Source update rollback

Given a staged source update fails before commit, when rollback runs, then the old
runtime and snapshotted integration surfaces are restored. Given only the final
theme refresh fails after commit, then the new runtime remains and recovery is
reported.

### AC-11: Complete and incomplete uninstall

Given cleanup succeeds, when full uninstall completes, then THPM preferences,
backups, and restoration records are removed. Given promised restoration cannot be
completed, then uninstall fails, reports residuals and retry instructions, and
retains the recovery data needed for that retry.

## 16. Roadmap

### Phase 0: 1.0 lifecycle stabilization

- Replace Zed setup with standard enable/disable semantics and deprecate the setup
  command.
- Isolate readiness failures.
- Define committed disable and incomplete cleanup responses.
- Harden uninstall failure behavior.
- Enforce conflicts at load and apply time.
- Separate ownership from availability.
- Validate every active integration end to end.
- Mark SwayNC experimental and disabled by default until stylesheet import and
  isolated visual validation are complete.
- Finish Windsurf retirement and legacy cleanup.
- Add registry/effect validation.

### Phase 1: Release and packaging hardening

- Build Arch packages in CI.
- Validate `.SRCINFO` and release metadata consistency.
- Test installed commands and data files.
- Add tag/release verification workflow.
- Align package post-upgrade, README, and UI refresh instructions.
- Add artifact signatures or attestations before external plugin distribution.

### Phase 2: Common effect and transaction model

- Centralize targets, conflicts, ownership, reversibility, and cleanup declarations.
- Add a journal for multi-file lifecycle operations.
- Add durable residual-effect reports.
- Migrate built-in integrations incrementally.

### Phase 3: Local external plugin packages

- Strict `thpm-plugin.toml` schema.
- Data-only package format.
- Safe extraction and content quotas.
- Logical allowlisted targets and brokered operations.
- Content-addressed store and inventory.
- Digest-bound check, add, inspect, verify, and remove plans.
- Disabled-by-default external plugins.

### Phase 4: Frontend parity for external plugins

- Installed and Discover views.
- Review of identity, digest, capabilities, targets, conflicts, and effects.
- Two-step JSON approval token.
- Equivalent CLI, TUI, and QML flows.

### Phase 5: Immutable Git and provenance

- HTTPS-only resolver by default.
- Branch and tag resolution to immutable commits.
- No hooks, submodules, build scripts, or source execution.
- Signature or attestation verification.
- Capability-delta approval on update.
- Audit and Doctor integration.

### Phase 6: Signed catalog

- TUF-style root, timestamp, snapshot, targets, expiry, and rollback protection.
- Delegated publisher policy and revocation.
- Same package and lifecycle APIs as local and Git sources.
- Data-only eligibility for the initial catalog.

This marketplace phase is optional. Executable third-party plugins are outside this
roadmap and require a separately approved unsafe-tier design if pursued.

## 17. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Integration writes a file the app does not load | False support claim | Require end-to-end loader validation |
| User target mistaken for managed output | Data loss | Digest ledger, backups, fail-closed cleanup |
| One adapter blocks theme switching | Broken theme changes | Failure isolation and strict timeouts |
| State commits before cleanup fails | Residual effects | Explicit committed disable and retry plan |
| Frontends diverge | Policy bypass or confusing UX | Service enforcement and contract fixtures |
| Omarchy adds native parity | Duplicate ownership | Applicability detection and retirement process |
| Application renames or changes profiles | Stale unsafe adapter | Deprecation and guarded retirement |
| Release metadata drifts | Broken installs or updates | Automated release consistency checks |
| Source dependency resolution is compromised or drifts | Untrusted or incompatible private runtime | Exact release lock, hashes, and staged import checks |
| GitHub release account compromise | Malicious archive and checksum | Signatures or attestations beyond SHA-256 |
| External plugin expands privileges | Desktop compromise | Data-only v1 and logical allowlisted effects |
| Marketplace metadata rollback | Old or revoked package installation | TUF-style expiry and rollback protection |

## 18. Open questions

1. Which built-in external actions are intentionally non-reversible?
2. What reference environment and application versions define end-to-end support?
3. Should compatibility integrations be hidden automatically after verified native
   parity, or require an explicit release decision?
4. What backup retention and storage limits should apply while THPM is installed?
5. Which signature or attestation system should source releases use?
6. Should a separately isolated and explicitly unsafe executable external-plugin
   tier ever be designed?

## 19. Evidence map

This PRD was reconstructed from the current product and design record:

- `README.md`: product overview, requirements, installation, use, and development.
- `docs/architecture.md`: current architecture and ownership contract.
- `docs/architecture-map.md`: data flow, lifecycle, transaction boundaries, and
  current system map.
- `docs/plugins.md`: built-in integration and lifecycle rules.
- `docs/quattro-compatibility-plan.md`: Omarchy 4 compatibility boundaries.
- `docs/plugin-security-and-distribution-design.md`: proposed external plugin
  package, policy, and marketplace architecture.
- `src/thpm/registry.py`: active and native integration inventory.
- `src/thpm/service.py`: shared operations and response semantics.
- `src/thpm/integrations.py`: readiness, apply, ownership, reload, and cleanup.
- `src/thpm/state.py`: intent persistence and locking.
- `src/thpm/update.py`: origin-aware update, verification, activation, and rollback.
- `src/thpm/compat.py` and `src/thpm/zed.py`: compatibility and authored-theme
  security models.
- `assets/qml/Panel.qml.in` and `src/thpm/tui.py`: frontend behavior.
- `tests/test_thpm.py`: executable behavioral contract and known coverage boundary.
- `packaging/aur/`, `install.sh`, `uninstall.sh`, and `scripts/`: distribution and
  release workflows.
- `CHANGELOG.md` and `releasenote.md`: delivered behavior and release intent.

## 20. Approval record

The maintainer approved the product direction on 2026-08-01 through an explicit
decision interview. The approved record includes:

- lifecycle stability as the 1.0 priority and external plugins after stable 1.0;
- standard Zed enable/disable semantics and deprecation of `zed setup`;
- committed disable, explicit residual cleanup, and fail-closed uninstall;
- ownership independent from availability;
- indefinite retired cleanup unless retaining it is unsafe;
- current-stable Omarchy support and evidence-based integration promotion;
- automatic integration and per-user QML refresh during update;
- data-only ordinary external plugins, with any executable tier requiring separate
  future approval;
- cryptographic attestations before external plugin distribution;
- an optional marketplace only after local and Git package lifecycle maturity.
