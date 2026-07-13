from __future__ import annotations

import os
import site
import sys
from pathlib import Path


def root() -> Path:
    override = os.environ.get("THPM_ASSET_DIR")
    if override:
        return Path(override)
    candidates = (
        Path(sys.prefix) / "share/thpm",
        Path(site.USER_BASE) / "share/thpm",
        Path("/usr/share/thpm"),
        Path(__file__).resolve().parents[2] / "assets",
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[-1]


def asset(*parts: str) -> Path:
    return root().joinpath(*parts)
