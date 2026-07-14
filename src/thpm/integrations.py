from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .files import atomic_copy, atomic_text, remove_managed_block
from .paths import Paths
from .registry import BY_ID, PLUGINS

GENERATED = {
    "fish": "thpm-fish.fish", "fzf": "thpm-fzf.fish", "discord": "thpm-vencord.theme.css",
    "discord-system24": "thpm-vencord-system24.theme.css",
    "qt6ct": "thpm-qt6ct.conf", "spotify": "thpm-spicetify.ini", "superfile": "thpm-superfile.toml",
    "vicinae": "thpm-vicinae.toml", "zellij": "thpm-zellij.kdl", "nwg-dock": "thpm-nwg-dock.css",
    "cava": "thpm-cava.ini", "firefox": "thpm-firefox.css", "zen": "thpm-zen.css",
    "hermes": "thpm-hermes.json", "qutebrowser": "thpm-qutebrowser.py", "heroic": "thpm-heroic.css",
}

ZELLIJ_MANAGED_START = "// thpm-zellij-theme-start"
ZELLIJ_MANAGED_END = "// thpm-zellij-theme-end"


def _copy_first(paths: Paths, candidates: tuple[str, ...], target: Path) -> bool:
    for name in candidates:
        source = paths.current_theme / name
        if source.is_file():
            atomic_copy(source, target)
            return True
    return False


def _browser_import(paths: Paths, plugin_id: str, base: Path) -> None:
    generated = paths.current_theme / GENERATED[plugin_id]
    if not generated.is_file():
        return
    profiles = base / "profiles.ini"
    if not profiles.is_file():
        return
    profile = ""
    in_install = False
    for raw in profiles.read_text().splitlines():
        if raw.startswith("[Install"):
            in_install = True
        elif raw.startswith("["):
            in_install = False
        elif in_install and raw.startswith("Default="):
            profile = raw.split("=", 1)[1]
            break
    if not profile:
        return
    chrome = base / profile / "chrome"
    managed = chrome / f"thpm-{plugin_id}.css"
    atomic_copy(generated, managed)
    user_chrome = chrome / "userChrome.css"
    start, end = "/* thpm-import-start */", "/* thpm-import-end */"
    existing = user_chrome.read_text() if user_chrome.exists() else ""
    existing = remove_managed_block(existing, start, end) if start in existing or end in existing else existing
    block = f'{start}\n@import url("{managed.name}");\n{end}\n'
    atomic_text(user_chrome, block + existing.lstrip())


def _select_zellij_theme(paths: Paths) -> Path:
    config = paths.config_home / "zellij/config.kdl"
    existing = config.read_text() if config.is_file() else ""
    if ZELLIJ_MANAGED_START in existing or ZELLIJ_MANAGED_END in existing:
        existing = remove_managed_block(existing, ZELLIJ_MANAGED_START, ZELLIJ_MANAGED_END)
    theme = re.compile(r'^(?P<indent>\s*)theme\s+"[^"]*".*$', re.MULTILINE)
    if theme.search(existing):
        updated = theme.sub(lambda match: f'{match.group("indent")}theme "thpm-current"', existing, count=1)
    else:
        updated = 'theme "thpm-current"\n' + ("\n" + existing.lstrip() if existing.strip() else "")
    if not updated.endswith("\n"):
        updated += "\n"
    if updated != (config.read_text() if config.is_file() else ""):
        atomic_text(config, updated)
    return config


