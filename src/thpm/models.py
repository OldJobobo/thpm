from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

Ownership = Literal["thpm", "native", "theme-provided", "unavailable", "conflicting"]
ApplyStatus = Literal["applied", "unchanged", "skipped", "failed"]


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
class ApplyResult:
    id: str
    status: ApplyStatus
    changed: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    message: str = ""
    warnings: list[str] = field(default_factory=list)

    def json(self) -> dict[str, object]:
        return asdict(self)


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
