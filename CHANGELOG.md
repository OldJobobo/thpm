# Changelog

## Unreleased

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
