from __future__ import annotations

import shutil

from .files import atomic_text, remove_managed_block
from .omarchy import run, shell_running
from .paths import Paths
from .registry import PLUGINS

START = "// thpm-menu-start"
END = "// thpm-menu-end"


def _entries() -> str:
    lines = ['  "style.theme-hooks": {"icon":"󰏘","label":"Theme Hook Plugins","keywords":"thpm plugins integrations"},']
    categories: list[str] = []
    for plugin in PLUGINS:
        slug = plugin.category.lower().replace(" ", "-")
        if slug not in categories:
            categories.append(slug)
            lines.append(f'  "style.theme-hooks.{slug}": {{"icon":"›","label":"{plugin.category}"}},')
        action = f"thpm plugin toggle {plugin.id} && omarchy menu summon style.theme-hooks.{slug}"
        checked = f"thpm plugin enabled {plugin.id}"
        lines.append(
            f'  "style.theme-hooks.{slug}.{plugin.id}": '
            f'{{"icon":"·","label":"{plugin.label}","description":"{plugin.description}",'
            f'"keywords":"{plugin.id} {plugin.category.lower()}","checked":"{checked}","action":"{action}"}},'
        )
    return "\n".join(lines)


def install(paths: Paths) -> dict[str, object]:
    running = shell_running()
    if running and paths.shell_plugin_dir.is_dir():
        run("plugin", "disable", "io.github.oldjobobo.thpm", check=False)
    shutil.rmtree(paths.shell_plugin_dir, ignore_errors=True)
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
    atomic_text(menu, f"{body}\n{START}\n{_entries()}\n{END}\n}}\n")
    if running:
        run("plugin", "rescan", check=False)
        run("menu", "refresh", check=False)
    return {"installed": True, "surface": "omarchy.menu", "menu": str(menu)}


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
    menu_entry = START in paths.menu_extension.read_text() if paths.menu_extension.exists() else False
    return {"installed": menu_entry, "menuEntry": menu_entry, "surface": "omarchy.menu", "shellRunning": shell_running()}
