from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

Ownership = Literal["thpm", "native", "theme-provided", "unavailable", "conflicting"]


@dataclass(frozen=True)
class Plugin:
    id: str
    label: str
    category: str
    description: str
    kind: Literal["template", "apply", "hybrid", "action"]
    commands: tuple[str, ...] = ()
    theme_assets: tuple[str, ...] = ()
    templates: tuple[str, ...] = ()
    default_enabled: bool = True
    confirmation: bool = False
    native: bool = False


@dataclass
class PluginView:
    id: str
    label: str
    category: str
    description: str
    kind: str
    ownership: Ownership
    enabled: bool
    available: bool
    commands: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    themeAssets: list[str] = field(default_factory=list)
    templates: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confirmationRequired: bool = False

    def json(self) -> dict[str, object]:
        return asdict(self)
