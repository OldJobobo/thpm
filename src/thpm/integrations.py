from __future__ import annotations

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
    "zellij": "thpm-zellij.kdl",
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

    if plugin_id == "gtk-css-compat":
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
    elif plugin_id == "branding" and not assets:
        missing.append("about.txt or screensaver.txt in the active theme")
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
        and plugin_id != "steam"
        and plugin.theme_assets
        and not assets
    ):
        missing.append(" or ".join(plugin.theme_assets) + " in the active theme")

    if plugin_id == "nwg-dock":
        warnings.append(
            "nwg-dock-hyprland has no supported live reload; restart it to see theme changes"
        )
    return not missing, missing, warnings


def _copy_first(
    paths: Paths, candidates: tuple[str, ...], target: Path
) -> tuple[Path | None, bool]:
    for name in candidates:
        source = paths.current_theme / name
        if source.is_file():
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


def _select_zellij_theme(paths: Paths) -> tuple[Path, bool]:
    config = paths.config_home / "zellij/config.kdl"
    original = config.read_text() if config.is_file() else ""
    existing = original
    if ZELLIJ_MANAGED_START in existing or ZELLIJ_MANAGED_END in existing:
        existing = remove_managed_block(
            existing, ZELLIJ_MANAGED_START, ZELLIJ_MANAGED_END
        )
    theme = re.compile(r'^(?P<indent>\s*)theme\s+"[^"]*".*$', re.MULTILINE)
    if theme.search(existing):
        updated = theme.sub(
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
        source = next(
            (
                paths.current_theme / name
                for name in ("zellij.kdl", GENERATED[plugin_id])
                if (paths.current_theme / name).is_file()
            ),
            None,
        )
        if source is None:
            raise RuntimeError("zellij: no theme asset or generated theme was found")
        if _install_zellij_theme(source, targets[plugin_id]):
            changed.append(str(targets[plugin_id]))
        config_file, config_changed = _select_zellij_theme(paths)
        if config_changed:
            changed.append(str(config_file))
    elif plugin_id in targets:
        source_names = candidates.get(plugin_id, (GENERATED[plugin_id],))
        source, copied = _copy_first(paths, source_names, targets[plugin_id])
        if source is None:
            raise RuntimeError(f"{plugin_id}: expected theme output was not found")
        if copied:
            changed.append(str(targets[plugin_id]))
        if plugin_id == "nwg-dock":
            warnings.append("restart nwg-dock-hyprland to see theme changes")
    elif plugin_id == "branding":
        for source_name in ("about.txt", "screensaver.txt"):
            target = config / "omarchy/branding" / source_name
            source, copied = _copy_first(paths, (source_name,), target)
            if source is not None and copied:
                changed.append(str(target))
        if not any(
            (paths.current_theme / name).is_file()
            for name in ("about.txt", "screensaver.txt")
        ):
            return ApplyResult(
                plugin_id, "skipped", message="active theme has no branding assets"
            )
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
    elif plugin_id == "typora":
        source, copied = _copy_first(
            paths, ("typora.css",), config / "Typora/themes/omarchy.css"
        )
        if source is None:
            raise RuntimeError("typora: active theme has no typora.css")
        if copied:
            changed.append(str(config / "Typora/themes/omarchy.css"))
    elif plugin_id == "swaync":
        target = config / "swaync/colors.css"
        source, copied = _copy_first(paths, ("colors.css",), target)
        if source is None:
            raise RuntimeError("swaync: active theme has no colors.css")
        if copied:
            changed.append(str(target))
    elif plugin_id == "windsurf":
        target = home / ".windsurf/extensions/local.omarchy-theme/themes/omarchy.json"
        source, copied = _copy_first(paths, ("vscode-theme.json",), target)
        if source is None:
            raise RuntimeError("windsurf: active theme has no vscode-theme.json")
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
    elif plugin_id == "cliamp":
        target = config / "cliamp/themes/omarchy.toml"
        source, copied = _copy_first(paths, ("cliamp.toml",), target)
        if source is None:
            return ApplyResult(
                plugin_id, "skipped", message="active theme has no cliamp.toml"
            )
        if copied:
            changed.append(str(target))
    elif plugin_id == "zed-extra":
        target = config / "zed/themes/omarchy.json"
        source, copied = _copy_first(paths, ("zed.json",), target)
        if source is None:
            raise RuntimeError("zed-extra: active theme has no zed.json")
        if copied:
            changed.append(str(target))

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
