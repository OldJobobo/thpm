from __future__ import annotations

import fcntl
import os
import tempfile
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .files import atomic_text
from .paths import Paths
from .registry import PLUGINS


STATE_VERSION = 2


class StateError(ValueError):
    """Raised when persisted THPM state exists but cannot be trusted."""


def defaults() -> dict[str, bool]:
    return {plugin.id: plugin.default_enabled for plugin in PLUGINS}


def cava_opt_in_completed(paths: Paths) -> bool:
    marker = paths.cava_opt_in_marker
    if not marker.is_file() or marker.is_symlink():
        return False
    try:
        return marker.read_text(encoding="utf-8") == "version = 1\n"
    except (OSError, UnicodeError):
        return False


def complete_cava_opt_in(paths: Paths) -> None:
    atomic_text(paths.cava_opt_in_marker, "version = 1\n", 0o600)


def enforce_cava_opt_in(paths: Paths, enabled: dict[str, bool]) -> None:
    if enabled.get("cava") and not cava_opt_in_completed(paths):
        enabled["cava"] = False


def load(paths: Paths) -> dict[str, bool]:
    enabled = defaults()
    try:
        raw = tomllib.loads(paths.state_file.read_text())
    except FileNotFoundError:
        return enabled
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise StateError(f"invalid THPM state at {paths.state_file}: {exc}") from exc
    version = raw.get("version")
    if version is not None and (
        type(version) is not int or version not in {1, STATE_VERSION}
    ):
        raise StateError(
            f"unsupported THPM state version at {paths.state_file}: {version!r}"
        )
    saved = raw.get("plugins", {})
    if not isinstance(saved, dict):
        raise StateError(f"invalid THPM plugin state at {paths.state_file}")
    for plugin_id in enabled:
        if isinstance(saved.get(plugin_id), bool):
            enabled[plugin_id] = saved[plugin_id]
    # Schema 1 persisted every registry default, so `swaync = true` did not
    # demonstrate explicit consent to use the still-experimental integration.
    if version in {None, 1}:
        enabled["swaync"] = False
    if enabled["discord"] and enabled["discord-system24"]:
        raise StateError(
            "conflicting THPM integrations are enabled: discord and discord-system24"
        )
    # Releases before managed Cava setup wrote the then-default `cava = true`
    # into every state file. Do not interpret that legacy value as consent to
    # edit the user's Cava selector. Confirmed setup creates the durable marker.
    enforce_cava_opt_in(paths, enabled)
    return enabled


def save(paths: Paths, enabled: dict[str, bool]) -> None:
    if enabled.get("discord") and enabled.get("discord-system24"):
        raise StateError(
            "conflicting THPM integrations are enabled: discord and discord-system24"
        )
    paths.thpm_state_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"version = {STATE_VERSION}", "", "[plugins]"]
    lines.extend(f'{key} = {str(value).lower()}' for key, value in sorted(enabled.items()))
    fd, name = tempfile.mkstemp(prefix=".state-", dir=paths.thpm_state_dir, text=True)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write("\n".join(lines) + "\n")
        os.replace(name, paths.state_file)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def _lock(path: Path, message: str) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(message) from exc
        yield


@contextmanager
def mutation_lock(paths: Paths) -> Iterator[None]:
    with _lock(paths.lock_file, "another THPM operation is already running"):
        yield


@contextmanager
def migration_lock(paths: Paths) -> Iterator[None]:
    """Serialize refresh migrations without blocking theme hooks on the mutation lock."""
    with _lock(paths.migration_lock_file, "another THPM migration is already running"):
        yield
