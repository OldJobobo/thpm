## THPM 1.0.0rc24 is now available

**THPM rc24 completes the Quattro application-theme fallback audit and publishes retained certification for both fzf and Zellij alongside the ownership, restoration, and semantic palette repairs from rc23.**

### Install or upgrade the latest release

```sh
curl -fsSL https://raw.githubusercontent.com/OldJobobo/thpm/main/scripts/install-arch-release.sh | bash
```

The installer resolves the newest published GitHub release, verifies its source archive and checksum, builds the Arch package with `makepkg`, installs it through pacman, and completes THPM's per-user setup.

## What’s new in rc24

### Safer semantic application themes

GTK receives a complete generated semantic fallback when a theme does not provide authored GTK CSS. Fish and Superfile use corrected target-native color contracts, while fzf remains fully certified after complete automated, lifecycle, restoration, fresh-process, visual, and maintainer-signoff gates on Omarchy Quattro.

Typora remains an opt-in Experimental integration with generated screen colors, neutral print output, restorable file ownership, and change-sensitive restart reporting. Zellij is now Supported after exact merged-source parser, no-op, disable, user-edit, uninstall, restoration, restart-reporting, and real Dune/Last Call transition gates passed with retained evidence and maintainer signoff.

### Obsidian Terminal recovery fails closed

THPM can restorably disable the Terminal community plugin's profile-level Follow Theme setting so its semantic xterm palette remains effective. Ownership records cover only true-to-false changes and preserve unrelated settings and later user edits.

Settings and private recovery paths reject traversal, malformed state, arbitrary targets, symlink leaves and ancestors, and unsafe relative candidates. Missing or malformed owned profiles, failed writes, uncertain atomic replacement, and incomplete rollback retain structured recovery state instead of falsely reporting successful cleanup.

### Native ownership stays native

cliamp keeps its contrast-checked built-in or terminal-ANSI theme by default. THPM installs an authored override only when the theme explicitly opts in with `# thpm:cliamp-use-native`, and restores both file and selector state conservatively.

The uncertified SwayNC adapter is retired because its standalone generated file was not consumed by the active stylesheet. Guarded historical cleanup remains available.

### Verification

The exact merged release tree passes 457 automated tests, release metadata validation, Python compilation, Ruff and ShellCheck static checks, wheel content and isolated-install smoke tests, Python 3.11 through 3.14 CI, and clean stable and VCS Arch package builds. Zellij certification PR #56 passed all 7 required checks and merged.

fzf and Zellij are Supported. Other active adapters remain visibly opt-in Experimental until their complete real-application certification records and maintainer signoff are retained.

This remains a release candidate. Please report application-theme ownership, restoration, migration, or visual compatibility issues.

[View the release](https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc24)
