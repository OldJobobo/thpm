from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from html import escape
from pathlib import Path

from .files import atomic_copy, atomic_text, remove_managed_block
from .models import ApplyResult
from .paths import Paths

GTK_START = "/* thpm-gtk-theme-start */"
GTK_END = "/* thpm-gtk-theme-end */"
GTK_IMPORT = f'{GTK_START}\n@import url("thpm-theme.css");\n{GTK_END}\n'
EDITORS = (
    ("code", "skip-vscode-theme-changes"),
    ("code-insiders", "skip-vscode-insiders-theme-changes"),
    ("codium", "skip-codium-theme-changes"),
    ("cursor", "skip-cursor-theme-changes"),
)
MAX_EXTENSION_FILES = 256
MAX_EXTENSION_FILE_SIZE = 5 * 1024 * 1024
MAX_EXTENSION_SIZE = 20 * 1024 * 1024
SAFE_EXTENSION_SUFFIXES = {
    ".json",
    ".jsonc",
    ".md",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
}
SAFE_CONTRIBUTIONS = {"themes"}


def gtk_requested(paths: Paths) -> bool:
    return (paths.current_theme / "gtk.css").is_file()


def _gtk_targets(paths: Paths) -> tuple[tuple[Path, Path], ...]:
    return tuple(
        (
            paths.config_home / version / "gtk.css",
            paths.config_home / version / "thpm-theme.css",
        )
        for version in ("gtk-3.0", "gtk-4.0")
    )


def _gtk_user_file(path: Path) -> Path:
    if not path.is_symlink():
        return path
    try:
        return path.resolve(strict=False)
    except RuntimeError as exc:
        raise ValueError(f"GTK stylesheet symlink cannot be resolved: {path}") from exc


def _remove_gtk_import(content: str) -> str:
    if GTK_START not in content and GTK_END not in content:
        return content
    return remove_managed_block(content, GTK_START, GTK_END)


def gtk_synchronized(paths: Paths) -> bool:
    source = paths.current_theme / "gtk.css"
    if not source.is_file():
        return all(
            not owned.exists()
            and (not main.exists() or GTK_START not in main.read_text())
            for main, owned in _gtk_targets(paths)
        )
    return all(
        owned.is_file()
        and owned.read_bytes() == source.read_bytes()
        and main.is_file()
        and GTK_IMPORT.strip() in main.read_text()
        for main, owned in _gtk_targets(paths)
    )


def apply_gtk(paths: Paths) -> ApplyResult:
    source = paths.current_theme / "gtk.css"
    changed: list[str] = []
    warnings: list[str] = []

    for main, owned in _gtk_targets(paths):
        user_file = _gtk_user_file(main)
        existing = user_file.read_text() if user_file.is_file() else ""
        clean = _remove_gtk_import(existing)
        if source.is_file():
            if not owned.is_file() or owned.read_bytes() != source.read_bytes():
                atomic_copy(source, owned)
                changed.append(str(owned))
            updated = GTK_IMPORT + ("\n" + clean.lstrip() if clean.strip() else "")
        else:
            updated = clean
            if owned.exists():
                owned.unlink()
                changed.append(str(owned))

        if updated != existing:
            if updated.strip():
                atomic_text(
                    user_file, updated if updated.endswith("\n") else updated + "\n"
                )
            else:
                user_file.unlink(missing_ok=True)
            changed.append(str(main))

    if changed and source.is_file():
        warnings.append("restart running GTK applications to load the new stylesheet")
    status = "applied" if changed else "unchanged"
    message = (
        "GTK 3 and GTK 4 theme CSS synchronized"
        if source.is_file()
        else "active theme does not request GTK CSS"
    )
    return ApplyResult(
        "gtk-css-compat", status, changed=changed, message=message, warnings=warnings
    )


def cleanup_gtk(paths: Paths) -> list[str]:
    result = apply_gtk_without_source(paths)
    return result.changed


