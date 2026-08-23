from __future__ import annotations

import re
from pathlib import Path

from .paths import Paths

UNRESOLVED_PLACEHOLDER = re.compile(r"\{\{\s*[^{}]+?\s*\}\}")


def authored_source(paths: Paths, names: tuple[str, ...]) -> Path | None:
    """Return the first declared active-theme asset, preserving declaration order."""
    return next(
        (
            paths.current_theme / name
            for name in names
            if (paths.current_theme / name).is_file()
        ),
        None,
    )


def ensure_rendered(source: Path) -> None:
    match = UNRESOLVED_PLACEHOLDER.search(source.read_text())
    if match:
        raise RuntimeError(
            "generated theme output contains an unresolved placeholder: "
            f"{source} ({match.group(0)})"
        )


def select_source(
    paths: Paths,
    authored_names: tuple[str, ...],
    generated_name: str | None,
) -> Path | None:
    """Select an authored asset first, then a validated generated fallback."""
    source = authored_source(paths, authored_names)
    if source is not None:
        return source
    if generated_name is None:
        return None
    generated = paths.current_theme / generated_name
    if not generated.is_file():
        return None
    ensure_rendered(generated)
    return generated
