## THPM 1.0.0rc8 is now available

**THPM is built exclusively for Omarchy Quattro and supports Omarchy 4.x only.**

### Install or upgrade through Omarchy

```sh
omarchy pkg aur add thpm   # first installation
omarchy update aur pkgs    # update an installed AUR package
```

### Detailed by default

The rc7 progress surface is now fully verbose by default. Normal commands show:

- Animated spinner and real stage-based progress bar.
- Elapsed time and current phase.
- Live stage logs.
- Changed paths and captured command output.
- Structured completion cards, result tables, warnings, and errors.

No extra flag is required:

```sh
thpm update
thpm run
thpm reconcile --refresh
```

Use compact mode only when you specifically want less output:

```sh
thpm update --quiet
```

`--verbose` / `-v` remains accepted as an explicit alias for the default detailed mode. Redirected output remains non-animated, `NO_COLOR=1` disables ANSI color, and `--json` remains stable and decoration-free.

### Special thanks

Special thanks to our beta testers: @HANCORE, @sodipops, @gnugent, and @signal//directive.

This remains a release candidate. Please report command-output or integration issues before the final 1.0.0 release.

[View the release](https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc8)
