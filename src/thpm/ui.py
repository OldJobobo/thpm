from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import tempfile
import time
import tomllib
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .files import atomic_text, remove_managed_block
from .omarchy import run, shell_running
from .paths import Paths
from .resources import asset

START = "// thpm-menu-start"
END = "// thpm-menu-end"
PLUGIN_ID = "io.github.oldjobobo.thpm"
SURFACES = ("gui", "tui")
ENTRIES = {
    "gui": '  "style.theme-hooks": {"icon":"󰏘","label":"Theme Hook Plugins","keywords":"thpm plugins integrations gui qml","action":"thpm ui open"},',
    "tui": '  "style.theme-hooks": {"icon":"󰆍","label":"Theme Hook Plugins","keywords":"thpm plugins integrations terminal tui","action":"omarchy-launch-floating-terminal-with-presentation \'thpm tui\'"},',
}


def _surface(paths: Paths) -> str:
    try:
        value = tomllib.loads(paths.ui_state_file.read_text()).get("menu_surface")
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        value = None
    return str(value) if value in SURFACES else "gui"


def _json_string_end(text: str, start: int) -> int:
    index = start + 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text[index] == '"':
            return index + 1
        else:
            index += 1
    raise ValueError("unterminated string in Omarchy menu extension")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _parse_jsonc(text: str) -> object:
    uncommented: list[str] = []
    index = 0
    while index < len(text):
        if text[index] == '"':
            end = _json_string_end(text, index)
            uncommented.append(text[index:end])
            index = end
        elif text.startswith("//", index):
            line_endings = (
                position
                for marker in ("\r", "\n")
                if (position := text.find(marker, index + 2)) >= 0
            )
            index = min(line_endings, default=len(text))
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                raise ValueError("unterminated comment in Omarchy menu extension")
            uncommented.append(" ")
            index = end + 2
        else:
            uncommented.append(text[index])
            index += 1
    cleaned = "".join(uncommented)
    output: list[str] = []
    index = 0
    while index < len(cleaned):
        if cleaned[index] == '"':
            end = _json_string_end(cleaned, index)
            output.append(cleaned[index:end])
            index = end
        elif cleaned[index] == ",":
            lookbehind = index - 1
            while lookbehind >= 0 and cleaned[lookbehind].isspace():
                lookbehind -= 1
            lookahead = index + 1
            while lookahead < len(cleaned) and cleaned[lookahead].isspace():
                lookahead += 1
            has_preceding_value = (
                lookbehind >= 0 and cleaned[lookbehind] not in "[{,:"
            )
            if (
                has_preceding_value
                and lookahead < len(cleaned)
                and cleaned[lookahead] in "}]"
            ):
                index += 1
                continue
            output.append(cleaned[index])
            index += 1
        else:
            output.append(cleaned[index])
            index += 1
    return json.loads("".join(output), parse_constant=_reject_json_constant)


def _menu_text(paths: Paths, surface: str) -> str:
    menu = paths.menu_extension
    text = menu.read_text() if menu.exists() else "{}\n"
    if START in text or END in text:
        text = remove_managed_block(text, START, END)
    stripped = text.strip()
    if not stripped.startswith("{") or not stripped.endswith("}"):
        raise ValueError("Omarchy menu extension is not a top-level JSONC object")
    body = stripped[1:-1].strip()
    # Insert first so our trailing comma remains syntactic even when another
    # managed block ends with a JSONC comment immediately before the root brace.
    managed = f"{START}\n{ENTRIES[surface]}\n{END}"
    suffix = f"\n{body}" if body else ""
    rendered = f"{{\n{managed}{suffix}\n}}\n"
    try:
        parsed = _parse_jsonc(rendered)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Omarchy menu extension is invalid JSONC: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Omarchy menu extension is not a top-level JSONC object")
    return rendered


def _write_menu(paths: Paths, surface: str) -> None:
    atomic_text(paths.menu_extension, _menu_text(paths, surface))


def _menu_current(paths: Paths) -> bool:
    try:
        text = paths.menu_extension.read_text()
    except OSError:
        return False
    return START in text and END in text and ENTRIES[_surface(paths)] in text


def _source_files() -> dict[str, Path]:
    source = asset("qml")
    if not source.is_dir():
        raise FileNotFoundError("packaged QML plugin is missing")
    return {
        "Panel.qml" if item.name == "Panel.qml.in" else item.name: item
        for item in source.iterdir()
        if item.is_file()
    }


