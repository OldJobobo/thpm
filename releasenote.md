## THPM 1.0.0rc3 is now available

**THPM is built exclusively for Omarchy Quattro and supports Omarchy 4.x only.**

### Install

```sh
omarchy pkg aur add thpm && thpm install
```

THPM 1.0.0rc3 is a release-safety candidate focused on trustworthy installation, plugin controls, and updates across the CLI, graphical panel, and terminal UI.

### Highlights

- Source installs are staged and validated before activation, with runtime rollback on failure.
- Firefox, Zen, and Steam are opt-in and require confirmation through every user interface.
- Newly enabled integrations are applied immediately, while unavailable integrations are rejected by the shared service.
- Corrupt state and unsafe browser profile paths fail safely instead of being silently overwritten.
- QML and TUI controls now surface plugin mutation failures and confirmation prompts consistently.
- RC installations can discover later release candidates through the updater.
- Downloads and release archives have stricter size, path, entry-type, and checksum validation.
- Theme-hook mutations are serialized to avoid lifecycle races.
- The QML panel is installed even when Omarchy Shell is not currently running.
- CI now covers Python 3.11, 3.12, and 3.13 with tests, Ruff, ShellCheck, and isolated wheel builds.

### Lifecycle note

Disabling an integration stops future synchronization and removes its THPM template. It deliberately preserves configuration already installed into an application. Uninstall likewise removes THPM-owned hooks, templates, and control surfaces without deleting application configuration that may have been modified by the user.

This remains a release candidate. Please report installation, update, rollback, or interface issues before the final 1.0.0 release.

[View the release](https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc3)
