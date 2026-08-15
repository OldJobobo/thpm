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
    saved = raw.get("plugins", {})
    for plugin_id in enabled:
        if isinstance(saved.get(plugin_id), bool):
            enabled[plugin_id] = saved[plugin_id]
    # Releases before managed Cava setup wrote the then-default `cava = true`
    # into every state file. Do not interpret that legacy value as consent to
    # edit the user's Cava selector. Confirmed setup creates the durable marker.
    enforce_cava_opt_in(paths, enabled)
    return enabled


def save(paths: Paths, enabled: dict[str, bool]) -> None:
    paths.thpm_state_dir.mkdir(parents=True, exist_ok=True)
    lines = ["version = 1", "", "[plugins]"]
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