def apply_gtk_without_source(paths: Paths) -> ApplyResult:
    changed: list[str] = []
    for main, owned in _gtk_targets(paths):
        user_file = _gtk_user_file(main)
        existing = user_file.read_text() if user_file.is_file() else ""
        updated = _remove_gtk_import(existing)
        if owned.exists():
            owned.unlink()
            changed.append(str(owned))
        if updated != existing:
            if updated.strip():
                atomic_text(
                    user_file, updated if updated.endswith("\n") else updated + "\n"
                )
            else:
                user_file.unlink(missing_ok=True)
            changed.append(str(main))
    return ApplyResult(
        "gtk-css-compat",
        "applied" if changed else "unchanged",
        changed=changed,
        message="THPM-managed GTK CSS removed",
    )


def _descriptor(paths: Paths) -> dict[str, object]:
    path = paths.current_theme / "vscode.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid vscode.json: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("vscode.json must contain an object")
    return value


def vscode_local_requested(paths: Paths) -> bool:
    descriptor = paths.current_theme / "vscode.json"
    source = paths.current_theme / "vscode-extension"
    if not descriptor.is_file():
        return False
    try:
        extension = str(_descriptor(paths).get("extension", ""))
    except ValueError:
        return source.is_dir()
    return extension.startswith("local.")


def _safe_extension_file(path: Path) -> bool:
    return path.suffix.lower() in SAFE_EXTENSION_SUFFIXES


def validate_vscode_source(paths: Paths) -> tuple[str, str, Path, dict[str, object]]:
    descriptor = _descriptor(paths)
    extension_id = str(descriptor.get("extension", "")).strip().lower()
    theme_name = str(descriptor.get("name", "")).strip()
    source = paths.current_theme / "vscode-extension"
    manifest_path = source / "package.json"

    if not extension_id.startswith("local.") or not re.fullmatch(
        r"[a-z0-9][a-z0-9._-]*", extension_id
    ):
        raise ValueError("bundled VS Code themes must use a valid local.* extension id")
    if not theme_name:
        raise ValueError("vscode.json has no theme name")
    if not manifest_path.is_file():
        raise ValueError("vscode-extension/package.json is missing")
    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid vscode-extension/package.json: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("vscode-extension/package.json must contain an object")

    for key in (
        "main",
        "browser",
        "activationEvents",
        "scripts",
        "dependencies",
        "optionalDependencies",
        "extensionDependencies",
        "extensionPack",
    ):
        if key in manifest:
            raise ValueError(f"local theme extension may not declare {key}")
    publisher = str(manifest.get("publisher", "")).strip().lower()
    name = str(manifest.get("name", "")).strip().lower()
    version = str(manifest.get("version", "1.0.0"))
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){2}(?:[-+][A-Za-z0-9.-]+)?", version):
        raise ValueError("local theme extension has an invalid version")
    if not publisher or not name or f"{publisher}.{name}" != extension_id:
        raise ValueError(
            "vscode.json extension id does not match package publisher.name"
        )
    engines = manifest.get("engines")
    if not isinstance(engines, dict) or not str(engines.get("vscode", "")).strip():
        raise ValueError("local theme extension must declare engines.vscode")
    contributes = manifest.get("contributes")
    if not isinstance(contributes, dict) or set(contributes) - SAFE_CONTRIBUTIONS:
        raise ValueError("local extension may contribute themes only")
    themes = contributes.get("themes")
    if not isinstance(themes, list) or not any(
        isinstance(theme, dict) and str(theme.get("label", "")) == theme_name
        for theme in themes
    ):
        raise ValueError(
            "requested VS Code theme label is not contributed by the local extension"
        )
    source_root = source.resolve()
    for theme in themes:
        if not isinstance(theme, dict) or not str(theme.get("path", "")):
            raise ValueError("local extension contains an invalid theme contribution")
        theme_path = (source / str(theme["path"])).resolve()
        if source_root not in theme_path.parents or not theme_path.is_file():
            raise ValueError("local extension theme contribution escapes or is missing")
        if theme_path.suffix.lower() not in {".json", ".jsonc"}:
            raise ValueError("local extension theme contribution must be JSON")

    if source.is_symlink() or paths.current_theme.resolve() not in source_root.parents:
        raise ValueError(
            "vscode-extension must be a real directory inside the active theme"
        )
    file_count = 0
    total_size = 0
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError(
                f"local theme extension contains a symlink: {path.relative_to(source)}"
            )
        if path.is_file():
            if not _safe_extension_file(path):
                raise ValueError(
                    f"local theme extension contains an unsupported file: {path.relative_to(source)}"
                )
            size = path.stat().st_size
            file_count += 1
            total_size += size
            if size > MAX_EXTENSION_FILE_SIZE:
                raise ValueError(
                    f"local theme extension file is too large: {path.relative_to(source)}"
                )
    if file_count > MAX_EXTENSION_FILES or total_size > MAX_EXTENSION_SIZE:
        raise ValueError("local theme extension exceeds the package size limit")
    return extension_id, theme_name, source, manifest


