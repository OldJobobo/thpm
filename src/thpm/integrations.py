from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from .compat import (
    apply_gtk,
    apply_vscode_local,
    gtk_requested,
    vscode_local_requested,
    vscode_readiness,
)
from .files import atomic_copy, atomic_text, remove_managed_block
from .models import ApplyResult
from .palette import load as load_palette
from .paths import Paths
from .registry import BY_ID, PLUGINS
from .zed import ZedThemeError
from .zed import legacy_target as zed_legacy_target
from .zed import normalized as normalized_zed_theme
from .zed import source as zed_source
from .zed import target as zed_target

GENERATED = {
    "fish": "thpm-fish.fish",
    "fzf": "thpm-fzf.fish",
    "discord": "thpm-vencord.theme.css",
    "discord-system24": "thpm-vencord-system24.theme.css",
    "qt6ct": "thpm-qt6ct.conf",
    "spotify": "thpm-spicetify.ini",
    "superfile": "thpm-superfile.toml",
    "vicinae": "thpm-vicinae.toml",
    "nwg-dock": "thpm-nwg-dock.css",
    "cava": "thpm-cava.ini",
    "firefox": "thpm-firefox.css",
    "zen": "thpm-zen.css",
    "hermes": "thpm-hermes.json",
    "qutebrowser": "thpm-qutebrowser.py",
    "heroic": "thpm-heroic.css",
}

ZELLIJ_MANAGED_START = "// thpm-zellij-theme-start"
ZELLIJ_MANAGED_END = "// thpm-zellij-theme-end"
ZELLIJ_THEME_DECLARATION = re.compile(
    r'(?m)^(?P<prefix>[ \t]*themes[ \t]*\{\s*)(?P<name>"(?:\\.|[^"\\])*"|[^\s{}]+)(?P<suffix>[ \t]*\{)'
)
ZELLIJ_THEME_OPTION = re.compile(
    r'^(?P<indent>[ \t]*)theme[ \t]+(?P<value>"(?P<name>(?:\\.|[^"\\\n])*)")[ \t]*(?:;[ \t]*)?$',
    re.MULTILINE,
)
ZELLIJ_THEME_DIR_OPTION = re.compile(
    r'^(?P<indent>[ \t]*)theme_dir[ \t]+(?P<value>"(?:\\.|[^"\\\n])*")[ \t]*(?:;[ \t]*)?$',
    re.MULTILINE,
)
UNRESOLVED_PLACEHOLDER = re.compile(r"\{\{\s*[^{}]+?\s*\}\}")
OPTIONAL_ASSET_PLUGINS = {
    "branding",
    "typora",
    "swaync",
    "cliamp",
    "zed-extra",
}
RETIRED_OPTIONAL_ASSET_PLUGINS = {"windsurf"}
MANAGED_OUTPUT_PLUGINS = set(GENERATED) | {"discord", "discord-system24"}


def _optional_asset_targets(
    paths: Paths, plugin_id: str
) -> tuple[tuple[str, str, Path], ...]:
    config = paths.config_home
    targets = {
        "branding": (
            ("branding-about", "about.txt", config / "omarchy/branding/about.txt"),
            (
                "branding-screensaver",
                "screensaver.txt",
                config / "omarchy/branding/screensaver.txt",
            ),
        ),
        "typora": (("typora", "typora.css", config / "Typora/themes/omarchy.css"),),
        "swaync": (("swaync", "colors.css", config / "swaync/colors.css"),),
        "windsurf": (
            (
                "windsurf",
                "vscode-theme.json",
                paths.home
                / ".windsurf/extensions/local.omarchy-theme/themes/omarchy.json",
            ),
        ),
        "cliamp": (("cliamp", "cliamp.toml", config / "cliamp/themes/omarchy.toml"),),
    }
    return targets.get(plugin_id, ())


def _standard_output_targets(paths: Paths) -> dict[str, Path]:
    config = paths.config_home
    return {
        "fish": config / "fish/conf.d/thpm-theme.fish",
        "fzf": config / "fish/conf.d/thpm-fzf.fish",
        "qt6ct": config / "qt6ct/colors/thpm.conf",
        "spotify": config / "spicetify/Themes/Omarchy/color.ini",
        "superfile": config / "superfile/theme/thpm.toml",
        "vicinae": config / "vicinae/themes/thpm.toml",
        "nwg-dock": config / "nwg-dock-hyprland/thpm.css",
        "cava": config / "cava/themes/thpm",
        "hermes": config / "Hermes/omarchy-theme.json",
        "qutebrowser": config / "qutebrowser/thpm_theme.py",
        "heroic": config / "heroic/themes/thpm.css",
    }


def _asset_state_paths(paths: Paths, key: str) -> tuple[Path, Path]:
    root = paths.managed_asset_state_dir
    return root / f"{key}.json", root / f"{key}.backup"


def _asset_legacy_marker(paths: Paths, key: str) -> Path:
    return paths.managed_asset_state_dir / f"{key}.legacy-checked"


def _target_key(prefix: str, target: Path) -> str:
    return f"{prefix}-{hashlib.sha256(str(target).encode()).hexdigest()[:16]}"


def _matches_sources(target: Path, sources: tuple[Path, ...]) -> bool:
    if not target.is_file() or target.is_symlink():
        return False
    try:
        target_digest = _digest(target.read_bytes())
        return any(
            source.is_file()
            and not source.is_symlink()
            and _digest(source.read_bytes()) == target_digest
            for source in sources
        )
    except OSError:
        return False


