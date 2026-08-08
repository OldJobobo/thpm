# THPM 1.0.0rc19

## What’s new in rc19

- **Obsidian Terminal theming is restored:** THPM once again synchronizes the Terminal community plugin’s xterm.js palette after Omarchy theme changes.
- **Safe vault discovery:** registered Obsidian vaults, common vault locations, and explicit environment overrides are supported.
- **Preserved settings:** only `terminalOptions.theme` is replaced; unrelated Terminal plugin options remain untouched.
- **Fail-closed updates:** malformed or symlinked settings are refused, and every discovered settings document is validated before writes begin.
- **Honest reload status:** changed Terminal palettes report Obsidian as restart-required instead of claiming that an open plugin instance repainted.

## Install or upgrade

```sh
curl -fsSL https://raw.githubusercontent.com/OldJobobo/thpm/main/scripts/install-arch-release.sh | bash
```

The installer verifies the latest release archive, builds it with `makepkg`, installs it through pacman, and completes THPM’s user setup.

https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc19
