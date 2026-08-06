## THPM 1.0.0rc18 is now available

**THPM is made for Omarchy Quattro and supports Omarchy 4.x.**

### Install or upgrade the latest release

```sh
curl -fsSL https://raw.githubusercontent.com/OldJobobo/thpm/main/scripts/install-arch-release.sh | bash
```

The installer now resolves the newest published GitHub release, including release candidates. It downloads the matching source archive and checksum, verifies them, builds the Arch package with `makepkg`, installs it through pacman, and completes THPM's per-user setup.

## What’s new in rc18

### Spotify setup now repairs itself

Once Spicetify has a current backup, enabling Spotify in THPM creates the missing Omarchy companion stylesheet, installs the generated color scheme, and selects `current_theme = omarchy` with `color_scheme = Base`. Doctor treats a different active Spicetify theme as repairable setup instead of leaving the integration unavailable. Existing custom `user.css` files remain untouched.

### Cava is safer and explicitly opt-in

Cava setup now verifies version 0.10.6 or newer, safely selects and restores the managed theme, reloads only verified Cava processes, and offers transactional repair through `thpm doctor cava --fix`.

### Better support diagnostics

`thpm report [plugin]` creates a bounded, privacy-preserving JSON support report with integration outcomes, durations, redacted configuration evidence, and recent operation history.

### Persistent Pi sessions repaint correctly

The opt-in Pi compatibility integration emits a safe metadata-only reload event when Omarchy's generated Pi theme is current, allowing long-lived sessions using `omarchy-system` to repaint.

### Verification

The rc18 release passes the complete automated suite: 312 tests and 58 subtests.

This remains a release candidate. Please report any issues you find.

[View the release](https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc18)
