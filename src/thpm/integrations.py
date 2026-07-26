from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
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
from .paths import Paths
from .registry import BY_ID, PLUGINS

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
    r'^(?P<indent>[ \t]*)theme[ \t]+"(?P<name>[^"\n]*)"[ \t]*(?://[^\n]*)?$',
    re.MULTILINE,
)
UNRESOLVED_PLACEHOLDER = re.compile(r"\{\{\s*[^{}]+?\s*\}\}")
ZELLIJ_RESTART_WARNING = "restart active Zellij sessions to load the updated theme"
OPTIONAL_ASSET_PLUGINS = {
    "branding",
    "typora",
    "swaync",
    "windsurf",
    "cliamp",
    "zed-extra",
}


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
        "zed-extra": (("zed-extra", "zed.json", config / "zed/themes/omarchy.json"),),
    }
    return targets.get(plugin_id, ())


def _asset_state_paths(paths: Paths, key: str) -> tuple[Path, Path]:
    root = paths.managed_asset_state_dir
    return root / f"{key}.json", root / f"{key}.backup"


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
    paths: Paths, key: str, source: Path, target: Path
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
            existed = target_data is not None and target_data != source_data
            if existed and target_data is not None:
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(target_data)
            saved = {
                "existed": existed,
                "priorType": "file",
                "priorSha256": target_digest if existed else "",
                "priorMode": target_mode if existed else 0o644,
            }

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
    paths: Paths, key: str, target: Path
) -> tuple[list[str], list[str]]:
    """Restore one displaced file, preserving targets changed outside THPM."""
    state_file, backup = _asset_state_paths(paths, key)
    invalid = f"could not restore optional asset because state is invalid: {state_file}"
    saved = _read_asset_state(state_file)
    if saved is None:
        return [], [invalid] if state_file.exists() else []
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
    paths: Paths, plugin_id: str
) -> tuple[list[str], list[str]]:
    changed: list[str] = []
    warnings: list[str] = []
    for key, _asset_name, target in _optional_asset_targets(paths, plugin_id):
        item_changed, item_warnings = _cleanup_optional_asset(paths, key, target)
        changed.extend(item_changed)
        warnings.extend(item_warnings)
    return changed, warnings


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

    if plugin_id == "zellij" and not assets:
        # Cleanup must remain actionable after Zellij is uninstalled.
        missing = []
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
    _, css_changed = _copy_first(paths, candidates, managed)
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
    if option and (
        "\n" in option
        or ZELLIJ_THEME_OPTION.fullmatch(option) is None
        or ZELLIJ_THEME_OPTION.fullmatch(option).group("name") == "thpm-current"
    ):
        return None
    return saved


def _validate_zellij_takeover(paths: Paths, source: Path) -> None:
    content = source.read_text()
    if not ZELLIJ_THEME_DECLARATION.search(content):
        raise ValueError(f"Zellij theme has no theme declaration: {source}")
    config = paths.config_home / "zellij/config.kdl"
    existing = config.read_text() if config.is_file() else ""
    if (ZELLIJ_MANAGED_START in existing) != (ZELLIJ_MANAGED_END in existing):
        raise RuntimeError("Zellij legacy THPM block is incomplete")
    if ZELLIJ_MANAGED_START in existing:
        existing = remove_managed_block(
            existing, ZELLIJ_MANAGED_START, ZELLIJ_MANAGED_END
        )
    selected = ZELLIJ_THEME_OPTION.search(existing)
    state = paths.zellij_theme_state_file
    if state.exists() and _read_zellij_state(state) is None and (
        selected is None or selected.group("name") == "thpm-current"
    ):
        raise RuntimeError(f"Zellij restoration state is invalid: {state}")


def _select_zellij_theme(paths: Paths) -> tuple[Path, bool]:
    config = paths.config_home / "zellij/config.kdl"
    config_existed = config.is_file()
    original = config.read_text() if config_existed else ""
    existing = original
    if ZELLIJ_MANAGED_START in existing or ZELLIJ_MANAGED_END in existing:
        existing = remove_managed_block(
            existing, ZELLIJ_MANAGED_START, ZELLIJ_MANAGED_END
        )
    selected = ZELLIJ_THEME_OPTION.search(existing)
    state_file = paths.zellij_theme_state_file
    saved = _read_zellij_state(state_file)
    if state_file.exists() and saved is None and (
        selected is None or selected.group("name") == "thpm-current"
    ):
        raise RuntimeError(f"Zellij restoration state is invalid: {state_file}")
    if saved is None:
        previous = ""
        if selected and selected.group("name") != "thpm-current":
            previous = selected.group(0)
        atomic_text(
            state_file,
            json.dumps(
                {"configExisted": config_existed, "themeOption": previous},
                separators=(",", ":"),
            )
            + "\n",
        )
    if selected:
        updated = ZELLIJ_THEME_OPTION.sub(
            lambda match: f'{match.group("indent")}theme "thpm-current"',
            existing,
            count=1,
        )
    else:
        updated = 'theme "thpm-current"\n' + (
            "\n" + existing.lstrip() if existing.strip() else ""
        )
    if not updated.endswith("\n"):
        updated += "\n"
    if updated != original:
        atomic_text(config, updated)
    return config, updated != original


