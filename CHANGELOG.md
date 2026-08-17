# Changelog

## Unreleased

## 1.0.0rc21 - 2026-08-17

- Synchronize package state, integrations, active-theme output, and the graphical control panel across CLI, TUI, and QML update flows. Package authorization remains visible in a separate terminal for callers without an attached TTY, while a private result channel returns the completed transaction and actionable partial-failure recovery.
- Expand Doctor's read-only GTK diagnostics to detect unmanaged or stale Aether CSS, legacy GTK dark-theme overrides, GNOME appearance drift, desktop-portal color-scheme drift, and failed native probes while preserving `gtk-css-compat` and `native-gnome` ownership boundaries.
- Let the verified release-source installer replace the archive's unavoidable pre-tag PKGBUILD checksum placeholder (including legacy `SKIP`) in its temporary build tree, while rejecting any non-placeholder checksum that disagrees with the verified release asset.

## 1.0.0rc20 - 2026-08-16

- Classify every uncertified active integration as Experimental, expose lifecycle status through JSON, CLI, QML, and TUI surfaces, and make fresh state fully opt-in. Existing schema-1 enablement is visibly grandfathered because inherited defaults cannot be distinguished from explicit choices.
- Publish an integration support register with the reference Omarchy baseline, active defaults, honest evidence gaps, retired cleanup, repeatable real-application certification procedures, and maintainer signoff requirements.
- Report incomplete disable and uninstall cleanup with committed state, structured residuals, retained recovery paths, and exact retry commands; preserve source runtime and ownership metadata while recovery remains necessary.
- Fail closed on unsupported or conflicting persisted state, isolate readiness inspection failures per integration, safely normalize migrated Discord intent, and preserve existing SwayNC enablement while default-disabling it for fresh state.
- Pin every transitive source-runtime dependency to a SHA-256-verified universal wheel and validate the shared lock on Python 3.11 through 3.14.
- Add Python 3.14 CI, clean stable and VCS Arch builds of the exact pull-request checkout (including the pre-tag phase), generated `.SRCINFO` validation, installed-package smoke tests, and an aggregate required status.
- Add phased release verification for committed version surfaces, exact tagged archives and checksums, canonical Git trees and permissions, stable and VCS PKGBUILDs, and generated `.SRCINFO` metadata.
- Build Arch packages with `/usr/bin/python` so pacman-owned modules cannot be mixed with mise-managed user environments.
- Preserve Shibumi Shell's comment-terminated JSONC menu blocks when installing or removing THPM launchers.
- Render Heroic's semantic CSS variables from the active Omarchy palette.

## 1.0.0rc19 - 2026-08-07

- Restore the Obsidian Terminal community-plugin integration with vault discovery, validated atomic settings updates, semantic xterm.js colors, preserved unrelated options, and honest Obsidian restart reporting.

## 1.0.0rc18 - 2026-08-06

- Make Cava integration opt-in and complete its lifecycle with safe selector setup/restoration, Cava 0.10.6+ checks, PID-specific `SIGUSR1` reloads, repairable Doctor diagnostics, and transactional `thpm doctor cava --fix` support. Persisted `cava = true` defaults from older releases remain disabled until a successful confirmed setup records new consent.
- Add bounded private operation journaling and `thpm report [plugin]` JSON support reports with duration evidence, filtered recent outcomes, file metadata, redaction, symlink-safe rotation, and strict size/permission limits.
- Make Spotify setup self-healing after Spicetify's backup exists: ship and initialize the missing Omarchy companion stylesheet, select `current_theme = omarchy` with `color_scheme = Base`, and preserve existing user-owned styles.
- Add an opt-in Pi live-reload compatibility integration that safely emits a metadata event only when the installed `omarchy-system` theme matches Omarchy's current native output, without claiming sessions using other theme overrides repainted.

## 1.0.0rc17 - 2026-08-05

- Replace the obsolete compact Discord variable fallback with an Omarchy-colored Midnight surface, hosted from THPM's own MIT-compliant vendored base and rendered from the complete semantic palette.
- Add a temporary verified release-source installer for Arch systems while AUR submissions are unavailable; it builds the stable package with `makepkg`, installs it through pacman, and completes per-user setup.

## 1.0.0rc16 - 2026-08-02

