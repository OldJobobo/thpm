# THPM 1.0.0rc21

## Reliable updates across CLI, TUI, and GUI

- **Complete update synchronization:** THPM-managed upgrades now reconcile integrations, refresh the active theme, and reinstall the graphical control panel automatically.
- **Consistent interfaces:** CLI, Textual TUI, and QML callers share the same final update result and recovery contract.
- **Visible authorization:** callers without an attached TTY hand package work to a separate Omarchy terminal instead of hiding prompts or running unsafe inline updates.
- **Honest partial failures:** committed package updates report exact `thpm reconcile --refresh` or `thpm ui install` recovery steps when later synchronization fails.
- **Expanded GTK Doctor checks:** detect stale Aether or unmanaged CSS, legacy dark-theme overrides, GNOME appearance drift, portal color-scheme drift, and native probe failures without mutating foreign configuration.
- **Verified release installation:** safely replace only recognized pre-tag checksum placeholders after the published archive digest is verified.

## Install or upgrade

```sh
curl -fsSL https://raw.githubusercontent.com/OldJobobo/thpm/main/scripts/install-arch-release.sh | bash
```

RC21 remains a release candidate. Please report update, control-panel synchronization, GTK diagnostic, or packaging issues.

https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc21
