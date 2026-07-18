from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

REQUIRED = (
    "mode",
    "bg",
    "dark_bg",
    "darker_bg",
    "lighter_bg",
    "selection",
    "muted",
    "dark_fg",
    "fg",
    "light_fg",
    "bright_fg",
    "red",
    "yellow",
    "orange",
    "green",
    "cyan",
    "blue",
    "magenta",
    "brown",
    "bright_red",
    "bright_yellow",
    "bright_green",
    "bright_cyan",
    "bright_blue",
    "bright_magenta",
)
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
OPTIONAL_HEX = ("active_border_color",)


def _validate(data: dict[str, object]) -> dict[str, str]:
    missing = [key for key in REQUIRED if not str(data.get(key, "")).strip()]
    if missing:
        raise ValueError("missing semantic colors: " + ", ".join(missing))
    if data["mode"] not in {"dark", "light"}:
        raise ValueError("mode must be dark or light")
    invalid = [
        key for key in REQUIRED if key != "mode" and not HEX.match(str(data[key]))
    ]
    if invalid:
        raise ValueError("invalid semantic colors: " + ", ".join(invalid))
    result = {key: str(data[key]) for key in REQUIRED}
    result.update(
        (key, str(data[key]))
        for key in OPTIONAL_HEX
        if key in data and HEX.match(str(data[key]))
    )
    return result


def _strict(path: Path) -> dict[str, str]:
    return _validate(tomllib.loads(path.read_text()))


def _resolved(path: Path, command: str) -> dict[str, str]:
    try:
        completed = subprocess.run(
            [command, "--file", str(path), "--all"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Omarchy palette resolver timed out") from exc
    except OSError as exc:
        raise ValueError(f"unable to run Omarchy palette resolver: {exc}") from exc
    if completed.returncode != 0:
        detail = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or f"exit {completed.returncode}"
        )
        raise ValueError(f"Omarchy palette resolver failed: {detail}")
    data: dict[str, object] = {}
    for line_number, line in enumerate(completed.stdout.splitlines(), 1):
        if not line:
            continue
        key, separator, value = line.partition("\t")
        if not separator or not key or key in data:
            raise ValueError(
                f"invalid Omarchy palette resolver output on line {line_number}"
            )
        data[key] = value
    return _validate(data)


def load(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise FileNotFoundError(path)
    resolver = shutil.which("omarchy-theme-color")
    return _resolved(path, resolver) if resolver else _strict(path)