def _deployment_current(paths: Paths) -> bool:
    expected = _source_files()
    try:
        actual = {item.name for item in paths.shell_plugin_dir.iterdir() if item.is_file()}
    except OSError:
        return False
    if actual != set(expected):
        return False
    try:
        return all(
            (paths.shell_plugin_dir / name).read_bytes() == source.read_bytes()
            for name, source in expected.items()
        )
    except OSError:
        return False


def _remove_tree(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def _deploy(paths: Paths) -> bool:
    """Stage a complete plugin tree and switch it into place as one generation."""
    if _deployment_current(paths):
        return False
    expected = _source_files()
    parent = paths.shell_plugin_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=f".{PLUGIN_ID}.staged-", dir=parent))
    displaced = parent / f".{PLUGIN_ID}.previous"
    try:
        for name, source in expected.items():
            shutil.copy2(source, staged / name)
        _remove_tree(displaced)
        if paths.shell_plugin_dir.exists() or paths.shell_plugin_dir.is_symlink():
            paths.shell_plugin_dir.rename(displaced)
        try:
            staged.rename(paths.shell_plugin_dir)
        except Exception:
            if displaced.exists() and not paths.shell_plugin_dir.exists():
                displaced.rename(paths.shell_plugin_dir)
            raise
        _remove_tree(displaced)
    finally:
        _remove_tree(staged)
    return True


def _plugin_state() -> dict[str, object] | None:
    try:
        completed = run("plugin", "list", "--json", check=False, timeout=5)
        if completed.returncode != 0:
            return None
        payload = json.loads(completed.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if not isinstance(payload, list):
        return None
    return next(
        (item for item in payload if isinstance(item, dict) and item.get("id") == PLUGIN_ID),
        None,
    )


def _wait_for_plugin(*, enabled: bool | None = None, timeout: float = 4.0) -> dict[str, object] | None:
    deadline = time.monotonic() + timeout
    while True:
        state = _plugin_state()
        if state is not None and (enabled is None or state.get("enabled") is enabled):
            return state
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.1)


