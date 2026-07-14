from __future__ import annotations

from .models import Plugin

PLUGINS: tuple[Plugin, ...] = (
    Plugin("fish", "Fish", "Terminal", "Synchronize Fish shell colors.", "hybrid", ("fish",), templates=("thpm-fish.fish.tpl",)),
    Plugin("fzf", "fzf", "Terminal", "Provide an Omarchy-colored fzf palette.", "hybrid", ("fzf",), templates=("thpm-fzf.fish.tpl",)),
    Plugin("branding", "Branding extras", "Desktop", "Synchronize optional theme branding text.", "action", theme_assets=("about.txt", "screensaver.txt"), default_enabled=False),
    Plugin("discord", "Discord / Vencord", "Messaging", "Install a theme-provided or generated Vencord theme.", "hybrid", theme_assets=("vencord.theme.css",), templates=("thpm-vencord.theme.css.tpl",)),
    Plugin("discord-system24", "Discord System24", "Messaging", "Install the System24-flavored Vencord surface.", "hybrid", theme_assets=("vencord-system24.theme.css",), templates=("thpm-vencord-system24.theme.css.tpl",), default_enabled=False),
    Plugin("qt6ct", "Qt6ct", "Desktop", "Generate a Qt6 color scheme.", "hybrid", ("qt6ct",), templates=("thpm-qt6ct.conf.tpl",)),
    Plugin("spotify", "Spotify / Spicetify", "Media", "Update Spicetify colors and apply them.", "hybrid", ("spicetify",), templates=("thpm-spicetify.ini.tpl",)),
    Plugin("superfile", "Superfile", "Terminal", "Install a semantic Superfile theme.", "hybrid", ("spf",), theme_assets=("superfile.toml",), templates=("thpm-superfile.toml.tpl",)),
    Plugin("vicinae", "Vicinae", "Desktop", "Install and select an Omarchy Vicinae theme.", "hybrid", ("vicinae",), templates=("thpm-vicinae.toml.tpl",)),
    Plugin("zellij", "Zellij", "Terminal", "Manage a current Zellij theme block.", "hybrid", ("zellij",), theme_assets=("zellij.kdl",), templates=("thpm-zellij.kdl.tpl",), default_enabled=False),
    Plugin("typora", "Typora", "Writing", "Install Typora theme CSS.", "apply", ("typora",), theme_assets=("typora.css",)),
    Plugin("nwg-dock", "nwg-dock-hyprland", "Desktop", "Retint and reload the dock.", "hybrid", ("nwg-dock-hyprland",), templates=("thpm-nwg-dock.css.tpl",)),
    Plugin("zed-extra", "Zed extras", "Editors", "Apply only Zed behavior not provided by Omarchy.", "apply", ("zeditor",), theme_assets=("zed.json",), default_enabled=False),
    Plugin("swaync", "SwayNC", "Desktop", "Install SwayNC theme files and reload.", "apply", ("swaync-client",), theme_assets=("colors.css",)),
    Plugin("windsurf", "Windsurf", "Editors", "Install the generated Omarchy editor theme.", "apply", ("windsurf",), theme_assets=("vscode-theme.json",)),
    Plugin("obsidian-terminal", "Obsidian Terminal", "Editors", "Synchronize Obsidian Terminal plugin colors.", "apply", ("python3",)),
    Plugin("cava", "Cava", "Media", "Install and reload a Cava gradient.", "hybrid", ("cava",), theme_assets=("cava_theme",), templates=("thpm-cava.ini.tpl",)),
    Plugin("firefox", "Firefox", "Browsers", "Manage Firefox userChrome imports and generated CSS.", "hybrid", ("firefox",), theme_assets=("firefox.css",), templates=("thpm-firefox.css.tpl",), confirmation=True),
    Plugin("zen", "Zen Browser", "Browsers", "Manage Zen userChrome imports and generated CSS.", "hybrid", ("zen-browser",), theme_assets=("zen.css",), templates=("thpm-zen.css.tpl",), confirmation=True),
    Plugin("hermes", "Hermes", "Editors", "Generate the Hermes Omarchy theme descriptor.", "hybrid", ("Hermes",), templates=("thpm-hermes.json.tpl",)),
    Plugin("qutebrowser", "Qutebrowser", "Browsers", "Install generated Qutebrowser colors.", "hybrid", ("qutebrowser",), templates=("thpm-qutebrowser.py.tpl",)),
    Plugin("steam", "Steam", "Games", "Apply a theme through steam-adwaita.", "apply", ("steam", "python"), theme_assets=("steam.css",), confirmation=True),
    Plugin("heroic", "Heroic", "Games", "Install a Heroic theme stylesheet.", "hybrid", ("heroic",), templates=("thpm-heroic.css.tpl",)),
    Plugin("cliamp", "cliamp", "Media", "Use an opted-in native cliamp theme or ANSI fallback.", "apply", ("cliamp",), theme_assets=("cliamp.toml",)),
)

NATIVE: tuple[Plugin, ...] = (
    Plugin("native-foot", "Foot live colors", "Native", "Owned by Omarchy 4.", "action", native=True),
    Plugin("native-tmux", "tmux synchronization", "Native", "Owned by Omarchy 4.", "action", native=True),
    Plugin("native-gnome", "GNOME mode and icons", "Native", "Owned by Omarchy 4.", "action", native=True),
    Plugin("native-vscode", "VS Code and Cursor", "Native", "Owned by Omarchy 4.", "action", native=True),
    Plugin("native-obsidian", "Obsidian theme", "Native", "Owned by Omarchy 4.", "action", native=True),
    Plugin("native-keyboard", "Keyboard theming", "Native", "Owned by Omarchy 4.", "action", native=True),
)

BY_ID = {plugin.id: plugin for plugin in PLUGINS}
