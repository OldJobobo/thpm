# Changelog

## Unreleased

- Report explicit applied, unchanged, skipped, and failed outcomes instead of silently accepting inert integrations.
- Share actionable-readiness checks across the service, hook runner, frontends, and Doctor.
- Honor declared Firefox, Zen, Superfile, and Cava theme assets, report browser-managed files, and expose bounded reload and steam-adwaita failures.
- Correct cliamp, Steam, Branding, Discord, and nwg-dock prerequisites and user-facing behavior.

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
