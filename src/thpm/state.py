from __future__ import annotations

import fcntl
import os
import tempfile
import tomllib
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .paths import Paths
from .registry import PLUGINS


class StateError(ValueError):
    """Raised when persisted THPM state exists but cannot be trusted."""


def defaults() -> dict[str, bool]:
    return {plugin.id: plugin.default_enabled for plugin in PLUGINS}


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
def mutation_lock(paths: Paths) -> Iterator[None]:
    paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
    with paths.lock_file.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another THPM operation is already running") from exc
        yield