def cleanup_zellij(paths: Paths) -> tuple[list[str], list[str]]:
    """Relinquish THPM's Zellij selection and restore the previous/default state."""
    config = paths.config_home / "zellij/config.kdl"
    target = paths.config_home / "zellij/themes/thpm.kdl"
    state = paths.zellij_theme_state_file
    saved = _read_zellij_state(state)
    if state.exists() and saved is None:
        return [], [f"preserved Zellij configuration because restoration state is invalid: {state}"]
    original = config.read_text() if config.is_file() else ""
    if (ZELLIJ_MANAGED_START in original) != (ZELLIJ_MANAGED_END in original):
        return [], ["preserved Zellij configuration because its legacy THPM block is incomplete"]

    changed: list[str] = []
    config_existed = bool(saved.get("configExisted", True)) if saved else True
    previous = str(saved.get("themeOption", "")) if saved else ""
    if config.is_file():
        updated = original
        if ZELLIJ_MANAGED_START in updated:
            updated = remove_managed_block(
                updated, ZELLIJ_MANAGED_START, ZELLIJ_MANAGED_END
            )
        selected = ZELLIJ_THEME_OPTION.search(updated)
        if selected and selected.group("name") == "thpm-current":
            updated = ZELLIJ_THEME_OPTION.sub(previous, updated, count=1)
        updated = updated.lstrip("\n")
        if updated and not updated.endswith("\n"):
            updated += "\n"
        if updated != original:
            if not config_existed and not updated.strip():
                config.unlink()
            else:
                atomic_text(config, updated)
            changed.append(str(config))
    if target.exists():
        target.unlink()
        changed.append(str(target))
    state.unlink(missing_ok=True)
    return changed, []


def _install_zellij_theme(source: Path, target: Path) -> bool:
    content = source.read_text()
    if not ZELLIJ_THEME_DECLARATION.search(content):
        raise ValueError(f"Zellij theme has no theme declaration: {source}")
    normalized = ZELLIJ_THEME_DECLARATION.sub(
        lambda match: f"{match.group('prefix')}thpm-current{match.group('suffix')}",
        content,
        count=1,
    )
    changed = not target.is_file() or target.read_text() != normalized
    if changed:
        atomic_text(target, normalized)
    return changed


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
    paths.current_theme.mkdir(parents=True, exist_ok=True)
    changed: list[str] = []
    warnings: list[str] = []
    home, config = paths.home, paths.config_home
    targets: dict[str, Path] = {
        "fish": config / "fish/conf.d/thpm-theme.fish",
        "fzf": config / "fish/conf.d/thpm-fzf.fish",
        "qt6ct": config / "qt6ct/colors/thpm.conf",
        "spotify": config / "spicetify/Themes/Omarchy/color.ini",
        "superfile": config / "superfile/theme/thpm.toml",
        "vicinae": config / "vicinae/themes/thpm.toml",
        "zellij": config / "zellij/themes/thpm.kdl",
        "nwg-dock": config / "nwg-dock-hyprland/thpm.css",
        "cava": config / "cava/themes/thpm",
        "hermes": config / "Hermes/omarchy-theme.json",
        "qutebrowser": config / "qutebrowser/thpm_theme.py",
        "heroic": config / "heroic/themes/thpm.css",
    }
    candidates = {
        "superfile": ("superfile.toml", GENERATED["superfile"]),
        "cava": ("cava_theme", GENERATED["cava"]),
    }

    if plugin_id == "zellij":
        source = paths.current_theme / "zellij.kdl"
        if not source.is_file():
            cleanup_changed, cleanup_warnings = cleanup_zellij(paths)
            changed.extend(cleanup_changed)
            warnings.extend(cleanup_warnings)
            if cleanup_changed:
                warnings.append(ZELLIJ_RESTART_WARNING)
            return _result(plugin_id, changed, [], warnings)
        _validate_zellij_takeover(paths, source)
        if _install_zellij_theme(source, targets[plugin_id]):
            changed.append(str(targets[plugin_id]))
        config_file, config_changed = _select_zellij_theme(paths)
        if config_changed:
            changed.append(str(config_file))
        warnings.append(ZELLIJ_RESTART_WARNING)
    elif plugin_id in targets:
        source_names = candidates.get(plugin_id, (GENERATED[plugin_id],))
        source, copied = _copy_first(paths, source_names, targets[plugin_id])
        if source is None:
            raise RuntimeError(f"{plugin_id}: expected theme output was not found")
        if copied:
            changed.append(str(targets[plugin_id]))
        if plugin_id == "nwg-dock":
            warnings.append("restart nwg-dock-hyprland to see theme changes")
    elif plugin_id in OPTIONAL_ASSET_PLUGINS:
        for key, asset_name, target in _optional_asset_targets(paths, plugin_id):
            source = paths.current_theme / asset_name
            if source.is_file():
                if _install_optional_asset(paths, key, source, target):
                    changed.append(str(target))
            else:
                item_changed, item_warnings = _cleanup_optional_asset(
                    paths, key, target
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
        if not any((paths.current_theme / name).is_file() for name in source_names):
            raise RuntimeError(
                f"{plugin_id}: no theme asset or generated stylesheet was found"
            )
        for directory in directories:
            target = directory / "vencord.theme.css"
            _, copied = _copy_first(paths, source_names, target)
            if copied:
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
        actions = _reload(plugin_id)
    except RuntimeError as exc:
        raise ApplyFailure(str(exc), changed=changed, warnings=warnings) from exc
    return _result(plugin_id, changed, actions, warnings)


def apply_enabled(paths: Paths, enabled: dict[str, bool]) -> dict[str, object]:
    results: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for plugin in PLUGINS:
        if not enabled.get(plugin.id):
            continue
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
        results.append(result.json())
        for warning in result.warnings:
            warnings.append({"plugin": plugin.id, "message": warning})
        if result.status == "skipped":
            warnings.append({"plugin": plugin.id, "message": result.message})
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
