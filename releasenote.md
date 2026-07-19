## THPM 1.0.0rc4 is now available

**THPM is built exclusively for Omarchy Quattro and supports Omarchy 4.x only.**

### Install

```sh
omarchy pkg aur add thpm && thpm install
```

THPM 1.0.0rc4 makes integration results trustworthy and restores conditional compatibility for theme assets that Quattro does not yet handle natively.

### Upgrading from rc3

AUR users can update normally. Source-installed rc3 users can use THPM's built-in updater, which now discovers later release candidates on the RC channel.

### Highlights

- Source-installed rc3 runtimes now retain their virtualenv path and can complete the built-in RC upgrade.
- Every enabled integration now reports an explicit applied, unchanged, skipped, or failed outcome.
- Readiness checks are shared by the service, hook runner, Doctor, CLI, TUI, and QML panel.
- Firefox, Zen, Superfile, and Cava honor declared theme assets and report the files they manage.
- Steam reports missing helpers, subprocess failures, and timeouts instead of silently succeeding.
- Branding, Discord, cliamp, and nwg-dock now describe their actual prerequisites and behavior.
- Conditional GTK compatibility deploys managed GTK3/GTK4 imports while preserving user CSS and stylesheet symlinks.
- Validated local VS Code-family theme bundles install deterministically across VS Code, Insiders, VSCodium, and Cursor.
- Unsafe local editor bundles are rejected for executable capabilities, identity mismatches, traversal, symlinks, unsupported files, or excessive size.
- Doctor and the interfaces distinguish applicability, availability, readiness, and synchronization warnings.
- Palette interpretation now follows Omarchy's canonical `omarchy-theme-color` resolver.

### Compatibility scope

GTK and local editor compatibility activate only when the current theme supplies the relevant assets. Native Omarchy ownership remains authoritative where it already exists, and THPM does not change GNOME settings or kill applications.

This remains a release candidate. Please report installation, update, integration-outcome, or compatibility issues before the final 1.0.0 release.

[View the release](https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc4)