def _panel_health() -> str:
    try:
        completed = run(
            "shell", "shell", "call", PLUGIN_ID, "health", "{}",
            check=False, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def _wait_for_ready(timeout: float = 4.0) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        if _panel_health() == "open":
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def _rescan_shell() -> None:
    completed = run("shell", "shell", "rescanPlugins", check=False, timeout=5)
    # rescanPlugins is a void Shell IPC method. Current Quickshell emits no
    # payload for it; older wrappers emitted "ok". In both cases discovery
    # below, rather than stdout, is the authoritative acknowledgement.
    response = completed.stdout.strip()
    if completed.returncode != 0 or response not in {"", "ok"}:
        detail = completed.stderr.strip() or response
        raise RuntimeError(detail or "Omarchy Shell could not rescan plugins")
    if _wait_for_plugin() is None:
        raise RuntimeError("Omarchy Shell did not discover the THPM plugin")


def _repair_shell() -> dict[str, object]:
    state = _plugin_state()
    rescanned = False
    enabled = False
    if state is None:
        _rescan_shell()
        rescanned = True
        state = _plugin_state()
        if state is None:
            raise RuntimeError("Omarchy Shell did not discover the THPM plugin")
    if state.get("enabled") is not True:
        completed = run("plugin", "enable", PLUGIN_ID, check=False, timeout=5)
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(detail or "Omarchy Shell could not enable the THPM plugin")
        enabled = True
        state = _wait_for_plugin(enabled=True)
        if state is None:
            raise RuntimeError("Omarchy Shell did not persist the THPM plugin as enabled")
    return {"rescanned": rescanned, "enabled": enabled}


@contextmanager
def _launch_lock(paths: Paths) -> Iterator[None]:
    lock_path = paths.runtime_dir / "thpm-ui-open.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _launch_fallback() -> bool:
    launcher = shutil.which("omarchy-launch-floating-terminal-with-presentation")
    if not launcher:
        return False
    try:
        subprocess.Popen(
            [launcher, "thpm tui"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return True


def surface(paths: Paths, requested: str | None = None) -> dict[str, object]:
    current = _surface(paths)
    if requested is None:
        return {"surface": current, "changed": False}
    selected = ("tui" if current == "gui" else "gui") if requested == "toggle" else requested
    if selected not in SURFACES:
        raise ValueError(f"unknown UI surface: {requested}")
    menu = paths.menu_extension
    previous_link = os.readlink(menu) if menu.is_symlink() else None
    previous_file = previous_link is None and menu.exists()
    next_menu = _menu_text(paths, selected)
    rollback_file: Path | None = None
    if previous_file:
        descriptor, rollback_name = tempfile.mkstemp(
            prefix=".thpm-menu-rollback-", dir=menu.parent
        )
        os.close(descriptor)
        rollback_file = Path(rollback_name)
        rollback_file.unlink()
        os.replace(menu, rollback_file)
    try:
        atomic_text(menu, next_menu)
        atomic_text(paths.ui_state_file, f'menu_surface = "{selected}"\n')
    except OSError as exc:
        try:
            menu.unlink(missing_ok=True)
            if previous_link is not None:
                menu.symlink_to(previous_link)
            elif rollback_file is not None:
                os.replace(rollback_file, menu)
        except OSError as rollback_exc:
            raise RuntimeError(
                f"menu surface state failed: {exc}; menu rollback failed: {rollback_exc}"
            ) from exc
        raise
    if rollback_file is not None:
        rollback_file.unlink(missing_ok=True)
    if shell_running():
        run("menu", "refresh", check=False)
    return {"surface": selected, "changed": selected != current}


def install(paths: Paths) -> dict[str, object]:
    deployed = _deploy(paths)
    selected = _surface(paths)
    menu_changed = not _menu_current(paths)
    if menu_changed:
        _write_menu(paths, selected)
    repair = {"rescanned": False, "enabled": False}
    if shell_running():
        if deployed:
            _rescan_shell()
            repair["rescanned"] = True
        repaired = _repair_shell()
        repair["rescanned"] = repair["rescanned"] or repaired["rescanned"]
        repair["enabled"] = repaired["enabled"]
        if menu_changed:
            run("menu", "refresh", check=False)
    return {
        "installed": True,
        "deployed": deployed,
        "menuChanged": menu_changed,
        "path": str(paths.shell_plugin_dir),
        "menu": str(paths.menu_extension),
        "menuSurface": selected,
        **repair,
    }


def open_manager(paths: Paths, *, fallback: bool = True) -> dict[str, object]:
    try:
        with _launch_lock(paths):
            if not shell_running():
                raise RuntimeError("Omarchy Shell is not running")
            menu_synchronized = not _menu_current(paths)
            if menu_synchronized:
                _write_menu(paths, _surface(paths))
                run("menu", "refresh", check=False)
            synchronized = not _deployment_current(paths)
            if synchronized:
                _deploy(paths)
                # A changed tree must be rediscovered even when the old plugin is
                # still represented in the registry.
                _rescan_shell()
            repaired = _repair_shell()
            completed = run("shell", "shell", "summon", PLUGIN_ID, "{}", check=False, timeout=5)
            response = completed.stdout.strip()
            if completed.returncode != 0 or response != "ok":
                detail = completed.stderr.strip() or response
                raise RuntimeError(detail or "Omarchy Shell rejected the THPM window")
            if not _wait_for_ready():
                raise RuntimeError("Omarchy Shell accepted THPM but its graphical panel did not become ready")
            return {
                "opened": True,
                "surface": "gui",
                "synchronized": synchronized,
                "menuSynchronized": menu_synchronized,
                **repaired,
            }
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        if fallback and _launch_fallback():
            return {
                "opened": True,
                "surface": "recovery-tui",
                "synchronized": False,
                "degraded": True,
                "graphicalError": str(exc),
            }
        raise RuntimeError(str(exc)) from exc


def sync(paths: Paths) -> dict[str, object]:
    requested = paths.shell_plugin_dir.exists() or (
        paths.menu_extension.exists() and START in paths.menu_extension.read_text()
    )
    if not requested:
        return {"installed": False, "skipped": True, "reason": "graphical manager is not installed"}
    return install(paths)


def remove(paths: Paths) -> dict[str, object]:
    if shell_running():
        run("plugin", "disable", PLUGIN_ID, check=False)
    shutil.rmtree(paths.shell_plugin_dir, ignore_errors=True)
    if paths.menu_extension.exists():
        cleaned = remove_managed_block(paths.menu_extension.read_text(), START, END)
        atomic_text(paths.menu_extension, cleaned)
    if shell_running():
        run("shell", "shell", "rescanPlugins", check=False)
        run("menu", "refresh", check=False)
    return {"installed": False}


def status(paths: Paths) -> dict[str, object]:
    running = shell_running()
    state = _plugin_state() if running else None
    health = _panel_health() if running and state is not None else "unknown"
    return {
        "installed": paths.shell_plugin_dir.is_dir(),
        "current": _deployment_current(paths),
        "discovered": state is not None,
        "enabled": state.get("enabled") is True if state else False,
        "loaded": health in {"loaded", "open"},
        "open": health == "open",
        "menuEntry": START in paths.menu_extension.read_text() if paths.menu_extension.exists() else False,
        "menuCurrent": _menu_current(paths),
        "menuSurface": _surface(paths),
        "shellRunning": running,
    }
