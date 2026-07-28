## THPM 1.0.0rc13 is now available

**THPM is built exclusively for Omarchy Quattro and supports Omarchy 4.x only.**

### Install or upgrade through Omarchy

```sh
omarchy pkg aur add thpm   # first installation
omarchy update aur pkgs    # update an installed AUR package
```

## What’s new since rc5

### Authored Zed themes now work from the normal THPM controls

Themes can ship a full `zed.json` or compatibility `aether.zed.json` palette. THPM validates the authored theme and installs it under the stable **THPM Current** name, while leaving Omazed completely independent as the generated-color fallback.

Enable **Zed authored theme** from the graphical manager, TUI, or CLI and THPM now completes the whole job: it asks for confirmation, backs up your Zed settings, installs the theme, and selects **THPM Current**. You no longer need to discover and run a separate setup command after enabling it. `thpm zed status` shows the selected source, synchronization state, current Zed selection, and Omazed availability.

### Integrations are safer to enable, disable, and change between themes

THPM now remembers files displaced by optional and generated integrations. When an integration is disabled, removed, or no longer supplied by the active theme, THPM restores the previous file or relinquishes its own output. Files edited by the user are preserved, and older THPM outputs are removed only when they can be positively identified.

This restoration behavior covers optional application themes, generated outputs, browser styling, Discord themes, Zellij, and authored Zed themes.

### A calmer graphical manager

The graphical manager now lets Omarchy Shell and Hyprland own its outer background, border, and corner rounding. This removes the duplicate frame and keeps the manager visually consistent with the active Omarchy theme.

### Clearer command output

Interactive commands now have a proper terminal presentation with meaningful stages, progress, elapsed time, success and failure states, changed-file lists, and captured command output. Detailed results are shown by default; use `--quiet` for compact output. Redirected output, `NO_COLOR`, and JSON automation remain clean and predictable.

### Updates behave like normal terminal updates

Running bare `thpm update` now applies the available update directly. AUR upgrades stay in the terminal that launched them, package output remains readable, and sudo password prompts remain visible and usable. THPM temporarily gets out of Yay’s way, then resumes with reconciliation and an accurate completion report. Non-interactive callers still receive the Omarchy terminal fallback.

### Consistent confirmations and availability reporting

The CLI, TUI, graphical manager, JSON API, and documentation now agree about which integrations need confirmation and which are actually available. THPM reports missing applications or theme assets instead of pretending an integration was applied.

### Special thanks

Special thanks to our beta testers: @HANCORE, @sodipops, @gnugent, and @signal//directive.

This remains a release candidate. Please report Zed, restoration, update, or graphical-manager issues before the final 1.0.0 release.

[View the release](https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc13)
