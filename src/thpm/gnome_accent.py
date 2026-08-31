from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .files import atomic_text
from .palette import load as load_palette
from .paths import Paths

SCHEMA = "org.gnome.desktop.interface"
KEY = "accent-color"
ACCENTS = ("red", "orange", "yellow", "green", "teal", "blue", "purple", "pink")
HUES = (0, 28, 52, 125, 185, 215, 275, 330)
VALID = frozenset((*ACCENTS, "slate"))
PHASES = frozenset(("committed", "prepared", "may-have-succeeded"))
Runner = Callable[..., subprocess.CompletedProcess[str]]
State = dict[str, Any]


def state_path(paths: Paths) -> Path:
    return paths.managed_asset_state_dir / "gnome-accent-compat.json"


def nearest_accent(value: str) -> str:
    value = value.removeprefix("#")
    red, green, blue = (int(value[index : index + 2], 16) for index in (0, 2, 4))
    maximum, minimum = max(red, green, blue), min(red, green, blue)
    if maximum == 0 or (maximum - minimum) / maximum < 0.20:
        return "slate"
    delta = maximum - minimum
    if maximum == red:
        hue = (60 * ((green - blue) / delta)) % 360
    elif maximum == green:
        hue = 60 * ((blue - red) / delta) + 120
    else:
        hue = 60 * ((red - green) / delta) + 240
    return min(
        zip(ACCENTS, HUES),
        key=lambda item: min(abs(hue - item[1]), 360 - abs(hue - item[1])),
    )[0]


def desired_accent(paths: Paths) -> str:
    colors = load_palette(paths.current_theme / "colors.toml")
    return nearest_accent(colors.get("accent", colors["blue"]))