def _matches_installed_theme_asset(paths: Paths, target: Path, asset_name: str) -> bool:
    if not target.is_file() or target.is_symlink():
        return False
    try:
        root = paths.config_home / "omarchy/themes"
        return _matches_sources(target, tuple(root.glob(f"*/{asset_name}")))
    except OSError:
        return False


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _valid_digest(value: object, *, empty: bool = False) -> bool:
    if empty and value == "":
        return True
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _valid_mode(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 0o777


def _read_asset_state(path: Path) -> dict[str, object] | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        saved = json.loads(path.read_text())
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(saved, dict) or not isinstance(saved.get("existed"), bool):
        return None
    if "managedSha256" in saved and not _valid_digest(saved["managedSha256"]):
        return None
    if "managedMode" in saved and not _valid_mode(saved["managedMode"]):
        return None
    if "pendingSha256" in saved and not _valid_digest(saved["pendingSha256"]):
        return None
    if saved["existed"]:
        if saved.get("priorType") == "file":
            if not _valid_digest(saved.get("priorSha256")) or not _valid_mode(
                saved.get("priorMode")
            ):
                return None
        elif saved.get("priorType") == "symlink":
            if not isinstance(saved.get("linkTarget"), str) or not saved["linkTarget"]:
                return None
        else:
            return None
    return saved


def _clear_asset_state(paths: Paths, key: str) -> None:
    state, backup = _asset_state_paths(paths, key)
    state.unlink(missing_ok=True)
    backup.unlink(missing_ok=True)


def _valid_backup(path: Path, expected_digest: str) -> bool:
    try:
        return (
            path.is_file()
            and not path.is_symlink()
            and _digest(path.read_bytes()) == expected_digest
        )
    except OSError:
        return False


def _install_optional_asset(
    paths: Paths,
    key: str,
    source: Path,
    target: Path,
    *,
    legacy_owned: bool = False,
) -> bool:
    """Install one opt-in asset while preserving the file THPM displaced."""
    state_file, backup = _asset_state_paths(paths, key)
    source_data = source.read_bytes()
    source_digest = _digest(source_data)
    target_data = target.read_bytes() if target.is_file() else None
    target_digest = _digest(target_data) if target_data is not None else ""
    target_mode = (
        target.stat().st_mode & 0o777
        if target_data is not None and not target.is_symlink()
        else 0
    )
    saved = _read_asset_state(state_file)
    had_state = saved is not None
    legacy_marker = _asset_legacy_marker(paths, key)
    if state_file.exists() and saved is None:
        raise RuntimeError(f"optional asset restoration state is invalid: {state_file}")
    try:
        managed_mode = int(saved.get("managedMode", 0)) if saved else 0
        prior_mode = int(saved.get("priorMode", 0)) if saved else 0
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"optional asset restoration state is invalid: {state_file}"
        ) from exc

    managed_match = bool(saved) and (
        not target.is_symlink()
        and target_digest == str(saved.get("managedSha256", ""))
        and target_mode == managed_mode
    )
    pending_match = bool(saved) and (
        not target.is_symlink()
        and target_digest == str(saved.get("pendingSha256", ""))
        and target_mode == 0o644
    )
    prior_match = bool(saved) and bool(saved.get("pendingSha256")) and (
        (
            saved.get("priorType") == "symlink"
            and target.is_symlink()
            and str(target.readlink()) == str(saved.get("linkTarget", ""))
        )
        or (
            saved.get("priorType") == "file"
            and not target.is_symlink()
            and target_digest == str(saved.get("priorSha256", ""))
            and target_mode == prior_mode
        )
        or (not bool(saved.get("existed")) and not target.exists())
    )

    if saved is None or not (managed_match or pending_match or prior_match):
        # A changed target belongs to the user again. Start a fresh takeover so it can
        # be restored later. Equal source/target without state is a pre-state THPM
        # install, so do not preserve that stale copy as the user's default.
        _clear_asset_state(paths, key)
        if target.exists() and not target.is_file() and not target.is_symlink():
            raise RuntimeError(f"optional asset target is not a file: {target}")
        if target.is_symlink():
            saved = {
                "existed": True,
                "priorType": "symlink",
                "linkTarget": str(target.readlink()),
            }
        else:
            legacy_takeover = not had_state and not legacy_marker.exists() and legacy_owned
            existed = (
                target_data is not None
                and target_data != source_data
                and not legacy_takeover
            )
            if existed and target_data is not None:
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(target_data)
            saved = {
                "existed": existed,
                "priorType": "file",
                "priorSha256": target_digest if existed else "",
                "priorMode": target_mode if existed else 0o644,
            }

    if not legacy_marker.exists():
        atomic_text(legacy_marker, "checked\n")

    # A pending digest makes either side of the atomic target replacement recognizable
    # after interruption, so the original backup is never mistaken for stale output.
    saved["pendingSha256"] = source_digest
    atomic_text(state_file, json.dumps(saved, separators=(",", ":")) + "\n")
    changed = (
        target_data != source_data or target.is_symlink() or target_mode != 0o644
    )
    if changed:
        atomic_copy(source, target)
    saved["managedSha256"] = source_digest
    saved["managedMode"] = 0o644
    saved.pop("pendingSha256", None)
    atomic_text(state_file, json.dumps(saved, separators=(",", ":")) + "\n")
    return changed


def _cleanup_optional_asset(
    paths: Paths,
    key: str,
    target: Path,
    *,
    legacy_owned: bool = False,
) -> tuple[list[str], list[str]]:
    """Restore one displaced file, preserving targets changed outside THPM."""
    state_file, backup = _asset_state_paths(paths, key)
    invalid = f"could not restore optional asset because state is invalid: {state_file}"
    saved = _read_asset_state(state_file)
    if saved is None:
        if state_file.exists():
            return [], [invalid]
        marker = _asset_legacy_marker(paths, key)
        changed: list[str] = []
        if not marker.exists():
            if legacy_owned and (target.exists() or target.is_symlink()):
                if target.is_file() or target.is_symlink():
                    target.unlink()
                    changed.append(str(target))
                else:
                    return [], [f"preserved non-file legacy output path: {target}"]
            atomic_text(marker, "checked\n")
        return changed, []
    try:
        managed_mode = int(saved.get("managedMode", 0))
        prior_mode = int(saved.get("priorMode", 0o644))
    except (TypeError, ValueError):
        return [], [invalid]
    if bool(saved.get("existed")):
        if saved.get("priorType") == "file" and not _valid_backup(
            backup, str(saved.get("priorSha256", ""))
        ):
            return [], [f"could not restore optional asset because backup is missing or invalid: {backup}"]
        if saved.get("priorType") == "symlink" and not isinstance(
            saved.get("linkTarget"), str
        ):
            return [], [invalid]

    target_data = target.read_bytes() if target.is_file() else None
    target_digest = _digest(target_data) if target_data is not None else ""
    target_mode = (
        target.stat().st_mode & 0o777
        if target_data is not None and not target.is_symlink()
        else 0
    )
    managed_match = (
        target_data is not None
        and not target.is_symlink()
        and target_digest
        in {str(saved.get("managedSha256", "")), str(saved.get("pendingSha256", ""))}
        and target_mode in {managed_mode, 0o644}
    )
    prior_match = bool(saved.get("pendingSha256")) and (
        (
            saved.get("priorType") == "symlink"
            and target.is_symlink()
            and str(target.readlink()) == str(saved.get("linkTarget", ""))
        )
        or (
            saved.get("priorType") == "file"
            and not target.is_symlink()
            and target_digest == str(saved.get("priorSha256", ""))
            and target_mode == prior_mode
        )
        or (not bool(saved.get("existed")) and not target.exists())
    )
    if prior_match:
        _clear_asset_state(paths, key)
        return [], []
    if (target.exists() or target.is_symlink()) and not managed_match:
        _clear_asset_state(paths, key)
        label = "file" if target_data is not None else "path"
        return [], [f"preserved user-modified {label} instead of restoring it: {target}"]

    changed: list[str] = []
    if bool(saved.get("existed")) and saved.get("priorType") == "symlink":
        if target.exists() or target.is_symlink():
            target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(str(saved["linkTarget"]))
        changed.append(str(target))
    elif bool(saved.get("existed")):
        atomic_copy(backup, target, prior_mode)
        changed.append(str(target))
    elif target.exists() or target.is_symlink():
        target.unlink()
        changed.append(str(target))
    _clear_asset_state(paths, key)
    return changed, []


