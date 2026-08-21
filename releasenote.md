## THPM 1.0.0rc22 is now available

**THPM is built for Omarchy Quattro and targets Omarchy 4.x. RC22 is a browser-theming and reliability release for Zen, the graphical manager, menu updates, source rollback, Zed setup, and CLI discoverability.**

### Install or upgrade the latest release

```sh
curl -fsSL https://raw.githubusercontent.com/OldJobobo/thpm/main/scripts/install-arch-release.sh | bash
```

The installer resolves the newest published GitHub release, verifies its source archive and checksum, builds the Arch package with `makepkg`, installs it through pacman, and completes THPM's per-user setup.

## What’s new in rc22

### Zen follows the active Omarchy palette

The generated Zen fallback now styles modern browser chrome, including Zen palette variables, sidebar controls, navigation surfaces, the URL bar, and the app-content wrapper. Upgraded profiles migrate complete legacy Firefox and Zen hook import blocks while preserving unrelated user CSS.

Firefox and Zen now report a required restart after profile stylesheets change so new `userChrome.css` colors are not mistaken for a failed hook. Removing only an unused rendered source does not produce a false restart notice. The Zen path was also validated live against the current browser release and an active Omarchy palette.

### The graphical manager and menu recover safely

The Omarchy menu now launches the graphical manager through a stable `thpm ui open` path. THPM can stage and switch stale QML, verify Shell discovery and readiness with bounded retries, and open the TUI as a recovery surface when the graphical path cannot load. An idempotent post-update hook keeps already-installed control panels synchronized.

Every user-scoped menu writer now shares one per-user lock. Surface changes validate the next JSONC document before committing, restore the previous menu when state persistence fails, and remain coherent across concurrent install, synchronization, repair, removal, and surface-selection operations.

### Updates, Zed setup, and CLI help are more predictable

Source-update rollback now preserves relative, absolute, and dangling symlinks exactly. Snapshot ownership comes from the staged runtime's complete template registry, including obsolete outputs that the next version must remove.

Direct `thpm zed setup` preserves the user's existing `zed-extra` synchronization state instead of silently enabling ongoing synchronization. Normal enable operations through the CLI, TUI, and GUI still opt into that behavior explicitly.

Built-in help now documents every root command, nested action, positional argument, global option, and command-specific flag, making the complete CLI discoverable without external documentation.

### Verification

The rc22 preparation passes the complete automated suite: 385 tests, Python 3.11 through 3.14, and clean stable and VCS Arch package builds.

This remains a release candidate. Please report Zen theming, graphical-manager recovery, menu synchronization, source rollback, Zed setup, or packaging issues.

[View the release](https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc22)
