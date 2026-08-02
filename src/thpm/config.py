from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .files import atomic_text
from .paths import Paths

RESTART_POLICIES = ("automatic", "notify")
DEFAULT_RESTART_POLICY = "automatic"


class ConfigError(ValueError):
    """Raised when user configuration exists but cannot be trusted."""


@dataclass(frozen=True)
class Preferences:
    restart_policy: str = DEFAULT_RESTART_POLICY

    @property
    def automatic_app_restarts(self) -> bool:
        return self.restart_policy == "automatic"

    def json(self) -> dict[str, object]:
        return {
            "restartPolicy": self.restart_policy,
            "automaticAppRestarts": self.automatic_app_restarts,
        }


def _parse(path: Path) -> Preferences:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"invalid THPM config at {path}: {exc}") from exc
    if raw.get("config_version") != 1:
        raise ConfigError(
            f"invalid THPM config at {path}: config_version must be 1"
        )
    behavior = raw.get("behavior", {})
    if not isinstance(behavior, dict):
        raise ConfigError(f"invalid THPM config at {path}: behavior must be a table")
    policy = behavior.get("restart_policy", DEFAULT_RESTART_POLICY)
    if policy not in RESTART_POLICIES:
        choices = " or ".join(f'"{item}"' for item in RESTART_POLICIES)
        raise ConfigError(
            f"invalid THPM config at {path}: behavior.restart_policy must be {choices}"
        )
    return Preferences(restart_policy=str(policy))


def load(paths: Paths) -> Preferences:
    if not paths.config_file.exists():
        return Preferences()
    if not paths.config_file.is_file() or paths.config_file.is_symlink():
        raise ConfigError(f"invalid THPM config path: {paths.config_file}")
    return _parse(paths.config_file)


def save(paths: Paths, preferences: Preferences) -> None:
    if preferences.restart_policy not in RESTART_POLICIES:
        raise ValueError(f"unknown restart policy: {preferences.restart_policy}")
    atomic_text(
        paths.config_file,
        "\n".join(
            (
                "config_version = 1",
                "",
                "[behavior]",
                f'restart_policy = "{preferences.restart_policy}"',
                "",
            )
        ),
    )


def claims_current_format(path: Path) -> bool:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return False
        return bool(
            re.search(
                r"(?m)^\s*config_version\s*=\s*1(?:\s*(?:#.*)?)?$",
                text,
            )
        )
    return raw.get("config_version") == 1