def cleanup_optional_assets(
    paths: Paths, plugin_id: str, *, assume_legacy: bool = False
) -> tuple[list[str], list[str]]:
    changed: list[str] = []
    warnings: list[str] = []
    for key, asset_name, target in _optional_asset_targets(paths, plugin_id):
        legacy_owned = assume_legacy and _matches_installed_theme_asset(
            paths, target, asset_name
        )
        item_changed, item_warnings = _cleanup_optional_asset(
            paths, key, target, legacy_owned=legacy_owned
        )
        changed.extend(item_changed)
        warnings.extend(item_warnings)
    return changed, warnings


def _cleanup_legacy_zed_asset(
    paths: Paths, *, assume_legacy: bool = False
) -> tuple[list[str], list[str]]:
    legacy = zed_legacy_target(paths)
    legacy_owned = assume_legacy and _matches_sources(
        legacy, _current_plugin_sources(paths, "zed-extra")
    )
    return _cleanup_optional_asset(
        paths, "zed-extra", legacy, legacy_owned=legacy_owned
    )


def cleanup_zed_assets(
    paths: Paths, *, assume_legacy: bool = False
) -> tuple[list[str], list[str]]:
    """Relinquish the stable authored theme and migrate the former Omarchy target."""
    changed, warnings = _cleanup_optional_asset(
        paths, "zed-thpm-current", zed_target(paths)
    )
    legacy_changed, legacy_warnings = _cleanup_legacy_zed_asset(
        paths, assume_legacy=assume_legacy
    )
    changed.extend(legacy_changed)
    warnings.extend(legacy_warnings)
    return changed, warnings


def _apply_zed_asset(paths: Paths) -> ApplyResult:
    source = zed_source(paths)
    if source is None:
        changed, warnings = cleanup_zed_assets(paths, assume_legacy=True)
        return _result("zed-extra", changed, [], warnings)

    # Validate and normalize completely before cleaning up or replacing any target.
    content, _appearance = normalized_zed_theme(source)
    legacy_changed, warnings = _cleanup_legacy_zed_asset(
        paths, assume_legacy=True
    )
    paths.thpm_state_dir.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=".zed-current-", suffix=".json", dir=paths.thpm_state_dir, text=True
    )
    rendered = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        changed = _install_optional_asset(
            paths,
            "zed-thpm-current",
            rendered,
            zed_target(paths),
        )
    finally:
        rendered.unlink(missing_ok=True)
    paths_changed = list(legacy_changed)
    if changed:
        paths_changed.append(str(zed_target(paths)))
    return _result("zed-extra", paths_changed, [], warnings)


def _ensure_generated_output_is_rendered(source: Path) -> None:
    match = UNRESOLVED_PLACEHOLDER.search(source.read_text())
    if match:
        raise RuntimeError(
            f"generated theme output contains an unresolved placeholder: "
            f"{source} ({match.group(0)})"
        )


def _generated_output_error(plugin_id: str, paths: Paths) -> str | None:
    name = GENERATED.get(plugin_id)
    if not name:
        return None
    plugin = BY_ID[plugin_id]
    if any((paths.current_theme / asset).is_file() for asset in plugin.theme_assets):
        return None
    source = paths.current_theme / name
    if not source.is_file():
        return None
    try:
        _ensure_generated_output_is_rendered(source)
    except (OSError, RuntimeError, UnicodeError) as exc:
        return str(exc)
    return None


class ApplyFailure(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        changed: list[str] | None = None,
        warnings: list[str] | None = None,
    ):
        super().__init__(message)
        self.changed = changed or []
        self.warnings = warnings or []


def _discord_directories(paths: Paths) -> tuple[Path, ...]:
    return (
        paths.config_home / "Vencord/themes",
        paths.config_home / "vesktop/themes",
        paths.config_home / "Equicord/themes",
        paths.config_home / "equibop/themes",
        paths.home / ".var/app/com.discordapp.Discord/config/Vencord/themes",
        paths.home / ".var/app/dev.vencord.Vesktop/config/vesktop/themes",
        paths.home / ".var/app/io.github.equicord.equibop/config/equibop/themes",
    )


def _browser_default_profile(base: Path) -> str:
    profiles = base / "profiles.ini"
    if not profiles.is_file():
        return ""
    in_install = False
    for raw in profiles.read_text().splitlines():
        if raw.startswith("[Install"):
            in_install = True
        elif raw.startswith("["):
            in_install = False
        elif in_install and raw.startswith("Default="):
            return raw.split("=", 1)[1]
    return ""


def inspect_applicability(plugin_id: str, paths: Paths) -> bool:
    if plugin_id == "gtk-css-compat":
        return gtk_requested(paths)
    if plugin_id == "vscode-local-compat":
        return vscode_local_requested(paths)
    return True


def inspect_readiness(
    plugin_id: str, paths: Paths, which: Callable[[str], str | None] | None = None
) -> tuple[bool, list[str], list[str]]:
    """Return whether an integration can act, its missing prerequisites, and warnings."""
    command_path = which or shutil.which
    plugin = BY_ID[plugin_id]
    missing = [command for command in plugin.commands if command_path(command) is None]
    warnings: list[str] = []
    assets = [
        name for name in plugin.theme_assets if (paths.current_theme / name).is_file()
    ]

    if (
        plugin_id == "zellij"
        and not assets
        and not (paths.current_theme / "colors.toml").is_file()
    ):
        # Cleanup must remain actionable after Zellij is uninstalled.
        missing = []
    elif plugin_id == "zed-extra":
        # Missing authored assets relinquish THPM ownership even if Zed was removed;
        # an available source still requires the application and valid JSON.
        source = zed_source(paths)
        if source is None:
            missing = []
        else:
            try:
                normalized_zed_theme(source)
            except ZedThemeError as exc:
                missing.append(str(exc))
    elif plugin_id in OPTIONAL_ASSET_PLUGINS and not assets:
        # Missing opt-in assets mean "restore defaults", not "unavailable".
        missing = []
    elif plugin_id == "gtk-css-compat":
        missing = []
    elif plugin_id == "vscode-local-compat":
        ready, missing = vscode_readiness(paths)
        return ready, missing, warnings
    elif plugin_id == "hermes" and (
        (paths.config_home / "Hermes").is_dir()
        or command_path("hermes-desktop-remote")
        or command_path("Hermes")
    ):
        missing = []
    elif plugin_id in {"discord", "discord-system24"} and not any(
        path.is_dir() for path in _discord_directories(paths)
    ):
        missing.append("supported Discord client theme directory")
    elif plugin_id in {"firefox", "zen"}:
        base = paths.home / (".mozilla/firefox" if plugin_id == "firefox" else ".zen")
        if not (base / "profiles.ini").is_file():
            missing.append(str(base / "profiles.ini"))
        elif not _browser_default_profile(base):
            missing.append("default browser install profile")
    elif plugin_id == "steam":
        installer = paths.home / ".local/share/steam-adwaita/install.py"
        if not installer.is_file():
            missing.append(str(installer))
    elif (
        plugin.kind == "apply"
        and plugin_id not in OPTIONAL_ASSET_PLUGINS | {"steam", "zellij"}
        and plugin.theme_assets
        and not assets
    ):
        missing.append(" or ".join(plugin.theme_assets) + " in the active theme")

    if generated_error := _generated_output_error(plugin_id, paths):
        missing.append(generated_error)
    if plugin_id == "nwg-dock":
        warnings.append(
            "nwg-dock-hyprland has no supported live reload; restart it to see theme changes"
        )
    return not missing, missing, warnings


