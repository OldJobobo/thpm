from __future__ import annotations

from .files import atomic_copy
from .paths import Paths
from .registry import PLUGINS
from .resources import asset


def reconcile(paths: Paths, enabled: dict[str, bool]) -> list[str]:
    changed: list[str] = []
    paths.themed_dir.mkdir(parents=True, exist_ok=True)
    owned = {name for plugin in PLUGINS for name in plugin.templates}
    wanted = {name for plugin in PLUGINS if enabled.get(plugin.id) for name in plugin.templates}
    for name in sorted(owned):
        target = paths.themed_dir / name
        if name in wanted:
            source = asset("templates", name)
            if not source.is_file():
                raise FileNotFoundError(f"missing packaged template: {name}")
            if not target.exists() or source.read_bytes() != target.read_bytes():
                atomic_copy(source, target)
                changed.append(str(target))
        elif target.exists():
            target.unlink()
            changed.append(str(target))
    return changed
