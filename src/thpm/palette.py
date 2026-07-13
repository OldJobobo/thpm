from __future__ import annotations

import re
import tomllib
from pathlib import Path

REQUIRED = ("mode", "bg", "dark_bg", "darker_bg", "lighter_bg", "selection", "muted", "dark_fg", "fg", "light_fg", "bright_fg", "red", "yellow", "orange", "green", "cyan", "blue", "magenta", "brown", "bright_red", "bright_yellow", "bright_green", "bright_cyan", "bright_blue", "bright_magenta")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def load(path: Path) -> dict[str, str]:
    data = tomllib.loads(path.read_text())
    missing = [key for key in REQUIRED if key not in data]
    if missing:
        raise ValueError("missing semantic colors: " + ", ".join(missing))
    if data["mode"] not in {"dark", "light"}:
        raise ValueError("mode must be dark or light")
    invalid = [key for key in REQUIRED if key != "mode" and not HEX.match(str(data[key]))]
    if invalid:
        raise ValueError("invalid semantic colors: " + ", ".join(invalid))
    return {key: str(data[key]) for key in REQUIRED}