def _editor_commands(*, respect_toggles: bool = True) -> list[str]:
    commands: list[str] = []
    toggle_command = shutil.which("omarchy-toggle-enabled") if respect_toggles else None
    for command, toggle in EDITORS:
        if not shutil.which(command):
            continue
        if toggle_command:
            try:
                skipped = (
                    subprocess.run(
                        [toggle_command, toggle],
                        text=True,
                        capture_output=True,
                        check=False,
                        timeout=2,
                    ).returncode
                    == 0
                )
            except subprocess.TimeoutExpired:
                skipped = False
            if skipped:
                continue
        commands.append(command)
    return commands


def vscode_readiness(paths: Paths) -> tuple[bool, list[str]]:
    if not vscode_local_requested(paths):
        return True, []
    installed_commands = _editor_commands(respect_toggles=False)
    if installed_commands and not _editor_commands():
        return True, []
    missing = ["VS Code, VSCodium, or Cursor command"] if not installed_commands else []
    try:
        validate_vscode_source(paths)
    except ValueError as exc:
        missing.append(str(exc))
    return not missing, missing


def _source_hash(source: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(
        (item for item in source.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(source).as_posix(),
    ):
        relative = path.relative_to(source).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_zip_entry(bundle: zipfile.ZipFile, name: str, content: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    bundle.writestr(info, content)


def _build_vsix(
    source: Path, destination: Path, extension_id: str, manifest: dict[str, object]
) -> None:
    publisher, name = extension_id.split(".", 1)
    version = str(manifest.get("version", "1.0.0"))
    display = str(manifest.get("displayName", name))
    xml_name = escape(name, quote=True)
    xml_version = escape(version, quote=True)
    xml_publisher = escape(publisher, quote=True)
    xml_display = escape(display)
    vsix_manifest = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">'
        f'<Metadata><Identity Language="en-US" Id="{xml_name}" Version="{xml_version}" Publisher="{xml_publisher}" />'
        f'<DisplayName>{xml_display}</DisplayName><Description xml:space="preserve">{xml_display}</Description>'
        '<Categories>Themes</Categories></Metadata><Installation><InstallationTarget Id="Microsoft.VisualStudio.Code" />'
        '</Installation><Dependencies /><Assets><Asset Type="Microsoft.VisualStudio.Code.Manifest" '
        'Path="extension/package.json" Addressable="true" /></Assets></PackageManifest>\n'
    )
    content_types = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="json" ContentType="application/json" />'
        '<Default Extension="jsonc" ContentType="application/json" />'
        '<Default Extension="md" ContentType="text/markdown" />'
        '<Default Extension="txt" ContentType="text/plain" />'
        '<Default Extension="png" ContentType="image/png" />'
        '<Default Extension="jpg" ContentType="image/jpeg" />'
        '<Default Extension="jpeg" ContentType="image/jpeg" />'
        '<Default Extension="gif" ContentType="image/gif" />'
        '<Default Extension="webp" ContentType="image/webp" />'
        '<Default Extension="vsixmanifest" ContentType="text/xml" /></Types>\n'
    )
    with zipfile.ZipFile(destination, "w") as bundle:
        _write_zip_entry(bundle, "extension.vsixmanifest", vsix_manifest.encode())
        _write_zip_entry(bundle, "[Content_Types].xml", content_types.encode())
        for path in sorted(
            (item for item in source.rglob("*") if item.is_file()),
            key=lambda item: item.relative_to(source).as_posix(),
        ):
            _write_zip_entry(
                bundle,
                "extension/" + path.relative_to(source).as_posix(),
                path.read_bytes(),
            )


def _run_editor(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command, text=True, capture_output=True, check=False, timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"editor command timed out: {' '.join(command[:2])}"
        ) from exc


def _installed(command: str, extension_id: str) -> bool:
    completed = _run_editor([command, "--list-extensions"], 15)
    if completed.returncode != 0:
        detail = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or f"exit {completed.returncode}"
        )
        raise RuntimeError(f"{command} could not list extensions: {detail}")
    return extension_id.lower() in {
        line.strip().lower() for line in completed.stdout.splitlines()
    }


