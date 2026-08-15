# THPM 1.0.0rc18

## What’s new in rc18

- **Spotify setup now self-heals:** THPM creates the missing Omarchy Spicetify stylesheet, installs its generated colors, and selects the correct theme and color scheme while preserving custom CSS.
- **Cava is safely opt-in:** setup, version checks, targeted reloads, restoration, and `thpm doctor cava --fix` now form one guarded workflow.
- **Support reports:** `thpm report [plugin]` produces privacy-preserving diagnostics for remote troubleshooting.
- **Persistent Pi theme reload:** long-lived sessions using `omarchy-system` can repaint after Omarchy theme changes.
- **One latest-release installer:** the same curl command always resolves the newest published THPM release, including release candidates.

## Install or upgrade

```sh
curl -fsSL https://raw.githubusercontent.com/OldJobobo/thpm/main/scripts/install-arch-release.sh | bash
```

The installer verifies the latest release archive, builds it with `makepkg`, installs it through pacman, and completes THPM’s user setup.

https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc18
