## THPM 1.0.0rc6 is now available

**THPM is built exclusively for Omarchy Quattro and supports Omarchy 4.x only.**

### Install or upgrade through AUR

```sh
omarchy pkg aur add thpm
```

Users on rc4 or rc5 can upgrade directly with:

```sh
yay -S thpm
```

Source-install users on rc5 must use the old explicit form once:

```sh
thpm update apply
```

### Fixed

Bare `thpm update` now does exactly what it says: it checks for and applies the available update. The more specific `thpm update check`, `thpm update status`, and `thpm update apply` commands remain available for scripted and UI workflows, but they are no longer required for normal command-line use.

Regression coverage now verifies both the bare update path and explicit update checks.

### Special thanks

Special thanks to our beta testers: @HANCORE, @sodipops, @gnugent, and @signal//directive.

This remains a release candidate. Please report update or integration issues before the final 1.0.0 release.

[View the release](https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc6)