def _run(
    *args: str, runner: Runner | None = None
) -> subprocess.CompletedProcess[str]:
    command_runner = runner or subprocess.run
    try:
        completed = command_runner(
            ["gsettings", *args],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("gsettings timed out") from exc
    except OSError as exc:
        raise RuntimeError(f"unable to run gsettings: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        raise RuntimeError(f"gsettings {' '.join(args)} failed: {detail}")
    return completed


def readiness(
    paths: Paths,
    *,
    command: str | None,
    runner: Runner | None = None,
) -> tuple[bool, list[str]]:
    del paths
    missing: list[str] = []
    if command is None:
        return False, ["gsettings"]
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        missing.append("desktop DBus session (DBUS_SESSION_BUS_ADDRESS)")
        return False, missing
    try:
        keys = _run("list-keys", SCHEMA, runner=runner).stdout.splitlines()
        if KEY not in keys:
            missing.append(f"GSettings key {SCHEMA} {KEY}")
        elif _run("writable", SCHEMA, KEY, runner=runner).stdout.strip() != "true":
            missing.append(f"writable GSettings key {SCHEMA} {KEY}")
    except RuntimeError as exc:
        missing.append(str(exc))
    return not missing, missing


def _current(*, runner: Runner | None = None) -> str:
    value = _run("get", SCHEMA, KEY, runner=runner).stdout.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    if value not in VALID:
        raise RuntimeError(f"gsettings returned an invalid accent-color value: {value!r}")
    return value


def _set(value: str, *, runner: Runner | None = None) -> None:
    _run("set", SCHEMA, KEY, value, runner=runner)


def _committed(prior: str, managed: str) -> State:
    return {
        "version": 2,
        "schema": SCHEMA,
        "key": KEY,
        "phase": "committed",
        "prior": prior,
        "managed": managed,
    }


def _pending(
    saved: State,
    *,
    current: str,
    desired: str,
    had_ownership: bool,
    phase: str,
) -> State:
    return {
        **_committed(str(saved["prior"]), str(saved["managed"])),
        "phase": phase,
        "pendingFrom": current,
        "pendingTo": desired,
        "hadOwnership": had_ownership,
    }


def _read_state(path: Path) -> State | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        saved = json.loads(path.read_text())
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(saved, dict):
        return None
    if saved.get("version") != 2:
        return None
    if saved.get("schema") != SCHEMA or saved.get("key") != KEY:
        return None
    if saved.get("prior") not in VALID or saved.get("managed") not in VALID:
        return None
    phase = saved.get("phase")
    if phase not in PHASES:
        return None
    if phase != "committed" and (
        saved.get("pendingFrom") not in VALID
        or saved.get("pendingTo") not in VALID
        or not isinstance(saved.get("hadOwnership"), bool)
    ):
        return None
    return saved


def _write_state(path: Path, saved: State) -> None:
    atomic_text(path, json.dumps(saved, separators=(",", ":")) + "\n", 0o600)


def _restore_pretransition(path: Path, saved: State) -> State | None:
    if bool(saved["hadOwnership"]):
        committed = _committed(str(saved["prior"]), str(saved["managed"]))
        _write_state(path, committed)
        return committed
    path.unlink(missing_ok=True)
    return None


def _recover_pending(path: Path, saved: State, current: str) -> tuple[State | None, bool]:
    phase = str(saved["phase"])
    if phase == "committed":
        return saved, False
    if phase == "prepared":
        return _restore_pretransition(path, saved), True
    pending_from = str(saved["pendingFrom"])
    pending_to = str(saved["pendingTo"])
    if current == pending_to:
        committed = _committed(str(saved["prior"]), pending_to)
        _write_state(path, committed)
        return committed, True
    if current == pending_from:
        return _restore_pretransition(path, saved), True
    raise RuntimeError(
        "GNOME accent transition is unresolved: current value "
        f"{current!r} matches neither pending source {pending_from!r} nor "
        f"pending target {pending_to!r}; retained recovery state at {path}"
    )


def _restore_after_failed_set(
    path: Path,
    pending: State,
    *,
    runner: Runner | None,
    failure: Exception,
) -> None:
    try:
        current = _current(runner=runner)
    except RuntimeError as probe_exc:
        raise RuntimeError(
            f"GNOME accent update failed ({failure}); outcome could not be verified "
            f"and recovery state was retained at {path}: {probe_exc}"
        ) from failure
    if current != str(pending["pendingFrom"]):
        raise RuntimeError(
            f"GNOME accent update failed ({failure}); current value is {current!r}, "
            f"so recovery state was retained at {path}"
        ) from failure
    try:
        _restore_pretransition(path, pending)
    except Exception as state_exc:
        raise RuntimeError(
            f"GNOME accent update failed ({failure}); transition was not applied but "
            f"restoration state recovery failed: {state_exc}"
        ) from failure
    raise failure


def apply(
    paths: Paths, *, runner: Runner | None = None
) -> tuple[list[str], list[str], list[str]]:
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        raise RuntimeError("desktop DBus session is unavailable")
    state = state_path(paths)
    saved = _read_state(state)
    if (state.exists() or state.is_symlink()) and saved is None:
        raise RuntimeError(f"GNOME accent restoration state is invalid: {state}")
    current = _current(runner=runner)
    recovered = False
    if saved is not None:
        saved, recovered = _recover_pending(state, saved, current)
    desired = desired_accent(paths)
    changed = [str(state)] if recovered else []
    if saved is not None and current != saved["managed"]:
        return changed, [], [
            f"preserved user-modified GNOME accent {current}; THPM last set {saved['managed']}"
        ]
    if current == desired:
        if saved is None:
            _write_state(state, _committed(current, current))
            if str(state) not in changed:
                changed.append(str(state))
        return changed, [], []

    had_ownership = saved is not None
    base = saved or _committed(current, current)
    prepared = _pending(
        base,
        current=current,
        desired=desired,
        had_ownership=had_ownership,
        phase="prepared",
    )
    _write_state(state, prepared)
    if str(state) not in changed:
        changed.append(str(state))
    pending = {**prepared, "phase": "may-have-succeeded"}
    _write_state(state, pending)
    try:
        _set(desired, runner=runner)
    except Exception as exc:
        _restore_after_failed_set(
            state, pending, runner=runner, failure=exc
        )

    committed = _committed(str(base["prior"]), desired)
    try:
        _write_state(state, committed)
    except Exception as state_exc:
        try:
            _set(current, runner=runner)
        except Exception as rollback_exc:
            raise RuntimeError(
                f"GNOME accent state commit failed ({state_exc}); rollback to "
                f"{current!r} also failed ({rollback_exc}); retained pending recovery "
                f"state at {state}"
            ) from state_exc
        try:
            _restore_pretransition(state, pending)
        except Exception as recovery_exc:
            raise RuntimeError(
                f"GNOME accent state commit failed ({state_exc}); setting rollback "
                f"succeeded but restoration state recovery failed ({recovery_exc})"
            ) from state_exc
        raise RuntimeError(
            f"GNOME accent state commit failed ({state_exc}); setting was rolled back"
        ) from state_exc
    return changed, [f"gsettings set {SCHEMA} {KEY} {desired}"], []


def cleanup(paths: Paths, *, runner: Runner | None = None) -> tuple[list[str], list[str]]:
    state = state_path(paths)
    if not state.exists() and not state.is_symlink():
        return [], []
    saved = _read_state(state)
    if saved is None:
        return [], [f"GNOME accent cleanup incomplete because restoration state is invalid: {state}"]
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return [], ["GNOME accent cleanup incomplete because the desktop DBus session is unavailable"]
    try:
        current = _current(runner=runner)
        saved, recovered = _recover_pending(state, saved, current)
    except RuntimeError as exc:
        return [], [f"GNOME accent cleanup incomplete because recovery failed: {exc}"]
    changed = [str(state)] if recovered else []
    if saved is None:
        return changed, []
    if current != saved["managed"]:
        try:
            state.unlink()
        except OSError as exc:
            return changed, [
                f"GNOME accent cleanup incomplete because recovery state could not be removed: {exc}"
            ]
        if str(state) not in changed:
            changed.append(str(state))
        return changed, [
            f"preserved user-modified GNOME accent {current}; THPM last set {saved['managed']}"
        ]
    try:
        if current != saved["prior"]:
            _set(str(saved["prior"]), runner=runner)
    except RuntimeError as exc:
        return changed, [f"GNOME accent cleanup incomplete because restoration failed: {exc}"]
    try:
        state.unlink()
    except OSError as exc:
        return changed, [
            f"GNOME accent cleanup incomplete because recovery state could not be removed: {exc}"
        ]
    if str(state) not in changed:
        changed.append(str(state))
    return changed, []
