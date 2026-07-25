## THPM 1.0.0rc11 is now available

**THPM is built exclusively for Omarchy Quattro and supports Omarchy 4.x only.**

### Install or upgrade through Omarchy

```sh
omarchy pkg aur add thpm   # first installation
omarchy update aur pkgs    # update an installed AUR package
```

### Clean terminal ownership during AUR updates

THPM now suspends its Rich live progress display while Yay owns the terminal. Package build output is no longer interleaved with a stale spinner, and sudo password prompts remain visible and usable.

After Yay and reconciliation finish, THPM resumes its own completion output normally. Non-TTY callers retain the Omarchy terminal fallback.

### Special thanks

Special thanks to our beta testers: @HANCORE, @sodipops, @gnugent, and @signal//directive.

This remains a release candidate. Please report update-flow or integration issues before the final 1.0.0 release.

[View the release](https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc11)
