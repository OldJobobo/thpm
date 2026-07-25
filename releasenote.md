## THPM 1.0.0rc9 is now available

**THPM is built exclusively for Omarchy Quattro and supports Omarchy 4.x only.**

### Install or upgrade through Omarchy

```sh
omarchy pkg aur add thpm   # first installation
omarchy update aur pkgs    # update an installed AUR package
```

### AUR updates stay in your terminal

Running `thpm update` from a terminal now keeps the complete upgrade in that terminal instead of opening a separate floating Omarchy window.

THPM invokes Yay with routine package-manager confirmations disabled, displays the upgrade output in place, and reconciles integrations after the package is installed. Password authentication can still appear normally when required by the system.

Callers without a TTY, including graphical surfaces, retain the Omarchy terminal fallback so authentication and package output remain visible.

### Special thanks

Special thanks to our beta testers: @HANCORE, @sodipops, @gnugent, and @signal//directive.

This remains a release candidate. Please report update-flow or integration issues before the final 1.0.0 release.

[View the release](https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc9)
