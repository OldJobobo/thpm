from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _expand(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


@dataclass(frozen=True)
class Paths:
    home: Path
    config_home: Path
    data_home: Path
    state_home: Path
    runtime_dir: Path
    cache_root: Path | None = None

    @classmethod
    def discover(cls) -> "Paths":
        home = Path.home()
        return cls(
            home=home,
            config_home=_expand(os.environ.get("XDG_CONFIG_HOME", "~/.config")),
            data_home=_expand(os.environ.get("XDG_DATA_HOME", "~/.local/share")),
            state_home=_expand(os.environ.get("XDG_STATE_HOME", "~/.local/state")),
            runtime_dir=_expand(os.environ.get("XDG_RUNTIME_DIR", "/tmp")),
            cache_root=_expand(os.environ.get("XDG_CACHE_HOME", "~/.cache")),
        )

    @property
    def thpm_config_dir(self) -> Path:
        return self.config_home / "thpm"

    @property
    def thpm_state_dir(self) -> Path:
        return self.state_home / "thpm"

    @property
    def state_file(self) -> Path:
        return self.thpm_state_dir / "state.toml"

    @property
    def legacy_compat_file(self) -> Path:
        return self.data_home / "thpm/lib/theme-env.sh"

    @property
    def lock_file(self) -> Path:
        return self.runtime_dir / "thpm.lock"

    @property
    def update_lock_file(self) -> Path:
        return self.runtime_dir / "thpm-update.lock"

    @property
    def update_cache_file(self) -> Path:
        return (self.cache_root or self.home / ".cache") / "thpm/update.json"

    @property
    def install_metadata(self) -> Path:
        return self.data_home / "thpm/install.toml"

    @property
    def current_theme(self) -> Path:
        return self.state_home / "omarchy/current/theme"

    @property
    def current_theme_name(self) -> Path:
        return self.state_home / "omarchy/current/theme.name"

    @property
    def current_background(self) -> Path:
        return self.state_home / "omarchy/current/background"

    @property
    def hook_dir(self) -> Path:
        return self.config_home / "omarchy/hooks/theme-set.d"

    @property
    def hook_file(self) -> Path:
        return self.hook_dir / "90-thpm"

    @property
    def themed_dir(self) -> Path:
        return self.config_home / "omarchy/themed"

    @property
    def shell_plugin_dir(self) -> Path:
        return self.config_home / "omarchy/plugins/io.github.oldjobobo.thpm"

    @property
    def menu_extension(self) -> Path:
        return self.config_home / "omarchy/extensions/omarchy-menu.jsonc"