def _marker(paths: Paths, command: str, extension_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", extension_id)
    return paths.thpm_state_dir / "vscode-local" / f"{command}-{safe}.sha256"


def vscode_marker_current(paths: Paths) -> bool:
    if not vscode_local_requested(paths):
        return True
    commands = _editor_commands()
    if not commands and _editor_commands(respect_toggles=False):
        return True
    try:
        extension_id, _, source, _ = validate_vscode_source(paths)
    except ValueError:
        return False
    digest = _source_hash(source)
    return bool(commands) and all(
        _marker(paths, command, extension_id).is_file()
        and _marker(paths, command, extension_id).read_text().strip() == digest
        for command in commands
    )


def vscode_doctor_warnings(paths: Paths) -> list[str]:
    if not vscode_local_requested(paths):
        return []
    commands = _editor_commands()
    if not commands:
        if _editor_commands(respect_toggles=False):
            return []
        return ["no supported VS Code-family command is installed"]
    try:
        extension_id, _, source, _ = validate_vscode_source(paths)
    except ValueError as exc:
        return [str(exc)]
    digest = _source_hash(source)
    warnings: list[str] = []
    for command in commands:
        try:
            present = _installed(command, extension_id)
        except RuntimeError as exc:
            warnings.append(str(exc))
            continue
        if not present:
            warnings.append(f"{command} has not registered {extension_id}")
            continue
        marker = _marker(paths, command, extension_id)
        if not marker.is_file() or marker.read_text().strip() != digest:
            warnings.append(f"{command} local theme source is not synchronized")
    return warnings


def apply_vscode_local(paths: Paths) -> ApplyResult:
    if not vscode_local_requested(paths):
        return ApplyResult(
            "vscode-local-compat",
            "unchanged",
            message="active theme does not request a bundled local editor theme",
        )
    commands = _editor_commands()
    if not commands:
        if _editor_commands(respect_toggles=False):
            return ApplyResult(
                "vscode-local-compat",
                "unchanged",
                message="editor theme changes are disabled by Omarchy toggles",
            )
        return ApplyResult(
            "vscode-local-compat",
            "failed",
            message="no supported VS Code-family command is installed",
        )
    try:
        extension_id, _, source, manifest = validate_vscode_source(paths)
    except ValueError as exc:
        return ApplyResult("vscode-local-compat", "failed", message=str(exc))

    digest = _source_hash(source)
    actions: list[str] = []
    changed: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="thpm-vscode-") as temporary:
            vsix = Path(temporary) / "theme.vsix"
            built = False
            for command in commands:
                marker = _marker(paths, command, extension_id)
                current = marker.is_file() and marker.read_text().strip() == digest
                if current and _installed(command, extension_id):
                    continue
                if not built:
                    _build_vsix(source, vsix, extension_id, manifest)
                    built = True
                completed = _run_editor(
                    [command, "--install-extension", str(vsix), "--force"], 90
                )
                if completed.returncode != 0:
                    detail = (
                        completed.stderr.strip()
                        or completed.stdout.strip()
                        or f"exit {completed.returncode}"
                    )
                    raise RuntimeError(
                        f"{command} failed to install {extension_id}: {detail}"
                    )
                if not _installed(command, extension_id):
                    raise RuntimeError(
                        f"{command} did not register {extension_id} after installation"
                    )
                atomic_text(marker, digest + "\n")
                changed.append(str(marker))
                actions.append(f"{command} installed {extension_id}")
    except RuntimeError as exc:
        return ApplyResult(
            "vscode-local-compat",
            "failed",
            changed=changed,
            actions=actions,
            message=str(exc),
        )

    return ApplyResult(
        "vscode-local-compat",
        "applied" if actions else "unchanged",
        changed=changed,
        actions=actions,
        message=(
            "local editor theme installed"
            if actions
            else "local editor theme already current"
        ),
    )
