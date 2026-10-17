## THPM 1.0.0 is now available

**THPM 1.0.0 is the first stable release. It manages theme integrations for applications that Omarchy does not theme itself, keeps each integration opt-in, and puts your own files back when you turn an integration off.**

### Install or upgrade

```sh
omarchy pkg aur add thpm
thpm install
```

Or install from the verified release sources:

```sh
curl -fsSL https://raw.githubusercontent.com/OldJobobo/thpm/main/scripts/install-arch-release.sh | bash
```

## What’s new since rc24

### New Experimental integrations

- **Nautilus** palette, with a hot-reloading extension; it requires `nautilus-python`.
- **GNOME accent** compatibility, which maps the theme accent to libadwaita's named accents and restores your previous accent.
- **Thunderbird**, theming both the window chrome and the message views.
- **Hermes Desktop** local palette, offered as **Local Omarchy** in Desktop Appearance.

### Fixes and improvements

- Firefox and Zen pick the profile of the installation that is actually present, find profiles under `$XDG_CONFIG_HOME`, and theme more of Firefox's chrome: the URL bar, panels, sidebar and tabs.
- Zed's installed **THPM Current** theme fills in missing diagnostic colors, so warning and error popups stay readable.
- Steam's Omarchy palette no longer goes stale after a theme change.
- A theme change no longer hangs in a terminal when a running Cava reads its config from standard input.
- THPM's old Hermes JSON writer is retired in favor of Omarchy's native Hermes skins.

### Support status

Every integration is disabled until you enable it. An integration is **Supported** once it has automated lifecycle tests and a recorded check against the real application. fzf, Zellij, Discord / Vencord, and Pi live reload are Supported. The others are labeled **Experimental** but keep the same guarantees for your files on disable and uninstall. See the [integration support register](https://github.com/OldJobobo/thpm/blob/main/docs/integration-support.md).

Please report any application that stops following your theme.

[View the release](https://github.com/OldJobobo/thpm/releases/tag/v1.0.0)