- Skip SwayNC's reload command when its daemon is not running, preventing the installed but inactive client from waiting on a masked D-Bus service and timing out the theme hook.
- Stream structured integration start and finish events through `thpm run` and normal terminal-driven Omarchy theme switches, show truthful current/total progress while work is running, retain a real-time outline of every completed integration by default, and reserve adapter details, changed paths, and captured subprocess output for explicit `--verbose` mode.
- Restore live Zellij color updates by refreshing its watched `config.kdl` after an external managed theme changes, while preserving custom paths, safe restoration, and true no-op behavior.
- Retire the obsolete Windsurf integration after the editor's replacement by Devin Desktop, while retaining guarded reconciliation and uninstall cleanup for legacy managed output.
- Retire the Vicinae integration while retaining guarded reconciliation and uninstall cleanup for both historical managed theme destinations.
- Retire the Typora integration while retaining guarded reconciliation and uninstall cleanup for its former managed stylesheet.
- Add a versioned user restart policy with CLI, GUI, and TUI controls: supported running apps can restart automatically, or remain open while THPM sends one notification naming pending restarts. Spotify honors both policies without launching a closed client; unsafe generic GTK and nwg-dock restarts remain notification-only.
- Avoid spurious automatic-hook failures by invoking application reloads and restart notices only when managed content changed, while making explicit **Apply active theme** actions force restart-required adapters such as Spotify even when files are already current.

## 1.0.0rc15 - 2026-07-31

- Show a compact, color-aware outcome line for every enabled THPM integration during terminal-driven Omarchy theme changes and `thpm run`, while preserving structured JSON reporting and honest failure status.

## 1.0.0rc14 - 2026-07-28

- Fix CLI progress and confirmation handling so enable/disable commands show real stages, never hide prompts behind the progress display, report failures honestly, and suggest valid integration names for typos.
- Make nested options and JSON errors consistent, reject interactive TUI launches in JSON mode, bound update subprocesses, and refresh active theme outputs after installs and updates.

## 1.0.0rc13 - 2026-07-28

- Make the normal CLI, TUI, and graphical-manager enable flow for Zed install and select **THPM Current** transactionally instead of requiring a separate setup command.

## 1.0.0rc12 - 2026-07-28

- Add validated authored Zed theme support with `zed.json` / `aether.zed.json` precedence, a stable **THPM Current** identity, restorable installation, fail-closed legacy migration, and strict separation from the independently owned Omazed fallback.
- Add `thpm zed status` diagnostics and a confirmed one-time `thpm zed setup` flow that backs up and safely updates JSONC settings without letting normal theme hooks rewrite them.
- Let the graphical manager use the native Omarchy floating-window background and compositor-owned border instead of drawing duplicate outer window chrome.
- Preserve and restore optional, generated, browser, Discord, and Zellij outputs when integrations are disabled, themes stop providing assets, or THPM is uninstalled; preserve user-modified targets and positively identify legacy managed files before cleanup.
- Correct AUR updater progress totals after package installation selects its reconciliation path.

## 1.0.0rc11 - 2026-07-25

- Suspend THPM's Rich live progress display while Yay owns the terminal so package output remains readable and sudo password prompts remain visible and usable.

## 1.0.0rc10 - 2026-07-25

- Document the synchronous AUR update flow and bring the plugin security design's confirmation and availability status in line with the enforced service policy.

## 1.0.0rc9 - 2026-07-25

- Run AUR upgrades synchronously in the invoking terminal, suppress routine package-manager confirmations, and reserve the floating Omarchy terminal for callers without a TTY.

## 1.0.0rc8 - 2026-07-25

- Make detailed stage logs, changed paths, and captured command output the default human interface; add `--quiet` / `-q` as the explicit compact-mode opt-out while retaining `--verbose` compatibility.

## 1.0.0rc7 - 2026-07-25

- Add a TTY-aware Rich command surface with animated spinners, honest stage-based progress bars, elapsed time, semantic color, structured completion details, and `--verbose` logs while preserving plain redirected output, `NO_COLOR`, and decoration-free JSON.

## 1.0.0rc6 - 2026-07-25

- Make bare `thpm update` apply the available update instead of failing because an internal update subcommand was omitted.

## 1.0.0rc5 - 2026-07-25