def _copy_first(
    paths: Paths, candidates: tuple[str, ...], target: Path
) -> tuple[Path | None, bool]:
    generated_names = set(GENERATED.values())
    for name in candidates:
        source = paths.current_theme / name
        if source.is_file():
            if name in generated_names:
                _ensure_generated_output_is_rendered(source)
            unchanged = target.is_file() and source.read_bytes() == target.read_bytes()
            if not unchanged:
                atomic_copy(source, target)
            return source, not unchanged
    return None, False


def _browser_import(paths: Paths, plugin_id: str, base: Path) -> tuple[list[str], bool]:
    candidates = (
        ("firefox.css", GENERATED[plugin_id])
        if plugin_id == "firefox"
        else ("zen.css", GENERATED[plugin_id])
    )
    source = next(
        (
            paths.current_theme / name
            for name in candidates
            if (paths.current_theme / name).is_file()
        ),
        None,
    )
    if source is None:
        raise RuntimeError(f"{plugin_id}: no theme asset or generated CSS was found")
    profiles = base / "profiles.ini"
    if not profiles.is_file():
        raise RuntimeError(f"{plugin_id}: profiles.ini was not found")
    profile = _browser_default_profile(base)
    if not profile:
        raise RuntimeError(f"{plugin_id}: profiles.ini has no default install profile")
    profile_root = base.resolve()
    profile_path = (base / profile).resolve()
    if profile_path == profile_root or profile_root not in profile_path.parents:
        raise ValueError(f"browser profile escapes its profile root: {profile}")
    chrome = profile_path / "chrome"
    managed = chrome / f"thpm-{plugin_id}.css"
    if source.name in set(GENERATED.values()):
        _ensure_generated_output_is_rendered(source)
    css_changed = _install_optional_asset(
        paths,
        _target_key(f"browser-{plugin_id}", managed),
        source,
        managed,
        legacy_owned=_matches_sources(
            managed, _current_plugin_sources(paths, plugin_id)
        ),
    )
    user_chrome = chrome / "userChrome.css"
    start, end = "/* thpm-import-start */", "/* thpm-import-end */"
    existing = user_chrome.read_text() if user_chrome.exists() else ""
    existing = (
        remove_managed_block(existing, start, end)
        if start in existing or end in existing
        else existing
    )
    block = f'{start}\n@import url("{managed.name}");\n{end}\n'
    updated = block + existing.lstrip()
    import_changed = not user_chrome.is_file() or user_chrome.read_text() != updated
    if import_changed:
        atomic_text(user_chrome, updated)
    changed = []
    if css_changed:
        changed.append(str(managed))
    if import_changed:
        changed.append(str(user_chrome))
    return changed, bool(changed)


def _scan_zellij_kdl(content: str) -> tuple[str, list[int]]:
    """Mask comments and track brace depth without changing source offsets."""
    masked = list(content)
    depths = [-1] * (len(content) + 1)
    depth = 0
    index = 0
    mode = "code"
    block_depth = 0
    raw_end = ""
    while index < len(content):
        depths[index] = depth if mode == "code" else -1
        pair = content[index : index + 2]
        if mode == "line-comment":
            if content[index] == "\n":
                mode = "code"
            else:
                masked[index] = " "
            index += 1
            continue
        if mode == "block-comment":
            if pair == "/*":
                masked[index : index + 2] = "  "
                block_depth += 1
                index += 2
                continue
            if pair == "*/":
                masked[index : index + 2] = "  "
                block_depth -= 1
                index += 2
                if block_depth == 0:
                    mode = "code"
                continue
            if content[index] != "\n":
                masked[index] = " "
            index += 1
            continue
        if mode == "string":
            if content[index] == "\\":
                index += min(2, len(content) - index)
                continue
            if content[index] == '"':
                mode = "code"
            index += 1
            continue
        if mode == "raw-string":
            if content.startswith(raw_end, index):
                index += len(raw_end)
                mode = "code"
            else:
                index += 1
            continue

        if pair == "//":
            masked[index : index + 2] = "  "
            mode = "line-comment"
            index += 2
        elif pair == "/*":
            masked[index : index + 2] = "  "
            mode = "block-comment"
            block_depth = 1
            index += 2
        elif content[index] == '"':
            mode = "string"
            index += 1
        elif content[index] == "r":
            raw = re.match(r'r(#+)"', content[index:])
            if raw:
                raw_end = '"' + raw.group(1)
                mode = "raw-string"
                index += len(raw.group(0))
            else:
                index += 1
        elif content[index] == "{":
            depth += 1
            index += 1
        elif content[index] == "}":
            depth -= 1
            if depth < 0:
                raise ValueError("Zellij KDL has an unmatched closing brace")
            index += 1
        else:
            index += 1
    depths[len(content)] = depth
    if mode == "block-comment":
        raise ValueError("Zellij KDL has an unterminated block comment")
    if mode in {"string", "raw-string"}:
        raise ValueError("Zellij KDL has an unterminated string")
    if depth:
        raise ValueError("Zellij KDL has unbalanced braces")
    return "".join(masked), depths


def _zellij_root_match(pattern: re.Pattern[str], content: str) -> re.Match[str] | None:
    masked, depths = _scan_zellij_kdl(content)
    return next(
        (match for match in pattern.finditer(masked) if depths[match.start()] == 0),
        None,
    )


def _zellij_theme_option(content: str) -> re.Match[str] | None:
    return _zellij_root_match(ZELLIJ_THEME_OPTION, content)


def _remove_zellij_legacy_block(content: str) -> str:
    starts = content.count(ZELLIJ_MANAGED_START)
    ends = content.count(ZELLIJ_MANAGED_END)
    if starts != ends or starts > 1:
        raise ValueError("incomplete or duplicate THPM managed block")
    if starts and content.index(ZELLIJ_MANAGED_START) > content.index(ZELLIJ_MANAGED_END):
        raise ValueError("reversed THPM managed block")
    return (
        remove_managed_block(content, ZELLIJ_MANAGED_START, ZELLIJ_MANAGED_END)
        if starts
        else content
    )


def _environment_path(value: str) -> Path:
    expanded = Path(os.path.expandvars(os.path.expanduser(value)))
    return (
        expanded.resolve()
        if expanded.is_absolute()
        else (Path.cwd() / expanded).resolve()
    )


def _zellij_config_path(paths: Paths) -> Path:
    configured = os.environ.get("ZELLIJ_CONFIG_FILE")
    if configured:
        return _environment_path(configured)
    directory = os.environ.get("ZELLIJ_CONFIG_DIR")
    if directory:
        return _environment_path(directory) / "config.kdl"
    return paths.config_home / "zellij/config.kdl"


