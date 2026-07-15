# Changelog

## Unreleased

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