- Normalize Omarchy's canonical long palette keys to THPM's internal TUI schema with explicit canonical precedence, fixing Doctor and TUI on stock Omarchy themes.
- Convert bundled templates, including stripped color forms, to Omarchy's canonical resolver namespace and reject unresolved generated placeholders before application.
- Add a serialized, versioned, retryable per-user template refresh migration. Install and reconciliation complete it once; rc4 and newer source-update activation paths defer across rollback, source installation refreshes only after commit, and AUR updates reconcile after successful package installation.
- Add canonical-schema, collision, Doctor/TUI, template-rendering, unresolved-output, and upgrade-refresh regression coverage.

## 1.0.0rc4 - 2026-07-19

- Preserve the source virtualenv path during RC updates instead of resolving its Python symlink to the system interpreter.
- Follow Omarchy's canonical `omarchy-theme-color` resolver so Doctor and the TUI accept every palette Quattro can resolve, including legacy-compatible aliases and stock themes with derived values.
- Restore conditional GTK 3/GTK 4 CSS deployment through managed imports, preserving user content and stylesheet symlinks while cleaning only THPM-owned output on theme changes, disable, or uninstall.
- Restore bundled local VS Code-family themes through validated data-only source packages, deterministic VSIX builds, source hashes, Omarchy skip-toggle support, bounded installation, and post-install registration checks.
- Reject unsafe local editor bundles with executable capabilities, identity or contribution mismatches, traversal, symlinks, unsupported files, and package size violations.
- Distinguish non-applicable compatibility integrations from unavailable ones, add synchronization diagnostics, migrate legacy GTK/VS Code state, and narrow native GNOME/VS Code ownership descriptions to actual Omarchy coverage.
- Report explicit applied, unchanged, skipped, and failed outcomes instead of silently accepting inert integrations, while preserving per-plugin failure isolation and partial change reporting.
- Share actionable-readiness checks across the service, hook runner, frontends, and Doctor; surface readiness and native-coverage warnings consistently in CLI, JSON, TUI, and QML.
- Honor declared Firefox, Zen, Superfile, and Cava theme assets, report browser-managed files, and expose bounded reload and steam-adwaita failures.
- Correct cliamp, Steam, Branding, Discord, and nwg-dock prerequisites and user-facing behavior.
- Expand behavioral coverage to 92 tests, add optional QML linting, validate every installed stock Omarchy palette, and verify isolated VSIX installation and wheel packaging.
- Publish finalized rc3 Arch package metadata and release checksum, and reset the VCS package baseline to rc3.
- Document the one-time manual source-upgrade requirement from rc2; RC-channel discovery works automatically from rc3 onward.

## 1.0.0rc3 - 2026-07-17

- Stage and validate source installs before atomic runtime activation, with rollback to the previous runtime on failure.
- Enforce sensitive-plugin confirmation and availability in the shared service, with matching QML, TUI, CLI, and JSON behavior.
- Reject malformed persisted state and unsafe browser profile paths instead of silently overwriting or escaping expected roots.
- Serialize theme-hook mutations, apply newly enabled integrations immediately, and stage the QML panel while the shell is stopped.
- Add RC-aware update discovery, bounded downloads, stricter archive extraction, and streamed checksum verification.
- Expand CI coverage and enforce the supported Textual 8.x range in Arch packaging.

## 1.0.0rc2 - 2026-07-15

- Stage the Omarchy Shell panel as a `.qml.in` payload and install it as `Panel.qml`, preventing package linters from treating shell-private QML imports as system dependencies.
- Correct AUR dependency metadata so clean Arch chroots do not resolve the unrelated `omarchy` placeholder package.

## 1.0.0rc1 - 2026-07-14

- Introduce an independent Omarchy 4.x-native Python control plane.
- Add Quattro semantic templates and one theme hook.
- Add the Omarchy Shell QML plugin manager and menu entry.
- Design the manager with native Omarchy controls, search, concise state counts, and compact integration rows.
- Add migration, diagnostics, JSON output, Arch packaging, and tests.
- Add confirmed, origin-aware updates from the panel with SHA-256 verification and transactional rollback.
- Add a Textual terminal control panel with Overview, Integrations, Doctor, and System sections.
- Add `thpm tui`, active Omarchy palette theming, keyboard shortcuts, and a separate Omarchy terminal menu entry.
- Install and validate Textual in private source runtimes and declare it for Arch packages.
- Add a Ko-fi donation action to the TUI and QML control panels.
- Replace duplicate Omarchy menu entries with one persisted GUI/TUI-selectable entry.
- Prefer complete theme-provided Zellij assets, normalize their installed theme name, and bound app reload helpers so theme hooks cannot stall.