def _zellij_paths(paths: Paths) -> tuple[Path, Path]:
    config = _zellij_config_path(paths)
    content = config.read_text() if config.is_file() else ""
    selected = _zellij_root_match(ZELLIJ_THEME_DIR_OPTION, content)
    if selected:
        try:
            raw_directory = json.loads(selected.group("value"))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"Zellij theme_dir is invalid: {config}") from exc
        directory = Path(os.path.expandvars(os.path.expanduser(raw_directory)))
        if not directory.is_absolute():
            raise ValueError(
                f"Zellij theme_dir must be absolute for reliable live reload: {config}"
            )
        theme_directory = directory.resolve()
    else:
        default_config = paths.config_home / "zellij/config.kdl"
        if config != default_config:
            raise ValueError(
                "custom Zellij config locations require an absolute root-level "
                f"theme_dir: {config}"
            )
        theme_directory = config.parent / "themes"
    return config, theme_directory / "thpm.kdl"


def _zellij_config_tick_remaining_ns(path: Path) -> int | None:
    destination = path.resolve() if path.is_symlink() else path
    if not destination.is_file():
        return None
    previous_mtime_second = destination.stat().st_mtime_ns // 1_000_000_000
    next_second_ns = (previous_mtime_second + 1) * 1_000_000_000
    remaining_ns = next_second_ns - time.time_ns()
    if remaining_ns > 1_100_000_000:
        raise RuntimeError(
            f"Zellij configuration has an unsupported future timestamp: {path}"
        )
    return remaining_ns


def _wait_for_zellij_config_tick(path: Path) -> None:
    remaining_ns = _zellij_config_tick_remaining_ns(path)
    if remaining_ns is not None and remaining_ns >= 0:
        # Zellij 0.44 only reports a strictly newer integer mtime. Wait before
        # re-reading the config so edits made during the wait cannot be lost.
        time.sleep((remaining_ns + 1_000_000) / 1_000_000_000)


def _write_zellij_config(path: Path, content: str) -> None:
    destination = path.resolve() if path.is_symlink() else path
    if destination.exists() and not destination.is_file():
        raise RuntimeError(f"Zellij configuration is not a file: {path}")
    mode = destination.stat().st_mode & 0o777 if destination.is_file() else 0o644
    atomic_text(destination, content, mode)


