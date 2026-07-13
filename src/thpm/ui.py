from __future__ import annotations

import shutil
from pathlib import Path

from .files import atomic_copy, atomic_text, remove_managed_block
from .omarchy import run, shell_running
from .paths import Paths
from .resources import asset

START = "// thpm-menu-start"
END = "// thpm-menu-end"
ENTRY = '  "style.theme-hooks": {"icon":"󰏘","label":"Theme Hook Plugins","keywords":"thpm plugins integrations","action":"omarchy shell shell summon io.github.oldjobobo.thpm \'{}\'"},'


def install(paths: Paths) -> dict[str, object]:
    source = asset("qml")
    if not source.is_dir():
        raise FileNotFoundError("packaged QML plugin is missing")
    paths.shell_plugin_dir.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.is_file(): atomic_copy(item, paths.shell_plugin_dir / item.name)
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
    atomic_text(menu, f"{body}\n{START}\n{ENTRY}\n{END}\n}}\n")
    if shell_running():
        run("plugin", "rescan", check=False)
        run("plugin", "enable", "io.github.oldjobobo.thpm", check=False)
        run("menu", "refresh", check=False)
    return {"installed": True, "path": str(paths.shell_plugin_dir), "menu": str(menu)}


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
    return {"installed": paths.shell_plugin_dir.is_dir(), "menuEntry": START in paths.menu_extension.read_text() if paths.menu_extension.exists() else False, "shellRunning": shell_running()}