def apply(plugin_id: str, paths: Paths) -> list[str]:
    if plugin_id not in BY_ID:
        raise KeyError(plugin_id)
    paths.current_theme.mkdir(parents=True, exist_ok=True)
    changed: list[str] = []
    home, config = paths.home, paths.config_home
    generated = paths.current_theme / GENERATED.get(plugin_id, "")
    targets: dict[str, Path] = {
        "fish": config / "fish/conf.d/thpm-theme.fish",
        "fzf": config / "fish/conf.d/thpm-fzf.fish",
        "qt6ct": config / "qt6ct/colors/thpm.conf",
        "spotify": config / "spicetify/Themes/Omarchy/color.ini",
        "superfile": config / "superfile/theme/thpm.toml",
        "vicinae": config / "vicinae/themes/thpm.toml",
        "zellij": config / "zellij/themes/thpm.kdl",
        "nwg-dock": config / "nwg-dock-hyprland/thpm.css",
        "cava": config / "cava/themes/thpm",
        "hermes": config / "Hermes/omarchy-theme.json",
        "qutebrowser": config / "qutebrowser/thpm_theme.py",
        "heroic": config / "heroic/themes/thpm.css",
    }
    if plugin_id in targets and generated.is_file():
        atomic_copy(generated, targets[plugin_id])
        changed.append(str(targets[plugin_id]))
        if plugin_id == "zellij":
            config_file = _select_zellij_theme(paths)
            changed.append(str(config_file))
    elif plugin_id == "branding":
        for source_name, target_name in (("about.txt", "about.txt"), ("screensaver.txt", "screensaver.txt")):
            source = paths.current_theme / source_name
            if source.is_file():
                target = config / "omarchy/branding" / target_name
                atomic_copy(source, target)
                changed.append(str(target))
    elif plugin_id in {"discord", "discord-system24"}:
        source_names = (("vencord.theme.css", GENERATED[plugin_id]) if plugin_id == "discord"
            else ("vencord-system24.theme.css", GENERATED[plugin_id]))
        directories = (
            config / "Vencord/themes",
            config / "vesktop/themes",
            config / "Equicord/themes",
            config / "equibop/themes",
            home / ".var/app/com.discordapp.Discord/config/Vencord/themes",
            home / ".var/app/dev.vencord.Vesktop/config/vesktop/themes",
            home / ".var/app/io.github.equicord.equibop/config/equibop/themes",
        )
        for directory in directories:
            if directory.is_dir():
                target = directory / "vencord.theme.css"
                if _copy_first(paths, source_names, target):
                    changed.append(str(target))
    elif plugin_id == "typora":
        target = config / "Typora/themes/omarchy.css"
        if _copy_first(paths, ("typora.css",), target): changed.append(str(target))
    elif plugin_id == "swaync":
        target = config / "swaync/colors.css"
        if _copy_first(paths, ("colors.css",), target): changed.append(str(target))
    elif plugin_id == "windsurf":
        target = home / ".windsurf/extensions/local.omarchy-theme/themes/omarchy.json"
        if _copy_first(paths, ("vscode-theme.json",), target): changed.append(str(target))
    elif plugin_id == "obsidian-terminal":
        # Discovery and JSON preservation are deliberately handled by a dedicated adapter later.
        return changed
    elif plugin_id == "firefox":
        _browser_import(paths, plugin_id, home / ".mozilla/firefox")
    elif plugin_id == "zen":
        _browser_import(paths, plugin_id, home / ".zen")
    elif plugin_id == "steam":
        script = home / ".local/share/steam-adwaita/install.py"
        if script.is_file(): subprocess.run([str(script), "--color-theme", "omarchy"], cwd=script.parent, check=False)
    elif plugin_id == "cliamp":
        target = config / "cliamp/themes/omarchy.toml"
        if _copy_first(paths, ("cliamp.toml",), target): changed.append(str(target))
    elif plugin_id == "zed-extra":
        target = config / "zed/themes/omarchy.json"
        if _copy_first(paths, ("zed.json",), target): changed.append(str(target))
    _reload(plugin_id)
    return changed


def _reload(plugin_id: str) -> None:
    commands = {
        "spotify": ["spicetify", "apply"], "vicinae": ["vicinae", "theme", "set", "thpm"],
        "swaync": ["swaync-client", "--reload-css"], "cava": ["pkill", "-USR2", "cava"],
    }
    command = commands.get(plugin_id)
    if command and shutil.which(command[0]):
        subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def apply_enabled(paths: Paths, enabled: dict[str, bool]) -> dict[str, object]:
    results, errors = [], []
    for plugin in PLUGINS:
        if not enabled.get(plugin.id):
            continue
        try:
            results.append({"id": plugin.id, "changed": apply(plugin.id, paths)})
        except Exception as exc:  # isolate plugins at the hook boundary
            errors.append({"plugin": plugin.id, "message": str(exc)})
    return {"results": results, "errors": errors}