def _read_zellij_state(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        saved = json.loads(path.read_text())
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(saved, dict):
        return None
    option = saved.get("themeOption")
    if not isinstance(saved.get("configExisted"), bool) or not isinstance(option, str):
        return None
    if option:
        try:
            selected = _zellij_theme_option(option)
        except ValueError:
            return None
        if (
            "\n" in option
            or selected is None
            or selected.span() != (0, len(option))
            or selected.group("name") == "thpm-current"
        ):
            return None
    for key in ("configFile", "themeTarget"):
        value = saved.get(key)
        if value is not None and (
            not isinstance(value, str) or not value or not Path(value).is_absolute()
        ):
            return None
    return saved


def _validate_zellij_takeover(paths: Paths, content: str, source: Path) -> None:
    declaration = _zellij_root_match(ZELLIJ_THEME_DECLARATION, content)
    if declaration is None:
        raise ValueError(f"Zellij theme has no theme declaration: {source}")
    config, target = _zellij_paths(paths)
    _zellij_config_tick_remaining_ns(config)
    existing = config.read_text() if config.is_file() else ""
    try:
        existing = _remove_zellij_legacy_block(existing)
    except ValueError as exc:
        raise RuntimeError("Zellij legacy THPM block is invalid") from exc
    selected = _zellij_theme_option(existing)
    state = paths.zellij_theme_state_file
    saved = _read_zellij_state(state)
    if state.exists() and saved is None and (
        selected is None or selected.group("name") == "thpm-current"
    ):
        raise RuntimeError(f"Zellij restoration state is invalid: {state}")
    if saved and (
        Path(str(saved.get("configFile", paths.config_home / "zellij/config.kdl")))
        != config
        or Path(
            str(saved.get("themeTarget", paths.config_home / "zellij/themes/thpm.kdl"))
        )
        != target
    ):
        raise RuntimeError("Zellij configuration location changed; disable the integration before re-enabling it")


def _current_plugin_sources(paths: Paths, plugin_id: str) -> tuple[Path, ...]:
    source_plugins = (
        ("discord", "discord-system24")
        if plugin_id in {"discord", "discord-system24"}
        else (plugin_id,)
    )
    names = [
        name
        for source_plugin in source_plugins
        for name in (
            *BY_ID[source_plugin].theme_assets,
            *([GENERATED[source_plugin]] if source_plugin in GENERATED else []),
        )
    ]
    installed = paths.config_home / "omarchy/themes"
    return tuple(paths.current_theme / name for name in names) + tuple(
        candidate
        for name in names
        for candidate in installed.glob(f"*/{name}")
    )


def _cleanup_browser(paths: Paths, plugin_id: str, *, assume_legacy: bool) -> tuple[list[str], list[str]]:
    base = paths.home / (".mozilla/firefox" if plugin_id == "firefox" else ".zen")
    sources = _current_plugin_sources(paths, plugin_id)
    changed: list[str] = []
    warnings: list[str] = []
    start, end = "/* thpm-import-start */", "/* thpm-import-end */"
    for chrome in (path for path in base.rglob("chrome") if path.is_dir()):
        managed = chrome / f"thpm-{plugin_id}.css"
        item_changed, item_warnings = _cleanup_optional_asset(
            paths,
            _target_key(f"browser-{plugin_id}", managed),
            managed,
            legacy_owned=assume_legacy and _matches_sources(managed, sources),
        )
        changed.extend(item_changed)
        warnings.extend(item_warnings)
        user_chrome = chrome / "userChrome.css"
        if user_chrome.is_file():
            existing = user_chrome.read_text()
            if (start in existing) != (end in existing):
                warnings.append(f"preserved incomplete THPM browser import block: {user_chrome}")
            elif start in existing:
                updated = remove_managed_block(existing, start, end)
                if updated != existing:
                    if updated.strip():
                        atomic_text(user_chrome, updated)
                    else:
                        user_chrome.unlink()
                    changed.append(str(user_chrome))
    return changed, warnings


def cleanup_managed_outputs(
    paths: Paths, plugin_id: str, *, assume_legacy: bool = False
) -> tuple[list[str], list[str]]:
    """Restore or remove output deployed by a generated/hybrid integration."""
    changed: list[str] = []
    warnings: list[str] = []
    targets = _standard_output_targets(paths)
    if plugin_id in targets:
        target = targets[plugin_id]
        item_changed, item_warnings = _cleanup_optional_asset(
            paths,
            f"generated-{plugin_id}",
            target,
            legacy_owned=assume_legacy
            and _matches_sources(target, _current_plugin_sources(paths, plugin_id)),
        )
        changed.extend(item_changed)
        warnings.extend(item_warnings)
    elif plugin_id in {"discord", "discord-system24"}:
        for directory in _discord_directories(paths):
            target = directory / "vencord.theme.css"
            item_changed, item_warnings = _cleanup_optional_asset(
                paths,
                _target_key("discord", target),
                target,
                legacy_owned=assume_legacy
                and _matches_sources(
                    target, _current_plugin_sources(paths, plugin_id)
                ),
            )
            changed.extend(item_changed)
            warnings.extend(item_warnings)
    elif plugin_id in {"firefox", "zen"}:
        item_changed, item_warnings = _cleanup_browser(
            paths, plugin_id, assume_legacy=assume_legacy
        )
        changed.extend(item_changed)
        warnings.extend(item_warnings)
    generated = GENERATED.get(plugin_id)
    if generated:
        rendered = paths.current_theme / generated
        if rendered.is_file():
            rendered.unlink()
            changed.append(str(rendered))
    return changed, warnings


def reload_restored_integration(plugin_id: str, changed: list[str]) -> tuple[list[str], list[str]]:
    if plugin_id != "swaync" or not changed or not shutil.which("swaync-client"):
        return [], []
    try:
        return _reload("swaync"), []
    except RuntimeError as exc:
        return [], [str(exc)]


def _zellij_selected_content(
    content: str,
) -> tuple[str, re.Match[str] | None, str]:
    existing = _remove_zellij_legacy_block(content)
    selected = _zellij_theme_option(existing)
    if selected:
        start, end = selected.span("value")
        updated = existing[:start] + '"thpm-current"' + existing[end:]
    else:
        updated = 'theme "thpm-current"\n' + (
            "\n" + existing.lstrip() if existing.strip() else ""
        )
    if not updated.endswith("\n"):
        updated += "\n"
    return existing, selected, updated


def _select_zellij_theme(
    paths: Paths, config: Path, target: Path, *, refresh: bool = False
) -> tuple[Path, bool]:
    config_existed = config.exists() or config.is_symlink()
    original = config.read_text() if config_existed else ""
    try:
        existing, selected, updated = _zellij_selected_content(original)
    except ValueError as exc:
        raise RuntimeError("Zellij legacy THPM block is invalid") from exc
    if refresh or updated != original:
        _wait_for_zellij_config_tick(config)
        # Re-read after the wait so a concurrent user edit is transformed or
        # rejected rather than overwritten with stale pre-wait content.
        config_existed = config.exists() or config.is_symlink()
        original = config.read_text() if config_existed else ""
        try:
            existing, selected, updated = _zellij_selected_content(original)
        except ValueError as exc:
            raise RuntimeError("Zellij legacy THPM block is invalid") from exc

    state_file = paths.zellij_theme_state_file
    saved = _read_zellij_state(state_file)
    if state_file.exists() and saved is None and (
        selected is None or selected.group("name") == "thpm-current"
    ):
        raise RuntimeError(f"Zellij restoration state is invalid: {state_file}")
    if saved is None:
        previous = ""
        if selected and selected.group("name") != "thpm-current":
            previous = existing[selected.start() : selected.end()]
        atomic_text(
            state_file,
            json.dumps(
                {
                    "configExisted": config_existed,
                    "themeOption": previous,
                    "configFile": str(config),
                    "themeTarget": str(target),
                },
                separators=(",", ":"),
            )
            + "\n",
        )
    config_changed = updated != original
    if config_changed or refresh:
        # Zellij watches config.kdl, not files under theme_dir. Rewriting the
        # selected config after installing a changed external theme makes
        # running sessions reparse the newly completed theme file.
        _write_zellij_config(config, updated)
    return config, config_changed or refresh


def cleanup_zellij(paths: Paths) -> tuple[list[str], list[str]]:
    """Relinquish THPM's Zellij selection and restore the previous/default state."""
    state = paths.zellij_theme_state_file
    saved = _read_zellij_state(state)
    if state.exists() and saved is None:
        return [], [f"preserved Zellij configuration because restoration state is invalid: {state}"]
    if saved:
        config = Path(
            str(saved.get("configFile", paths.config_home / "zellij/config.kdl"))
        )
        target = Path(
            str(
                saved.get(
                    "themeTarget", paths.config_home / "zellij/themes/thpm.kdl"
                )
            )
        )
    else:
        try:
            config, target = _zellij_paths(paths)
        except (OSError, UnicodeError, ValueError) as exc:
            return [], [f"preserved Zellij configuration because its paths are invalid: {exc}"]
    try:
        _wait_for_zellij_config_tick(config)
    except RuntimeError as exc:
        return [], [f"preserved Zellij configuration because it cannot be refreshed safely: {exc}"]
    original = config.read_text() if config.is_file() else ""
    try:
        without_legacy = _remove_zellij_legacy_block(original)
    except ValueError:
        return [], ["preserved Zellij configuration because its legacy THPM block is invalid"]
    try:
        selected = _zellij_theme_option(without_legacy) if config.is_file() else None
    except ValueError:
        return [], ["preserved Zellij configuration because its KDL is invalid"]

    changed: list[str] = []
    warnings: list[str] = []
    config_existed = bool(saved.get("configExisted", True)) if saved else True
    previous = str(saved.get("themeOption", "")) if saved else ""
    if config.is_file():
        updated = without_legacy
        if selected and selected.group("name") == "thpm-current":
            start, end = selected.span()
            updated = updated[:start] + previous + updated[end:]
        updated = updated.lstrip("\n")
        if updated and not updated.endswith("\n"):
            updated += "\n"
        if updated != original:
            if not config_existed and not updated.strip():
                config.unlink()
            else:
                _write_zellij_config(config, updated)
            changed.append(str(config))
    target_key = _target_key("zellij-theme", target)
    target_changed, target_warnings = _cleanup_optional_asset(
        paths,
        target_key,
        target,
        legacy_owned=_matches_normalized_zellij_source(paths, target),
    )
    changed.extend(target_changed)
    warnings.extend(target_warnings)
    if target.exists() and not target_changed and not target_warnings:
        warnings.append(f"preserved untracked Zellij theme instead of deleting it: {target}")
    target_state, _backup = _asset_state_paths(paths, target_key)
    if not target_state.exists():
        state.unlink(missing_ok=True)
    return changed, warnings


def _normalized_zellij_theme(source: Path) -> str:
    content = source.read_text()
    declaration = _zellij_root_match(ZELLIJ_THEME_DECLARATION, content)
    if declaration is None:
        raise ValueError(f"Zellij theme has no theme declaration: {source}")
    start, end = declaration.span("name")
    return content[:start] + "thpm-current" + content[end:]


def _zellij_rgb(value: str) -> str:
    return " ".join(str(int(value[index : index + 2], 16)) for index in (1, 3, 5))


def _generated_zellij_theme(colors_path: Path) -> str:
    colors = load_palette(colors_path)

    def color(name: str) -> str:
        return _zellij_rgb(colors[name])

    border = _zellij_rgb(colors.get("active_border_color", colors["blue"]))
    sections = {
        "text_unselected": ("fg", "bg", "red", "green", "blue", "magenta"),
        "text_selected": (
            "bright_fg",
            "selection",
            "bright_red",
            "bright_green",
            "bright_blue",
            "bright_magenta",
        ),
        "ribbon_selected": (
            "bright_fg",
            "blue",
            "bright_red",
            "bright_green",
            "bright_cyan",
            "bright_magenta",
        ),
        "ribbon_unselected": (
            "fg",
            "lighter_bg",
            "red",
            "green",
            "cyan",
            "magenta",
        ),
        "table_cell_selected": (
            "bright_fg",
            "selection",
            "bright_red",
            "bright_green",
            "bright_blue",
            "bright_magenta",
        ),
        "table_cell_unselected": (
            "fg",
            "bg",
            "red",
            "green",
            "blue",
            "magenta",
        ),
        "list_selected": (
            "bright_fg",
            "selection",
            "bright_red",
            "bright_green",
            "bright_blue",
            "bright_magenta",
        ),
        "list_unselected": ("fg", "bg", "red", "green", "blue", "magenta"),
    }
    lines = ["themes {", "    thpm-current {"]
    for section, names in sections.items():
        lines.extend(
            [
                f"        {section} {{",
                f"            base {color(names[0])}",
                f"            background {color(names[1])}",
                f"            emphasis_0 {color(names[2])}",
                f"            emphasis_1 {color(names[3])}",
                f"            emphasis_2 {color(names[4])}",
                f"            emphasis_3 {color(names[5])}",
                "        }",
            ]
        )
    lines.extend(
        [
            "        table_title {",
            f"            base {color('blue')}",
            "            background 0",
            f"            emphasis_0 {color('red')}",
            f"            emphasis_1 {color('green')}",
            f"            emphasis_2 {color('cyan')}",
            f"            emphasis_3 {color('magenta')}",
            "        }",
            "        frame_selected {",
            f"            base {border}",
            "            background 0",
            f"            emphasis_0 {color('red')}",
            f"            emphasis_1 {color('green')}",
            f"            emphasis_2 {color('yellow')}",
            f"            emphasis_3 {color('cyan')}",
            "        }",
            "        frame_highlight {",
            f"            base {color('bright_cyan')}",
            "            background 0",
            f"            emphasis_0 {color('bright_red')}",
            f"            emphasis_1 {color('bright_yellow')}",
            f"            emphasis_2 {color('bright_green')}",
            f"            emphasis_3 {color('bright_magenta')}",
            "        }",
            "        exit_code_success {",
            f"            base {color('green')}",
            "            background 0",
            f"            emphasis_0 {color('bright_green')}",
            f"            emphasis_1 {color('bg')}",
            f"            emphasis_2 {color('cyan')}",
            f"            emphasis_3 {color('blue')}",
            "        }",
            "        exit_code_error {",
            f"            base {color('red')}",
            "            background 0",
            f"            emphasis_0 {color('yellow')}",
            "            emphasis_1 0",
            "            emphasis_2 0",
            "            emphasis_3 0",
            "        }",
            "        multiplayer_user_colors {",
            f"            player_1 {color('magenta')}",
            f"            player_2 {color('cyan')}",
            f"            player_3 {color('green')}",
            f"            player_4 {color('yellow')}",
            f"            player_5 {color('blue')}",
            f"            player_6 {color('orange')}",
            f"            player_7 {color('red')}",
            f"            player_8 {color('bright_magenta')}",
            f"            player_9 {color('bright_cyan')}",
            f"            player_10 {color('brown')}",
            "        }",
            "    }",
            "}",
        ]
    )
    return "\n".join(lines) + "\n"


def _matches_normalized_zellij_source(paths: Paths, target: Path) -> bool:
    if not target.is_file() or target.is_symlink():
        return False
    sources = (paths.current_theme / "zellij.kdl",) + tuple(
        (paths.config_home / "omarchy/themes").glob("*/zellij.kdl")
    )
    palettes = (paths.current_theme / "colors.toml",) + tuple(
        (paths.config_home / "omarchy/themes").glob("*/colors.toml")
    )
    try:
        target_data = target.read_text()
        return any(
            source.is_file()
            and not source.is_symlink()
            and _normalized_zellij_theme(source) == target_data
            for source in sources
        ) or any(
            palette.is_file()
            and not palette.is_symlink()
            and _generated_zellij_theme(palette) == target_data
            for palette in palettes
        )
    except (OSError, UnicodeError, ValueError):
        return False


def _install_zellij_theme(paths: Paths, content: str, target: Path) -> bool:
    paths.thpm_state_dir.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=".zellij-theme-", dir=paths.thpm_state_dir, text=True
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
        return _install_optional_asset(
            paths,
            _target_key("zellij-theme", target),
            temporary,
            target,
            legacy_owned=_matches_normalized_zellij_source(paths, target),
        )
    finally:
        temporary.unlink(missing_ok=True)


def _reload(plugin_id: str) -> list[str]:
    commands = {
        "spotify": ["spicetify", "apply"],
        "vicinae": ["vicinae", "theme", "set", "thpm"],
        "swaync": ["swaync-client", "--reload-css"],
        "cava": ["pkill", "-USR2", "cava"],
    }
    command = commands.get(plugin_id)
    if not command:
        return []
    if plugin_id == "cava":
        if not shutil.which("pgrep"):
            return []
        running = subprocess.run(
            ["pgrep", "-x", "cava"],
            text=True,
            capture_output=True,
            check=False,
            timeout=2,
        )
        if running.returncode != 0:
            return []
    if not shutil.which(command[0]):
        raise RuntimeError(f"{plugin_id}: reload command not found: {command[0]}")
    try:
        completed = subprocess.run(
            command, text=True, capture_output=True, check=False, timeout=5
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{plugin_id}: reload timed out") from exc
    if completed.returncode != 0:
        detail = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or f"exit {completed.returncode}"
        )
        raise RuntimeError(f"{plugin_id}: reload failed: {detail}")
    return [" ".join(command)]


def _result(
    plugin_id: str,
    changed: list[str],
    actions: list[str],
    warnings: list[str] | None = None,
) -> ApplyResult:
    status = "applied" if changed or actions else "unchanged"
    message = (
        "integration applied"
        if status == "applied"
        else "integration already up to date"
    )
    return ApplyResult(plugin_id, status, changed, actions, message, warnings or [])


def apply(plugin_id: str, paths: Paths) -> ApplyResult:
    if plugin_id not in BY_ID:
        raise KeyError(plugin_id)
    if plugin_id == "gtk-css-compat":
        return apply_gtk(paths)
    if plugin_id == "vscode-local-compat":
        return apply_vscode_local(paths)
    if plugin_id == "zed-extra":
        return _apply_zed_asset(paths)
    paths.current_theme.mkdir(parents=True, exist_ok=True)
    changed: list[str] = []
    warnings: list[str] = []
    home, config = paths.home, paths.config_home
    targets = _standard_output_targets(paths)
    candidates = {
        "superfile": ("superfile.toml", GENERATED["superfile"]),
        "cava": ("cava_theme", GENERATED["cava"]),
    }

    if plugin_id == "zellij":
        source = paths.current_theme / "zellij.kdl"
        colors = paths.current_theme / "colors.toml"
        if source.is_file():
            content = _normalized_zellij_theme(source)
        elif colors.is_file():
            content = _generated_zellij_theme(colors)
        else:
            cleanup_changed, cleanup_warnings = cleanup_zellij(paths)
            changed.extend(cleanup_changed)
            warnings.extend(cleanup_warnings)
            return _result(plugin_id, changed, [], warnings)
        _validate_zellij_takeover(paths, content, source if source.is_file() else colors)
        zellij_config, zellij_target = _zellij_paths(paths)
        theme_changed = _install_zellij_theme(paths, content, zellij_target)
        if theme_changed:
            changed.append(str(zellij_target))
        config_file, config_changed = _select_zellij_theme(
            paths, zellij_config, zellij_target, refresh=theme_changed
        )
        if config_changed:
            changed.append(str(config_file))
    elif plugin_id in targets:
        source_names = candidates.get(plugin_id, (GENERATED[plugin_id],))
        source = next(
            (
                paths.current_theme / name
                for name in source_names
                if (paths.current_theme / name).is_file()
            ),
            None,
        )
        if source is None:
            raise RuntimeError(f"{plugin_id}: expected theme output was not found")
        if source.name in set(GENERATED.values()):
            _ensure_generated_output_is_rendered(source)
        if _install_optional_asset(
            paths,
            f"generated-{plugin_id}",
            source,
            targets[plugin_id],
            legacy_owned=_matches_sources(
                targets[plugin_id], _current_plugin_sources(paths, plugin_id)
            ),
        ):
            changed.append(str(targets[plugin_id]))
        if plugin_id == "nwg-dock" and changed:
            warnings.append("restart nwg-dock-hyprland to see theme changes")
    elif plugin_id in OPTIONAL_ASSET_PLUGINS:
        for key, asset_name, target in _optional_asset_targets(paths, plugin_id):
            source = paths.current_theme / asset_name
            legacy_owned = _matches_installed_theme_asset(
                paths, target, asset_name
            )
            if source.is_file():
                if _install_optional_asset(
                    paths, key, source, target, legacy_owned=legacy_owned
                ):
                    changed.append(str(target))
            else:
                item_changed, item_warnings = _cleanup_optional_asset(
                    paths, key, target, legacy_owned=legacy_owned
                )
                changed.extend(item_changed)
                warnings.extend(item_warnings)
        if plugin_id == "swaync" and not shutil.which("swaync-client"):
            return _result(plugin_id, changed, [], warnings)
    elif plugin_id in {"discord", "discord-system24"}:
        source_names = (
            ("vencord.theme.css", GENERATED[plugin_id])
            if plugin_id == "discord"
            else ("vencord-system24.theme.css", GENERATED[plugin_id])
        )
        directories = [
            directory for directory in _discord_directories(paths) if directory.is_dir()
        ]
        if not directories:
            return ApplyResult(
                plugin_id,
                "skipped",
                message="no supported Discord client theme directory was found",
            )
        source = next(
            (
                paths.current_theme / name
                for name in source_names
                if (paths.current_theme / name).is_file()
            ),
            None,
        )
        if source is None:
            raise RuntimeError(
                f"{plugin_id}: no theme asset or generated stylesheet was found"
            )
        if source.name in set(GENERATED.values()):
            _ensure_generated_output_is_rendered(source)
        for directory in directories:
            target = directory / "vencord.theme.css"
            if _install_optional_asset(
                paths,
                _target_key("discord", target),
                source,
                target,
                legacy_owned=_matches_sources(
                    target, _current_plugin_sources(paths, plugin_id)
                ),
            ):
                changed.append(str(target))
    elif plugin_id in {"firefox", "zen"}:
        base = home / (".mozilla/firefox" if plugin_id == "firefox" else ".zen")
        browser_paths, browser_changed = _browser_import(paths, plugin_id, base)
        if browser_changed:
            changed.extend(browser_paths)
    elif plugin_id == "steam":
        script = home / ".local/share/steam-adwaita/install.py"
        if not script.is_file():
            return ApplyResult(
                plugin_id, "skipped", message="steam-adwaita installer is not installed"
            )
        try:
            completed = subprocess.run(
                [str(script), "--color-theme", "omarchy"],
                cwd=script.parent,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("steam: steam-adwaita timed out") from exc
        if completed.returncode != 0:
            detail = (
                completed.stderr.strip()
                or completed.stdout.strip()
                or f"exit {completed.returncode}"
            )
            raise RuntimeError(f"steam: steam-adwaita failed: {detail}")
        return _result(plugin_id, [], ["steam-adwaita --color-theme omarchy"])

    try:
        actions = _reload(plugin_id) if changed else []
    except RuntimeError as exc:
        raise ApplyFailure(str(exc), changed=changed, warnings=warnings) from exc
    return _result(plugin_id, changed, actions, warnings)


def apply_enabled(
    paths: Paths,
    enabled: dict[str, bool],
    events: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    results: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    plugins = [plugin for plugin in PLUGINS if enabled.get(plugin.id)]
    total = len(plugins)
    if events is not None:
        events({"type": "integrations_started", "total": total})
    for current, plugin in enumerate(plugins, start=1):
        if events is not None:
            events(
                {
                    "type": "integration_started",
                    "plugin": plugin.id,
                    "current": current,
                    "total": total,
                }
            )
        ready, missing, readiness_warnings = inspect_readiness(plugin.id, paths)
        if not ready:
            result = ApplyResult(
                plugin.id,
                "skipped",
                message="missing prerequisites: " + ", ".join(missing),
                warnings=readiness_warnings,
            )
        else:
            try:
                result = apply(plugin.id, paths)
            except ApplyFailure as exc:
                result = ApplyResult(
                    plugin.id,
                    "failed",
                    changed=exc.changed,
                    message=str(exc),
                    warnings=exc.warnings,
                )
                errors.append({"plugin": plugin.id, "message": str(exc)})
            except Exception as exc:  # isolate plugins at the hook boundary
                result = ApplyResult(plugin.id, "failed", message=str(exc))
                errors.append({"plugin": plugin.id, "message": str(exc)})
        if result.status == "failed" and not any(
            error["plugin"] == plugin.id for error in errors
        ):
            errors.append({"plugin": plugin.id, "message": result.message})
        result_payload = result.json()
        results.append(result_payload)
        for warning in result.warnings:
            warnings.append({"plugin": plugin.id, "message": warning})
        if result.status == "skipped":
            warnings.append({"plugin": plugin.id, "message": result.message})
        if events is not None:
            events(
                {
                    "type": "integration_finished",
                    "plugin": plugin.id,
                    "current": current,
                    "total": total,
                    "status": result.status,
                    "message": result.message,
                }
            )
    counts = {
        status: sum(1 for result in results if result["status"] == status)
        for status in ("applied", "unchanged", "skipped", "failed")
    }
    changed = [path for result in results for path in result["changed"]]
    return {
        "results": results,
        "counts": counts,
        "changed": changed,
        "errors": errors,
        "warnings": warnings,
    }
