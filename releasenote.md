## THPM 1.0.0rc19 is now available

**THPM is made for Omarchy Quattro and supports Omarchy 4.x.**

### Install or upgrade the latest release

```sh
curl -fsSL https://raw.githubusercontent.com/OldJobobo/thpm/main/scripts/install-arch-release.sh | bash
```

The installer resolves the newest published GitHub release, verifies its source archive and checksum, builds the Arch package with `makepkg`, installs it through pacman, and completes THPM's per-user setup.

## What’s new in rc19

### Obsidian Terminal theming is restored

THPM once again synchronizes the Obsidian Terminal community plugin’s xterm.js colors after Omarchy theme changes. This integration is separate from Omarchy’s native Obsidian application theme support.

### Safe discovery and updates

The adapter discovers Terminal settings through Obsidian’s registered vaults, common vault locations, or explicit `OBSIDIAN_VAULT_PATH` and `OBSIDIAN_TERMINAL_DATA_JSON` overrides. It validates all discovered documents first, refuses malformed or symlinked settings, atomically updates files, and preserves every option outside `terminalOptions.theme`.

### Truthful restart reporting

The running Terminal plugin does not reliably reload settings changed on disk. RC19 therefore reports Obsidian as restart-required after a palette change rather than falsely claiming that an open terminal repainted.

### Verification

The rc19 release passes the complete automated suite: 315 tests.

This remains a release candidate. Please report any issues you find.

[View the release](https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc19)
