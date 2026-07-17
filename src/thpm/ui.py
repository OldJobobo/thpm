from __future__ import annotations

import shutil
import tomllib

from .files import atomic_copy, atomic_text, remove_managed_block
from .omarchy import run, shell_running
from .paths import Paths
from .resources import asset

START = "// thpm-menu-start"
END = "// thpm-menu-end"
SURFACES = ("gui", "tui")
ENTRIES = {
    "gui": '  "style.theme-hooks": {"icon":"󰏘","label":"Theme Hook Plugins","keywords":"thpm plugins integrations gui qml","action":"omarchy shell shell summon io.github.oldjobobo.thpm \'{}\'"},',
    "tui": '  "style.theme-hooks": {"icon":"󰆍","label":"Theme Hook Plugins","keywords":"thpm plugins integrations terminal tui","action":"omarchy-launch-floating-terminal-with-presentation \'thpm tui\'"},',
}


def _surface(paths: Paths) -> str:
    try:
        value = tomllib.loads(paths.ui_state_file.read_text()).get("menu_surface")
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        value = None
    return str(value) if value in SURFACES else "gui"


def _write_menu(paths: Paths, surface: str) -> None:
    menu = paths.menu_extension
    text = menu.read_text() if menu.exists() else "{}\n"
    if START in text or END in text:
        text = remove_managed_block(text, START, END)
    stripped = text.strip()
    if not stripped.startswith("{") or not stripped.endswith("}"):
        raise ValueError("Omarchy menu extension is not a top-level JSONC object")
    body = stripped[:-1].rstrip()
    if body != "{" and not body.endswith(","):
        body += ","
    atomic_text(menu, f"{body}\n{START}\n{ENTRIES[surface]}\n{END}\n}}\n")


def surface(paths: Paths, requested: str | None = None) -> dict[str, object]:
    current = _surface(paths)
    if requested is None:
        return {"surface": current, "changed": False}
    selected = ("tui" if current == "gui" else "gui") if requested == "toggle" else requested
    if selected not in SURFACES:
        raise ValueError(f"unknown UI surface: {requested}")
    atomic_text(paths.ui_state_file, f'menu_surface = "{selected}"\n')
    _write_menu(paths, selected)
    if shell_running():
        run("menu", "refresh", check=False)
    return {"surface": selected, "changed": selected != current}


def install(paths: Paths) -> dict[str, object]:
    source = asset("qml")
    if not source.is_dir():
        raise FileNotFoundError("packaged QML plugin is missing")
    paths.shell_plugin_dir.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.is_file():
            target_name = "Panel.qml" if item.name == "Panel.qml.in" else item.name
            atomic_copy(item, paths.shell_plugin_dir / target_name)
    selected = _surface(paths)
    _write_menu(paths, selected)
    if shell_running():
        run("plugin", "rescan", check=False)
        run("plugin", "enable", "io.github.oldjobobo.thpm", check=False)
        run("menu", "refresh", check=False)
    return {"installed": True, "path": str(paths.shell_plugin_dir), "menu": str(paths.menu_extension), "menuSurface": selected}


def remove(paths: Paths) -> dict[str, object]:
    if shell_running(): run("plugin", "disable", "io.github.oldjobobo.thpm", check=False)
    shutil.rmtree(paths.shell_plugin_dir, ignore_errors=True)
    if paths.menu_extension.exists():
        cleaned = remove_managed_block(paths.menu_extension.read_text(), START, END)
        atomic_text(paths.menu_extension, cleaned)
    if shell_running():
        run("plugin", "rescan", check=False)
        run("menu", "refresh", check=False)
    return {"installed": False}


def status(paths: Paths) -> dict[str, object]:
    return {"installed": paths.shell_plugin_dir.is_dir(), "menuEntry": START in paths.menu_extension.read_text() if paths.menu_extension.exists() else False, "menuSurface": _surface(paths), "shellRunning": shell_running()}
