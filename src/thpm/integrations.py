from __future__ import annotations

import json
import re
import shutil
import subprocess
import tomllib
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
ZELLIJ_THEME_DECLARATION = re.compile(
    r'(?m)^(?P<prefix>[ \t]*themes[ \t]*\{\s*)(?P<name>"(?:\\.|[^"\\])*"|[^\s{}]+)(?P<suffix>[ \t]*\{)'
)


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
    profile_root = base.resolve()
    profile_path = (base / profile).resolve()
    if profile_path == profile_root or profile_root not in profile_path.parents:
        raise ValueError(f"browser profile escapes its profile root: {profile}")
    chrome = profile_path / "chrome"
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


def _install_zellij_theme(source: Path, target: Path) -> None:
    content = source.read_text()
    if not ZELLIJ_THEME_DECLARATION.search(content):
        raise ValueError(f"Zellij theme has no theme declaration: {source}")
    normalized = ZELLIJ_THEME_DECLARATION.sub(
        lambda match: f'{match.group("prefix")}thpm-current{match.group("suffix")}',
        content,
        count=1,
    )
    atomic_text(target, normalized)


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
        "spotify": config / "spicetify/Themes/omarchy/color.ini",
        "superfile": config / "superfile/theme/thpm.toml",
        "vicinae": config / "vicinae/themes/thpm.toml",
        "zellij": config / "zellij/themes/thpm.kdl",
        "nwg-dock": config / "nwg-dock-hyprland/thpm.css",
        "cava": config / "cava/themes/thpm",
        "hermes": config / "Hermes/omarchy-theme.json",
        "qutebrowser": config / "qutebrowser/thpm_theme.py",
        "heroic": config / "heroic/themes/thpm.css",
    }
    if plugin_id == "zellij":
        source = paths.current_theme / "zellij.kdl"
        if not source.is_file():
            source = generated
        if not source.is_file():
            return changed
        _install_zellij_theme(source, targets[plugin_id])
        changed.append(str(targets[plugin_id]))
        config_file = _select_zellij_theme(paths)
        changed.append(str(config_file))
    elif plugin_id in targets and generated.is_file():
        atomic_copy(generated, targets[plugin_id])
        changed.append(str(targets[plugin_id]))
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
    elif plugin_id == "firefox":
        _browser_import(paths, plugin_id, home / ".mozilla/firefox")
    elif plugin_id == "zen":
        _browser_import(paths, plugin_id, home / ".zen")
    elif plugin_id == "steam":
        steam_theme = home / ".local/share/steam-adwaita/adwaita/colorthemes/omarchy/omarchy.css"
        script = home / ".local/share/steam-adwaita/install.py"
        if script.is_file():
            try:
                raw = tomllib.loads((paths.current_theme / "colors.toml").read_text())
            except (OSError, tomllib.TOMLDecodeError):
                raw = {}
            if raw:
                def _rgb(h):
                    c = h.lstrip('#')
                    if len(c) == 6:
                        return "{},{},{}".format(int(c[0:2],16), int(c[2:4],16), int(c[4:6],16))
                    return "0,0,0"
                bg = _rgb(raw.get('background', raw.get('bg', '#000000')))
                fg = _rgb(raw.get('foreground', raw.get('fg', '#ffffff')))
                accent = _rgb(raw.get('accent', raw.get('blue', '#3584e4')))
                red = _rgb(raw.get('red', raw.get('color1', '#e6194b')))
                green = _rgb(raw.get('green', raw.get('color2', '#3cb44b')))
                yellow = _rgb(raw.get('yellow', raw.get('color3', '#ffe119')))
                muted = _rgb(raw.get('muted', raw.get('color8', '#666666')))
                darker_bg = _rgb(raw.get('darker_bg', raw.get('color0', '#111111')))
                fg_on_bg = _rgb(raw.get('selection_foreground', bg))
                steam_theme.parent.mkdir(parents=True, exist_ok=True)
                steam_theme.write_text(
                    '/* Generated by THPM from the active Omarchy theme */\n'
                    ':root {\n'
                    '    --adw-accent-bg-rgb: ' + accent + ' !important;\n'
                    '    --adw-accent-fg-rgb: ' + fg_on_bg + ' !important;\n'
                    '    --adw-accent-rgb: ' + accent + ' !important;\n'
                    '    --adw-destructive-bg-rgb: ' + red + ' !important;\n'
                    '    --adw-destructive-fg-rgb: ' + fg + ' !important;\n'
                    '    --adw-destructive-rgb: ' + red + ' !important;\n'
                    '    --adw-success-bg-rgb: ' + green + ' !important;\n'
                    '    --adw-success-fg-rgb: ' + fg_on_bg + ' !important;\n'
                    '    --adw-success-rgb: ' + green + ' !important;\n'
                    '    --adw-warning-bg-rgb: ' + yellow + ' !important;\n'
                    '    --adw-warning-fg-rgb: ' + fg_on_bg + ' !important;\n'
                    '    --adw-warning-rgb: ' + yellow + ' !important;\n'
                    '    --adw-error-bg-rgb: ' + red + ' !important;\n'
                    '    --adw-error-fg-rgb: ' + fg_on_bg + ' !important;\n'
                    '    --adw-error-rgb: ' + red + ' !important;\n'
                    '    --adw-window-bg-rgb: ' + bg + ' !important;\n'
                    '    --adw-window-fg-rgb: ' + fg + ' !important;\n'
                    '    --adw-view-bg-rgb: ' + bg + ' !important;\n'
                    '    --adw-view-fg-rgb: ' + fg + ' !important;\n'
                    '    --adw-headerbar-bg-rgb: ' + bg + ' !important;\n'
                    '    --adw-headerbar-fg-rgb: ' + fg + ' !important;\n'
                    '    --adw-headerbar-border-rgb: ' + muted + ' !important;\n'
                    '    --adw-headerbar-backdrop-rgb: ' + bg + ' !important;\n'
                    '    --adw-headerbar-shade-rgb: 0, 0, 0 !important;\n'
                    '    --adw-headerbar-shade-a: 0.36 !important;\n'
                    '    --adw-sidebar-bg-rgb: ' + bg + ' !important;\n'
                    '    --adw-sidebar-fg-rgb: ' + fg + ' !important;\n'
                    '    --adw-sidebar-backdrop-rgb: ' + bg + ' !important;\n'
                    '    --adw-sidebar-shade-rgb: 0, 0, 0 !important;\n'
                    '    --adw-sidebar-shade-a: 0.36 !important;\n'
                    '    --adw-secondary-sidebar-bg-rgb: ' + darker_bg + ' !important;\n'
                    '    --adw-secondary-sidebar-fg-rgb: ' + fg + ' !important;\n'
                    '    --adw-card-bg-rgb: 255, 255, 255 !important;\n'
                    '    --adw-card-bg-a: 0.08 !important;\n'
                    '    --adw-card-fg-rgb: 255, 255, 255 !important;\n'
                    '    --adw-dialog-bg-rgb: ' + bg + ' !important;\n'
                    '    --adw-dialog-fg-rgb: ' + fg + ' !important;\n'
                    '    --adw-popover-bg-rgb: ' + bg + ' !important;\n'
                    '    --adw-popover-fg-rgb: ' + fg + ' !important;\n'
                    '    --adw-thumbnail-bg-rgb: ' + bg + ' !important;\n'
                    '    --adw-shade-rgb: 0, 0, 0 !important;\n'
                    '    --adw-shade-a: 0.36 !important;\n'
                    '}\n'
                )
                changed.append(str(steam_theme))
            try:
                completed = subprocess.run(
                    [str(script), "--color-theme", "omarchy"],
                    cwd=script.parent,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if completed.returncode != 0:
                    raise RuntimeError(f"steam-adwaita failed: {completed.stderr.strip() or completed.stdout.strip()}")
            except subprocess.TimeoutExpired:
                raise RuntimeError("steam-adwaita timed out")
    elif plugin_id == "cliamp":
        target = config / "cliamp/themes/omarchy.toml"
        if _copy_first(paths, ("cliamp.toml",), target): changed.append(str(target))
    elif plugin_id == "zed-extra":
        target = config / "zed/themes/omarchy.json"
        source = paths.current_theme / "aether.zed.json"
        if not source.is_file():
            source = paths.current_theme / "zed.json"
        if source.is_file():
            try:
                theme = json.loads(source.read_text())
                theme['name'] = 'Omarchy'
                for t in theme.get('themes', []):
                    t['name'] = 'Omarchy'
                atomic_text(target, json.dumps(theme, indent=2))
                changed.append(str(target))
            except (OSError, ValueError) as exc:
                raise RuntimeError(f"zed theme copy failed: {exc}")
        else:
            raw = tomllib.loads((paths.current_theme / "colors.toml").read_text())
            def _s(k, d=""): return str(raw.get(k, d)).lstrip("#")
            if "background" in raw:
                _bg, _fg = _s("background"), _s("foreground")
                _c0, _c8 = _s("color0"), _s("color8")
                _a = [_s(f"color{i}") for i in range(16)]
            else:
                _bg, _fg = _s("bg"), _s("fg")
                _c0 = _s("darker_bg", _bg)
                _c8 = _s("lighter_bg", _s("muted"))
                _a = [
                    _s("darker_bg", _bg), _s("red"), _s("green"),
                    _s("yellow"), _s("blue"), _s("magenta"),
                    _s("cyan"), _s("light_fg", _fg),
                    _c8, _s("bright_red"), _s("bright_green"),
                    _s("bright_yellow"), _s("bright_blue"),
                    _s("bright_magenta"), _s("bright_cyan"),
                    _s("bright_fg", _fg)
                ]
            def _h(v, a=""): return f"#{v}{a}"
            tpl = {
                "$schema": "https://zed.dev/schema/themes/v0.1.0.json",
                "name": "Omarchy", "author": "@bypass_", "themes": [{
                    "name": "Omarchy", "appearance": "dark", "style": {
                        "background": _h(_bg,"90"),
                        "editor.background": _h(_bg,"90"),
                        "editor.foreground": _h(_fg),
                        "text": _h(_fg),
                        "text.muted": _h(_fg,"70"),
                        "text.ignored": _h(_fg,"40"),
                        "text.placeholder": _h(_fg,"50"),
                        "ignored": _h(_fg,"30"),
                        "element.hover": _h(_fg,"30"),
                        "ghost_element.hover": _h(_c8,"30"),
                        "ghost_element.selected": _h(_c8,"30"),
                        "ghost_element.active": _h(_c8,"60"),
                        "border": _h(_c0),
                        "editor.highlighted_line.background": _h(_c8,"10"),
                        "editor.active_line.background": _h(_c8,"10"),
                        "panel.background": _h(_c0,"90"),
                        "title_bar.background": _h(_c0,"90"),
                        "title_bar.inactive_background": _h(_c0,"90"),
                        "status_bar.background": _h(_c0,"90"),
                        "drop_target.background": _h(_c0,"90"),
                        "elevated_surface.background": _h(_c0),
                        "toolbar.background": _h(_c0,"90"),
                        "tab_bar.background": _h(_c0,"90"),
                        "tab.inactive_background": _h(_c0,"90"),
                        "tab.active_background": _h(_c8,"30"),
                        "scrollbar.track.background": "transparent",
                        "scrollbar.track.border": _h(_c0),
                        "scrollbar.thumb.background": _h(_fg),
                        "editor.gutter.background": _h(_c0,"90"),
                        "terminal.background": _h(_c0,"10"),
                        "terminal.foreground": _h(_fg),
                        "terminal.dim_foreground": _h(_fg),
                        "terminal.bright_foreground": _h(_fg),
                        "terminal.ansi.black": _h(_a[0]),
                        "terminal.ansi.red": _h(_a[1]),
                        "terminal.ansi.green": _h(_a[2]),
                        "terminal.ansi.yellow": _h(_a[3]),
                        "terminal.ansi.blue": _h(_a[4]),
                        "terminal.ansi.magenta": _h(_a[5]),
                        "terminal.ansi.cyan": _h(_a[6]),
                        "terminal.ansi.white": _h(_a[7]),
                        "terminal.ansi.bright_black": _h(_a[8]),
                        "terminal.ansi.bright_red": _h(_a[9]),
                        "terminal.ansi.bright_green": _h(_a[10]),
                        "terminal.ansi.bright_yellow": _h(_a[11]),
                        "terminal.ansi.bright_blue": _h(_a[12]),
                        "terminal.ansi.bright_magenta": _h(_a[13]),
                        "terminal.ansi.bright_cyan": _h(_a[14]),
                        "terminal.ansi.bright_white": _h(_a[15]),
                        "modified": _h(_a[1]),
                        "syntax": {
                            "attribute": {"color": _h(_a[7])},
                            "boolean": {"color": _h(_a[2])},
                            "comment": {"color": _h(_c8)},
                            "comment.doc": {"color": _h(_c8)},
                            "constant": {"color": _h(_a[10])},
                            "function": {"color": _h(_a[14])},
                            "keyword": {"color": _h(_a[4])},
                            "number": {"color": _h(_a[5])},
                            "operator": {"color": _h(_a[4])},
                            "string": {"color": _h(_a[1])},
                            "variable": {"color": _h(_a[2])}
                        },
                        "players": [{
                            "cursor": _h(_fg),
                            "background": _h(_c0),
                            "selection": _h(_fg,"30")
                        }]
                    }
                }]
            }
            atomic_text(target, json.dumps(tpl, indent=2))
            changed.append(str(target))
    _reload(plugin_id)
    return changed


def _reload(plugin_id: str) -> None:
    commands = {
        "spotify": ["spicetify", "apply"], "vicinae": ["vicinae", "theme", "set", "thpm"],
        "swaync": ["swaync-client", "--reload-css"], "cava": ["pkill", "-USR2", "cava"],
    }
    command = commands.get(plugin_id)
    if command and shutil.which(command[0]):
        try:
            subprocess.run(
                command,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            pass


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
