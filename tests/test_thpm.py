from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import re
import subprocess
import tarfile
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import call, patch

from rich.console import Console
from textual.widgets import Button, Link

from thpm import palette, ui
from thpm import update as updater
from thpm.cli import _confirm, main
from thpm.integrations import (
    _browser_import,
    _reload,
    apply,
    apply_enabled,
    inspect_readiness,
)
from thpm.migrate import archive, artifacts, inspect, needs_compat
from thpm.paths import Paths
from thpm.presentation import Activity, render, reporter
from thpm.registry import PLUGINS
from thpm.service import Service
from thpm.state import StateError, load, save
from thpm.templates import reconcile
from thpm.tui import ThpmTui, omarchy_theme
from thpm.zed import (
    MAX_THEME_BYTES,
    THEME_NAME,
    ZedThemeError,
    configure_settings,
    normalized,
)
from thpm.zed import status as zed_status

COLORS = {
    "mode": "dark", "bg": "#111111", "dark_bg": "#101010", "darker_bg": "#090909",
    "lighter_bg": "#222222", "selection": "#333333", "muted": "#777777", "dark_fg": "#999999",
    "fg": "#dddddd", "light_fg": "#eeeeee", "bright_fg": "#ffffff", "red": "#cc4444",
    "yellow": "#ccaa44", "orange": "#dd8844", "green": "#55aa66", "cyan": "#44aacc",
    "blue": "#4477cc", "magenta": "#aa55cc", "brown": "#996644", "bright_red": "#ff6666",
    "bright_yellow": "#ffdd66", "bright_green": "#77dd88", "bright_cyan": "#66ddee",
    "bright_blue": "#6699ff", "bright_magenta": "#dd77ff",
}
CANONICAL_NAMES = {
    "bg": "background",
    "dark_bg": "dark_background",
    "darker_bg": "darker_background",
    "lighter_bg": "lighter_background",
    "dark_fg": "dark_foreground",
    "fg": "foreground",
    "light_fg": "light_foreground",
    "bright_fg": "bright_foreground",
}
CANONICAL_COLORS = {CANONICAL_NAMES.get(key, key): value for key, value in COLORS.items()}


def zed_theme(name: str = "Source", appearance: str = "dark") -> str:
    return json.dumps({
        "$schema": "https://zed.dev/schema/themes/v0.1.0.json",
        "name": name,
        "author": "Theme Author",
        "themes": [{"name": name, "appearance": appearance, "style": {"background": "#123456"}}],
    }) + "\n"


def resolver_output(colors: dict[str, str]) -> str:
    return "\n".join(f"{key}\t{value}" for key, value in colors.items()) + "\n"


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.paths = Paths(root, root / "config", root / "data", root / "state", root / "run")

    def tearDown(self):
        self.temp.cleanup()

    def write_palette(self):
        self.paths.current_theme.mkdir(parents=True)
        lines = [f'{key} = "{value}"' for key, value in COLORS.items()]
        (self.paths.current_theme / "colors.toml").write_text("\n".join(lines) + "\n")


class PaletteTests(Sandbox):
    def test_accepts_quattro_semantic_palette_without_host_resolver(self):
        self.write_palette()
        with patch("thpm.palette.shutil.which", return_value=None):
            result = palette.load(self.paths.current_theme / "colors.toml")
        self.assertEqual(result["mode"], "dark")

    def test_uses_omarchy_resolver_as_native_palette_contract(self):
        self.paths.current_theme.mkdir(parents=True)
        colors = self.paths.current_theme / "colors.toml"
        colors.write_text('background = "#000000"\ncolor0 = "#000000"\n')
        with patch("thpm.palette.shutil.which", return_value="/usr/bin/omarchy-theme-color"), patch(
            "thpm.palette.subprocess.run"
        ) as run:
            run.return_value = subprocess.CompletedProcess(
                [], 0, resolver_output(CANONICAL_COLORS), ""
            )
            result = palette.load(colors)
        self.assertEqual(result, COLORS)
        run.assert_called_once_with(
            ["/usr/bin/omarchy-theme-color", "--file", str(colors), "--all"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )

    def test_canonical_keys_win_conflicts_independent_of_output_order(self):
        self.paths.current_theme.mkdir(parents=True)
        colors = self.paths.current_theme / "colors.toml"
        colors.write_text('mode = "dark"\n')
        conflicting = {**COLORS, **CANONICAL_COLORS}
        for key, canonical in CANONICAL_NAMES.items():
            conflicting[key] = "#010203"
            conflicting[canonical] = COLORS[key]
        for entries in (list(conflicting.items()), list(reversed(conflicting.items()))):
            with self.subTest(order="forward" if entries[0] == next(iter(conflicting.items())) else "reverse"), patch(
                "thpm.palette.shutil.which", return_value="resolver"
            ), patch(
                "thpm.palette.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    [], 0, resolver_output(dict(entries)), ""
                ),
            ):
                result = palette.load(colors)
            for key in CANONICAL_NAMES:
                self.assertEqual(result[key], COLORS[key])

    def test_blank_canonical_rows_fall_back_to_short_compatibility_values(self):
        data = {**COLORS, **{canonical: "" for canonical in CANONICAL_NAMES.values()}}
        self.assertEqual(palette._validate(data), COLORS)

    def test_strict_fallback_accepts_complete_canonical_palette(self):
        self.paths.current_theme.mkdir(parents=True)
        colors = self.paths.current_theme / "colors.toml"
        colors.write_text(
            "\n".join(f'{key} = "{value}"' for key, value in CANONICAL_COLORS.items()) + "\n"
        )
        with patch("thpm.palette.shutil.which", return_value=None):
            self.assertEqual(palette.load(colors), COLORS)

    def test_strict_fallback_rejects_incomplete_palette(self):
        self.paths.current_theme.mkdir(parents=True)
        colors = self.paths.current_theme / "colors.toml"
        colors.write_text('background = "#000000"\n')
        with patch("thpm.palette.shutil.which", return_value=None), self.assertRaisesRegex(
            ValueError, "missing semantic colors"
        ):
            palette.load(colors)

    def test_rejects_malformed_resolver_output(self):
        self.paths.current_theme.mkdir(parents=True)
        colors = self.paths.current_theme / "colors.toml"
        colors.write_text('mode = "dark"\n')
        with patch("thpm.palette.shutil.which", return_value="resolver"), patch(
            "thpm.palette.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, "mode\tdark\nmode\tlight\n", ""),
        ), self.assertRaisesRegex(ValueError, "invalid Omarchy palette resolver output"):
            palette.load(colors)

    def test_resolver_timeout_is_reported(self):
        self.paths.current_theme.mkdir(parents=True)
        colors = self.paths.current_theme / "colors.toml"
        colors.write_text('mode = "dark"\n')
        with patch("thpm.palette.shutil.which", return_value="resolver"), patch(
            "thpm.palette.subprocess.run", side_effect=subprocess.TimeoutExpired(["resolver"], 5)
        ), self.assertRaisesRegex(ValueError, "resolver timed out"):
            palette.load(colors)

    def test_resolver_failure_is_not_hidden_by_strict_fallback(self):
        self.paths.current_theme.mkdir(parents=True)
        colors = self.paths.current_theme / "colors.toml"
        colors.write_text('mode = "dark"\n')
        with patch("thpm.palette.shutil.which", return_value="resolver"), patch(
            "thpm.palette.subprocess.run",
            return_value=subprocess.CompletedProcess([], 2, "", "bad palette"),
        ), self.assertRaisesRegex(ValueError, "bad palette"):
            palette.load(colors)


class StateTests(Sandbox):
    def test_malformed_state_is_not_silently_replaced(self):
        self.paths.thpm_state_dir.mkdir(parents=True)
        self.paths.state_file.write_text("[plugins\n")
        with self.assertRaises(StateError):
            load(self.paths)
        with self.assertRaises(StateError):
            Service(self.paths).set_enabled("fish", False)
        self.assertEqual(self.paths.state_file.read_text(), "[plugins\n")

    def test_state_round_trip_preserves_known_values(self):
        state = load(self.paths)
        state["firefox"] = True
        save(self.paths, state)
        self.assertTrue(load(self.paths)["firefox"])

    def test_reconcile_only_removes_owned_templates(self):
        foreign = self.paths.themed_dir / "mine.tpl"
        foreign.parent.mkdir(parents=True)
        foreign.write_text("mine")
        enabled = {key: False for key in load(self.paths)}
        enabled["fish"] = True
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(Path(__file__).parents[1] / "assets")}):
            reconcile(self.paths, enabled)
        self.assertTrue((self.paths.themed_dir / "thpm-fish.fish.tpl").is_file())
        self.assertEqual(foreign.read_text(), "mine")

    def test_reconcile_removes_obsolete_generated_zellij_template(self):
        obsolete = self.paths.themed_dir / "thpm-zellij.kdl.tpl"
        obsolete.parent.mkdir(parents=True)
        obsolete.write_text("legacy generated fallback\n")
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(Path(__file__).parents[1] / "assets")}):
            changed = reconcile(self.paths, load(self.paths))
        self.assertFalse(obsolete.exists())
        self.assertIn(str(obsolete), changed)

    def test_sensitive_plugins_are_opt_in_by_default(self):
        enabled = load(self.paths)
        self.assertTrue(all(not enabled[plugin_id] for plugin_id in ("firefox", "zen", "steam", "zed-extra")))
        self.assertTrue(enabled["gtk-css-compat"])
        self.assertTrue(enabled["vscode-local-compat"])

    def test_every_registered_template_is_packaged(self):
        templates = Path(__file__).parents[1] / "assets/templates"
        missing = [name for plugin in PLUGINS for name in plugin.templates if not (templates / name).is_file()]
        self.assertEqual(missing, [])

    def test_templates_use_canonical_palette_keys_and_render_completely(self):
        templates = Path(__file__).parents[1] / "assets/templates"
        legacy = set(CANONICAL_NAMES)
        placeholder = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
        rendered: dict[str, str] = {}

        def substitute(match: re.Match[str]) -> str:
            expression = match.group(1).strip()
            parts = expression.split()
            self.assertEqual(
                len(parts), 1, f"test renderer needs explicit coverage for {expression}"
            )
            token = parts[0]
            suffix = ""
            for candidate in ("_strip", "_rgb"):
                if token.endswith(candidate):
                    token, suffix = token[: -len(candidate)], candidate
                    break
            self.assertNotIn(token, legacy)
            self.assertIn(token, CANONICAL_COLORS)
            value = CANONICAL_COLORS[token]
            if suffix == "_strip":
                return value.removeprefix("#")
            if suffix == "_rgb":
                return ",".join(str(int(value[index:index + 2], 16)) for index in (1, 3, 5))
            return value

        for path in sorted(templates.glob("*.tpl")):
            source = path.read_text()
            for expression in placeholder.findall(source):
                identifiers = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expression)
                self.assertFalse(legacy.intersection(identifiers), f"{path}: {expression}")
            output = placeholder.sub(substitute, source)
            self.assertNotIn("{{", output, str(path))
            rendered[path.name] = output
        document = json.loads(rendered["thpm-hermes.json.tpl"])
        self.assertEqual(document["schemaVersion"], 1)
        self.assertIn("brightWhite", document["theme"]["darkTerminal"])

    def test_unimplemented_plugins_are_not_exposed(self):
        self.assertNotIn("obsidian-terminal", {plugin.id for plugin in PLUGINS})


class MigrationTests(Sandbox):
    def test_migration_reads_names_not_legacy_contents(self):
        self.paths.hook_dir.mkdir(parents=True)
        legacy = self.paths.hook_dir / "40-firefox.sh"
        legacy.write_text("exit 99\n")
        updates, files = inspect(self.paths)
        self.assertTrue(updates["firefox"])
        self.assertEqual(files, [legacy])

    def test_migration_maps_legacy_native_coverage_hooks_to_compatibility_plugins(self):
        self.paths.hook_dir.mkdir(parents=True)
        gtk = self.paths.hook_dir / "10-gtk.sh"
        vscode = self.paths.hook_dir / "30-vscode.sh"
        gtk.write_text("legacy GTK\n")
        vscode.write_text("legacy VS Code\n")
        updates, files = inspect(self.paths)
        self.assertTrue(updates["gtk-css-compat"])
        self.assertTrue(updates["vscode-local-compat"])
        self.assertEqual(set(files), {gtk, vscode})

    def test_migration_preserves_hooks_without_a_replacement_adapter(self):
        self.paths.hook_dir.mkdir(parents=True)
        legacy = self.paths.hook_dir / "40-obsidian-terminal.sh"
        legacy.write_text("legacy integration\n")
        updates, files = inspect(self.paths)
        self.assertNotIn("obsidian-terminal", updates)
        self.assertNotIn(legacy, files)

    def test_upgrade_archives_known_install_and_preserves_unknown_files(self):
        launcher = self.paths.home / ".local/bin/thpm"
        launcher.parent.mkdir(parents=True)
        launcher.write_text('#!/bin/bash\nTHPM_CONTROL_LIB_DIR="$HOME/.local/share/thpm/lib"\n')
        control = self.paths.data_home / "thpm/lib/config.sh"
        control.parent.mkdir(parents=True)
        control.write_text("legacy")
        unknown = self.paths.data_home / "thpm/restart-notified-app"
        unknown.write_text("keep")
        old_config = self.paths.thpm_config_dir / "config.toml"
        old_config.parent.mkdir(parents=True)
        old_config.write_text("legacy")
        found = artifacts(self.paths)
        destination = archive(self.paths, [], found)
        self.assertIsNotNone(destination)
        self.assertFalse(launcher.exists())
        self.assertFalse(control.exists())
        self.assertFalse(old_config.exists())
        self.assertTrue(unknown.exists())
        self.assertTrue((destination / launcher.relative_to(self.paths.home)).exists())

    def test_upgrade_does_not_remove_unrecognized_thpm_launcher(self):
        launcher = self.paths.home / ".local/bin/thpm"
        launcher.parent.mkdir(parents=True)
        launcher.write_text("#!/bin/sh\necho unrelated\n")
        self.assertNotIn(launcher, artifacts(self.paths))

    def test_upgrade_detects_old_monolithic_launcher(self):
        launcher = self.paths.home / ".local/bin/thpm"
        launcher.parent.mkdir(parents=True)
        launcher.write_text('#!/bin/bash\nTHPM_VERSION_FILE="$HOME/.local/share/thpm/version"\n')
        self.assertIn(launcher, artifacts(self.paths))

    def test_upgrade_does_not_rearchive_new_transition_helper(self):
        helper = self.paths.legacy_compat_file
        helper.parent.mkdir(parents=True)
        helper.write_text("#!/usr/bin/env bash\n# Transitional helpers for independently authored hooks that used THPM's old helper path.\n")
        self.assertNotIn(helper, artifacts(self.paths))

    def test_custom_hook_requesting_old_helper_gets_compatibility_bridge(self):
        self.paths.hook_dir.mkdir(parents=True)
        custom = self.paths.hook_dir / "10-custom.sh"
        custom.write_text('source "$HOME/.local/share/thpm/lib/theme-env.sh"\nsuccess done\n')
        self.assertTrue(needs_compat(self.paths, []))

    def test_service_migration_preserves_custom_hook_and_replaces_old_helper(self):
        self.paths.hook_dir.mkdir(parents=True)
        old_hook = self.paths.hook_dir / "40-firefox.sh"
        old_hook.write_text("legacy")
        custom = self.paths.hook_dir / "10-custom.sh"
        custom.write_text('source "$HOME/.local/share/thpm/lib/theme-env.sh"\n')
        old_helper = self.paths.legacy_compat_file
        old_helper.parent.mkdir(parents=True)
        old_helper.write_text("old copyrighted implementation")
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            payload = Service(self.paths).migrate()
        self.assertTrue(payload["ok"])
        self.assertFalse(old_hook.exists())
        self.assertTrue(custom.exists())
        self.assertEqual(old_helper.read_bytes(), (assets / "compat/theme-env.sh").read_bytes())


class UiTests(Sandbox):
    def test_menu_install_and_remove_preserve_foreign_entries(self):
        self.paths.menu_extension.parent.mkdir(parents=True)
        self.paths.menu_extension.write_text('{\n  "foreign": {"label":"Mine"}\n}\n')
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch("thpm.ui.shell_running", return_value=False):
            ui.install(self.paths)
            installed = self.paths.menu_extension.read_text()
            self.assertIn('"foreign"', installed)
            self.assertEqual(installed.count('"style.theme-hooks"'), 1)
            self.assertNotIn("style.theme-hooks-terminal", installed)
            self.assertIn("omarchy shell shell summon", installed)
            self.assertEqual(
                (self.paths.shell_plugin_dir / "Panel.qml").read_bytes(),
                (assets / "qml/Panel.qml.in").read_bytes(),
            )
            self.assertFalse((self.paths.shell_plugin_dir / "Panel.qml.in").exists())
            selected = ui.surface(self.paths, "tui")
            self.assertEqual(selected["surface"], "tui")
            installed = self.paths.menu_extension.read_text()
            self.assertEqual(installed.count('"style.theme-hooks"'), 1)
            self.assertIn("omarchy-launch-floating-terminal-with-presentation 'thpm tui'", installed)
            self.assertNotIn("style.theme-hooks-terminal", installed)
            self.assertEqual(ui.status(self.paths)["menuSurface"], "tui")
            ui.install(self.paths)
            self.assertIn("'thpm tui'", self.paths.menu_extension.read_text())
            toggled = ui.surface(self.paths, "toggle")
            self.assertEqual(toggled["surface"], "gui")
            self.assertIn("omarchy shell shell summon", self.paths.menu_extension.read_text())
            ui.remove(self.paths)
        self.assertIn('"foreign"', self.paths.menu_extension.read_text())
        self.assertNotIn("style.theme-hooks", self.paths.menu_extension.read_text())

    def test_qml_manifest_contract(self):
        manifest = json.loads((Path(__file__).parents[1] / "assets/qml/manifest.json").read_text())
        self.assertEqual(manifest["id"], "io.github.oldjobobo.thpm")
        self.assertIn("panel", manifest["kinds"])
        self.assertTrue(manifest["keepLoaded"])

    def test_qml_uses_native_floating_window_surface(self):
        qml = (Path(__file__).parents[1] / "assets/qml/Panel.qml.in").read_text()
        self.assertIn("FloatingWindow {", qml)
        self.assertIn('title: "THPM Theme Hook Plugins"', qml)
        self.assertIn("color: Color.popups.background", qml)
        self.assertNotIn("id: card", qml)
        self.assertNotIn("PanelWindow {", qml)
        self.assertNotIn("WlrLayershell.", qml)

    def test_qml_design_stays_single_panel_and_uses_omarchy_controls(self):
        qml = (Path(__file__).parents[1] / "assets/qml/Panel.qml.in").read_text()
        self.assertEqual(qml.count("FloatingWindow {"), 1)
        self.assertIn("import qs.Ui", qml)
        self.assertIn("BorderSurface {", qml)
        self.assertIn("TextField {", qml)
        self.assertIn("delegate: Toggle {", qml)
        self.assertNotIn("Switch {", qml)
        self.assertNotIn('text: "Refresh"', qml)
        self.assertIn("rightPadding: pluginScrollBar.visible ? pluginScrollBar.width", qml)

    def test_qml_plugin_mutations_report_errors_and_require_confirmation(self):
        qml = (Path(__file__).parents[1] / "assets/qml/Panel.qml.in").read_text()
        self.assertIn("id: pluginConfirm", qml)
        self.assertIn("function readMutation()", qml)
        self.assertIn("id: mutateOutput", qml)
        self.assertIn('mutate.command.push("--yes")', qml)

    def test_qml_update_flow_requires_confirmation(self):
        qml = (Path(__file__).parents[1] / "assets/qml/Panel.qml.in").read_text()
        self.assertIn('["thpm", "--json", "update", "status"]', qml)
        self.assertIn('id: updateConfirm', qml)
        self.assertIn('command: ["thpm", "--json", "update", "apply"]', qml)
        self.assertIn("updateInfo.refreshRequired", qml)
        self.assertIn("thpm reconcile --refresh", qml)
        self.assertIn('text: "Restart shell"', qml)

    def test_qml_is_a_multi_section_control_panel(self):
        qml = (Path(__file__).parents[1] / "assets/qml/Panel.qml.in").read_text()
        self.assertIn('text: "THPM"', qml)
        self.assertIn('text: "Overview"', qml)
        self.assertIn('text: "Integrations"', qml)
        self.assertIn('text: "Doctor"', qml)
        self.assertIn('text: "System"', qml)

    def test_qml_doctor_and_system_actions_use_json_cli(self):
        qml = (Path(__file__).parents[1] / "assets/qml/Panel.qml.in").read_text()
        self.assertIn('command: ["thpm", "--json", "doctor"]', qml)
        self.assertIn('command: ["thpm", "--json", "run"]', qml)
        self.assertIn('command: ["thpm", "--json", "reconcile", "--refresh"]', qml)
        self.assertIn("doctorInfo.errors || []", qml)
        self.assertIn("doctorInfo.warnings || []", qml)

    def test_qml_menu_launcher_uses_shared_surface_command(self):
        qml = (Path(__file__).parents[1] / "assets/qml/Panel.qml.in").read_text()
        self.assertIn('property string menuSurface: "gui"', qml)
        self.assertIn('["thpm", "--json", "ui", "surface", surfaceName]', qml)
        self.assertIn('onClicked: root.chooseMenuSurface("gui")', qml)
        self.assertIn('onClicked: root.chooseMenuSurface("tui")', qml)

    def test_qml_donation_action_opens_kofi(self):
        qml = (Path(__file__).parents[1] / "assets/qml/Panel.qml.in").read_text()
        self.assertEqual(qml.count('text: "Donate on Ko-fi"'), 1)
        self.assertIn("id: persistentFooter", qml)
        self.assertIn("id: footerDonate", qml)
        self.assertIn("anchors.right: parent.right", qml)
        self.assertIn("bordered: false", qml)
        self.assertIn('text: "Donate on Ko-fi"', qml)
        self.assertIn('command: ["xdg-open", "https://ko-fi.com/oldjobobo"]', qml)


class ServiceTests(Sandbox):
    def test_json_envelope_and_native_ownership(self):
        payload = Service(self.paths).state()
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertTrue(any(p["ownership"] == "native" for p in payload["plugins"]))
        self.assertEqual(payload["menuSurface"], "gui")

    def test_ui_surface_uses_shared_service_envelope(self):
        result = {"surface": "tui", "changed": True}
        with patch("thpm.service.ui.surface", return_value=result) as set_surface:
            payload = Service(self.paths).ui_surface("tui")
        set_surface.assert_called_once_with(self.paths, "tui")
        self.assertEqual(payload["result"], result)
        self.assertEqual(payload["summary"], "Omarchy menu opens the TUI")

    def test_uninstall_removes_only_thpm_integration_files(self):
        foreign = self.paths.themed_dir / "foreign.tpl"
        owned = self.paths.themed_dir / "thpm-fish.fish.tpl"
        foreign.parent.mkdir(parents=True)
        foreign.write_text("keep")
        owned.write_text("remove")
        self.paths.hook_file.parent.mkdir(parents=True)
        self.paths.hook_file.write_text("remove")
        self.paths.canonical_palette_migration_marker.parent.mkdir(parents=True)
        self.paths.canonical_palette_migration_marker.write_text("done\n")
        zellij_config = self.paths.config_home / "zellij/config.kdl"
        zellij_config.parent.mkdir(parents=True)
        zellij_config.write_text('theme "thpm-current"\n')
        fish_source = self.paths.current_theme / "thpm-fish.fish"
        fish_source.parent.mkdir(parents=True)
        fish_source.write_text("theme output")
        fish_target = self.paths.config_home / "fish/conf.d/thpm-theme.fish"
        fish_target.parent.mkdir(parents=True)
        fish_target.write_text("user output")
        apply("fish", self.paths)
        with patch("thpm.service.ui.remove", return_value={"installed": False}):
            payload = Service(self.paths).uninstall()
        self.assertTrue(foreign.exists())
        self.assertFalse(owned.exists())
        self.assertFalse(self.paths.hook_file.exists())
        self.assertFalse(self.paths.canonical_palette_migration_marker.exists())
        self.assertEqual(zellij_config.read_text(), "")
        self.assertEqual(fish_target.read_text(), "user output")
        self.assertFalse(fish_source.exists())
        self.assertIn("restart active Zellij sessions", str(payload["warnings"]))

    def test_uninstall_removes_legacy_system24_output_despite_shared_marker(self):
        source = self.paths.current_theme / "thpm-vencord-system24.theme.css"
        source.parent.mkdir(parents=True)
        source.write_text("legacy system24")
        directory = self.paths.config_home / "Vencord/themes"
        directory.mkdir(parents=True)
        target = directory / "vencord.theme.css"
        target.write_text("legacy system24")
        enabled = load(self.paths)
        enabled["discord"] = False
        enabled["discord-system24"] = True
        save(self.paths, enabled)
        with patch("thpm.service.ui.remove", return_value={"installed": False}):
            payload = Service(self.paths).uninstall()
        self.assertTrue(payload["ok"])
        self.assertFalse(target.exists())
        self.assertFalse(source.exists())

    def test_refresh_failure_reports_that_enablement_was_committed(self):
        assets = Path(__file__).parents[1] / "assets"
        failed = subprocess.CompletedProcess([], 1, "", "refresh failed")
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch(
            "thpm.service.run", return_value=failed
        ):
            payload = Service(self.paths).set_enabled("branding", True)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["committed"])
        self.assertTrue(payload["stateChanged"])
        self.assertTrue(load(self.paths)["branding"])
        self.assertIn("setting was saved", payload["summary"])

    def test_enable_disable_reports_progress_instead_of_sitting_at_zero(self):
        stages: list[str] = []
        payload = Service(
            self.paths, progress=lambda message, _detail=None: stages.append(message)
        ).set_enabled("branding", False, refresh=False)
        self.assertTrue(payload["ok"])
        self.assertEqual(
            stages,
            [
                "Checking integration",
                "Updating integration state",
                "Verifying integration state",
            ],
        )

    def test_unknown_plugin_suggests_the_closest_valid_id(self):
        payload = Service(self.paths).set_enabled("zed-etra", True, refresh=False)
        self.assertFalse(payload["ok"])
        self.assertIn("did you mean zed-extra?", payload["summary"])

    def test_sensitive_plugin_requires_service_confirmation(self):
        assets = Path(__file__).parents[1] / "assets"
        browser = self.paths.home / ".mozilla/firefox"
        browser.mkdir(parents=True)
        (browser / "profiles.ini").write_text("[Install1]\nDefault=profile.default\n")
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch("thpm.snapshot.shutil.which", return_value="/bin/true"):
            pending = Service(self.paths).set_enabled("firefox", True, refresh=False)
            accepted = Service(self.paths).set_enabled("firefox", True, confirmed=True, refresh=False)
        self.assertFalse(pending["ok"])
        self.assertTrue(pending["confirmationRequired"])
        self.assertTrue(accepted["ok"])

    def test_disabling_optional_asset_restores_previous_file(self):
        source = self.paths.current_theme / "typora.css"
        source.parent.mkdir(parents=True)
        source.write_text("theme")
        target = self.paths.config_home / "Typora/themes/omarchy.css"
        target.parent.mkdir(parents=True)
        target.write_text("user default")
        apply("typora", self.paths)
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            payload = Service(self.paths).set_enabled("typora", False, refresh=False)
        self.assertTrue(payload["ok"])
        self.assertEqual(target.read_text(), "user default")
        self.assertIn(str(target), payload["changed"])

    def test_disabling_generated_integration_restores_previous_output(self):
        source = self.paths.current_theme / "thpm-fish.fish"
        source.parent.mkdir(parents=True)
        source.write_text("theme output")
        target = self.paths.config_home / "fish/conf.d/thpm-theme.fish"
        target.parent.mkdir(parents=True)
        target.write_text("user output")
        apply("fish", self.paths)
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            payload = Service(self.paths).set_enabled("fish", False, refresh=False)
        self.assertTrue(payload["ok"])
        self.assertEqual(target.read_text(), "user output")
        self.assertFalse(source.exists())

    def test_generated_upgrade_does_not_preserve_an_old_theme_as_user_default(self):
        installed = self.paths.config_home / "omarchy/themes/old"
        installed.mkdir(parents=True)
        (installed / "thpm-fish.fish").write_text("old theme output")
        source = self.paths.current_theme / "thpm-fish.fish"
        source.parent.mkdir(parents=True)
        source.write_text("new theme output")
        target = self.paths.config_home / "fish/conf.d/thpm-theme.fish"
        target.parent.mkdir(parents=True)
        target.write_text("old theme output")
        apply("fish", self.paths)
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            Service(self.paths).set_enabled("fish", False, refresh=False)
        self.assertFalse(target.exists())

    def test_disabling_legacy_generated_output_removes_positive_match(self):
        source = self.paths.current_theme / "thpm-fish.fish"
        source.parent.mkdir(parents=True)
        source.write_text("legacy theme output")
        target = self.paths.config_home / "fish/conf.d/thpm-theme.fish"
        target.parent.mkdir(parents=True)
        target.write_text("legacy theme output")
        enabled = load(self.paths)
        enabled["fish"] = False
        save(self.paths, enabled)
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            payload = Service(self.paths).set_enabled("fish", False, refresh=False)
        self.assertTrue(payload["ok"])
        self.assertFalse(target.exists())
        self.assertFalse(source.exists())

    def test_disabling_swaync_restores_and_reloads(self):
        source = self.paths.current_theme / "colors.css"
        source.parent.mkdir(parents=True)
        source.write_text("theme")
        target = self.paths.config_home / "swaync/colors.css"
        target.parent.mkdir(parents=True)
        target.write_text("user default")
        with patch("thpm.integrations._reload", return_value=[]):
            apply("swaync", self.paths)
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch(
            "thpm.integrations.shutil.which", return_value="/usr/bin/swaync-client"
        ), patch("thpm.integrations._reload", return_value=["swaync-client --reload-css"]) as reload_app:
            payload = Service(self.paths).set_enabled("swaync", False, refresh=False)
        self.assertTrue(payload["ok"])
        self.assertEqual(target.read_text(), "user default")
        reload_app.assert_called_once_with("swaync")

    def test_disabling_gtk_compat_removes_only_managed_css(self):
        source = self.paths.current_theme / "gtk.css"
        source.parent.mkdir(parents=True)
        source.write_text("@define-color accent #abcdef;\n")
        gtk = self.paths.config_home / "gtk-3.0/gtk.css"
        gtk.parent.mkdir(parents=True)
        gtk.write_text("button { padding: 2px; }\n")
        apply("gtk-css-compat", self.paths)
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            payload = Service(self.paths).set_enabled("gtk-css-compat", False, refresh=False)
        self.assertTrue(payload["ok"])
        self.assertEqual(gtk.read_text(), "button { padding: 2px; }\n")
        self.assertFalse((gtk.parent / "thpm-theme.css").exists())

    def test_unavailable_plugin_cannot_be_enabled_by_service(self):
        with patch("thpm.snapshot.shutil.which", return_value=None):
            payload = Service(self.paths).set_enabled("firefox", True, confirmed=True, refresh=False)
        self.assertFalse(payload["ok"])
        self.assertIn("unavailable", payload["summary"])

    def test_install_stages_qml_even_when_shell_is_stopped(self):
        assets = Path(__file__).parents[1] / "assets"
        refreshed = subprocess.CompletedProcess([], 0, "", "")
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch("thpm.service.capabilities") as caps, \
             patch("thpm.service.ui.install", return_value={"installed": True}) as install_ui, \
             patch("thpm.service.run", return_value=refreshed) as run:
            caps.return_value.available = True
            caps.return_value.routes = set()
            caps.return_value.missing = ()
            payload = Service(self.paths).install()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["migration"]["refreshed"])
        self.assertTrue(self.paths.canonical_palette_migration_marker.is_file())
        install_ui.assert_called_once_with(self.paths)
        run.assert_called_once_with("theme", "refresh", check=False, timeout=180)

    def test_reinstall_refreshes_even_after_one_time_migration_completed(self):
        assets = Path(__file__).parents[1] / "assets"
        self.paths.canonical_palette_migration_marker.parent.mkdir(parents=True)
        self.paths.canonical_palette_migration_marker.write_text("complete\n")
        refreshed = subprocess.CompletedProcess([], 0, "", "")
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch(
            "thpm.service.capabilities"
        ) as caps, patch(
            "thpm.service.ui.install", return_value={"installed": True}
        ), patch("thpm.service.run", return_value=refreshed) as run:
            caps.return_value.available = True
            caps.return_value.routes = set()
            caps.return_value.missing = ()
            payload = Service(self.paths).install()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["migration"]["refreshed"])
        run.assert_called_once_with("theme", "refresh", check=False, timeout=180)

    def test_palette_upgrade_refresh_is_idempotent_and_retries_failures(self):
        assets = Path(__file__).parents[1] / "assets"
        failed = subprocess.CompletedProcess([], 1, "", "render failed")
        refreshed = subprocess.CompletedProcess([], 0, "", "")
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch(
            "thpm.service.run", side_effect=[failed, refreshed]
        ) as run:
            first = Service(self.paths).reconcile()
            second = Service(self.paths).reconcile()
            third = Service(self.paths).reconcile()
        self.assertFalse(first["ok"])
        self.assertTrue(first["migration"]["pending"])
        self.assertTrue(second["ok"])
        self.assertTrue(second["migration"]["refreshed"])
        self.assertFalse(third["migration"]["pending"])
        self.assertFalse(third["migration"]["refreshed"])
        self.assertEqual(run.call_count, 2)

    def test_source_update_can_defer_upgrade_refresh_with_actionable_status(self):
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch(
            "thpm.service.run"
        ) as run:
            payload = Service(self.paths).reconcile(defer_upgrade_refresh=True)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["migration"]["pending"])
        self.assertTrue(payload["migration"]["deferred"])
        self.assertEqual(payload["migration"]["command"], "thpm reconcile --refresh")
        self.assertFalse(self.paths.canonical_palette_migration_marker.exists())
        run.assert_not_called()

    def test_rc4_bare_reconcile_defers_while_previous_runtime_is_rollbackable(self):
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch(
            "thpm.service._source_activation_in_progress", return_value=True
        ), patch("thpm.service.run") as run:
            payload = Service(self.paths).reconcile()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["migration"]["pending"])
        self.assertTrue(payload["migration"]["deferred"])
        run.assert_not_called()

    def test_state_and_doctor_report_pending_refresh_without_running_it(self):
        with patch("thpm.service.run") as run, patch(
            "thpm.service.capabilities"
        ) as caps, patch("thpm.service.load_palette", return_value=COLORS):
            caps.return_value.available = True
            caps.return_value.routes = set()
            caps.return_value.missing = ()
            state = Service(self.paths).state()
            doctor = Service(self.paths).doctor()
        self.assertTrue(state["migration"]["pending"])
        self.assertTrue(state["warnings"])
        self.assertTrue(doctor["migration"]["pending"])
        self.assertIn("refresh migration pending", str(doctor["warnings"]))
        run.assert_not_called()

    def test_doctor_accepts_canonical_resolver_palette(self):
        self.paths.current_theme.mkdir(parents=True)
        colors = self.paths.current_theme / "colors.toml"
        colors.write_text('background = "#111111"\n')
        completed = subprocess.CompletedProcess(
            [], 0, resolver_output(CANONICAL_COLORS), ""
        )
        with patch("thpm.service.capabilities") as caps, patch(
            "thpm.palette.shutil.which", return_value="resolver"
        ), patch("thpm.palette.subprocess.run", return_value=completed):
            caps.return_value.available = True
            caps.return_value.routes = set()
            caps.return_value.missing = ()
            payload = Service(self.paths).doctor()
        self.assertTrue(payload["ok"])
        self.assertNotIn("missing semantic colors", str(payload["errors"]))

    def test_doctor_warns_about_unresolved_generated_output(self):
        generated = self.paths.current_theme / "thpm-fish.fish"
        generated.parent.mkdir(parents=True)
        generated.write_text('set -gx COLOR "{{ background }}"\n')
        with patch("thpm.service.capabilities") as caps, patch(
            "thpm.service.load_palette", return_value=COLORS
        ), patch("thpm.snapshot.shutil.which", return_value="/bin/true"):
            caps.return_value.available = True
            caps.return_value.routes = set()
            caps.return_value.missing = ()
            payload = Service(self.paths).doctor()
        warnings = [item for item in payload["warnings"] if item.get("plugin") == "fish"]
        self.assertTrue(warnings)
        self.assertIn("unresolved placeholder", warnings[0]["message"])

    def test_disabling_inactive_discord_variant_keeps_active_shared_theme(self):
        source = self.paths.current_theme / "thpm-vencord.theme.css"
        source.parent.mkdir(parents=True)
        source.write_text("active discord theme")
        directory = self.paths.config_home / "Vencord/themes"
        directory.mkdir(parents=True)
        target = directory / "vencord.theme.css"
        apply("discord", self.paths)
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            payload = Service(self.paths).set_enabled(
                "discord-system24", False, refresh=False
            )
        self.assertTrue(payload["ok"])
        self.assertEqual(target.read_text(), "active discord theme")

    def test_discord_plugins_remain_mutually_exclusive(self):
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            Service(self.paths).set_enabled("discord", True)
        state = load(self.paths)
        self.assertTrue(state["discord"])
        self.assertFalse(state["discord-system24"])

    def test_non_applicable_compatibility_plugins_do_not_need_attention(self):
        plugins = Service(self.paths).state()["plugins"]
        compat = {plugin["id"]: plugin for plugin in plugins if plugin["id"].endswith("-compat")}
        self.assertFalse(compat["gtk-css-compat"]["applicable"])
        self.assertFalse(compat["vscode-local-compat"]["applicable"])
        self.assertEqual(compat["gtk-css-compat"]["warnings"], [])
        self.assertEqual(compat["vscode-local-compat"]["warnings"], [])

    def test_requested_gtk_compatibility_is_attention_until_synchronized(self):
        source = self.paths.current_theme / "gtk.css"
        source.parent.mkdir(parents=True)
        source.write_text("@define-color accent #abcdef;\n")
        before = next(plugin for plugin in Service(self.paths).state()["plugins"] if plugin["id"] == "gtk-css-compat")
        self.assertTrue(before["applicable"])
        self.assertTrue(before["warnings"])
        apply("gtk-css-compat", self.paths)
        after = next(plugin for plugin in Service(self.paths).state()["plugins"] if plugin["id"] == "gtk-css-compat")
        self.assertEqual(after["warnings"], [])

    def test_hermes_desktop_config_makes_plugin_available(self):
        (self.paths.config_home / "Hermes").mkdir(parents=True)
        plugin = next(item for item in Service(self.paths).state()["plugins"] if item["id"] == "hermes")
        self.assertTrue(plugin["available"])
        self.assertEqual(plugin["missing"], [])

    def test_enabled_unavailable_plugins_are_reported_as_attention(self):
        with patch("thpm.snapshot.shutil.which", return_value=None), patch("thpm.service.capabilities") as caps:
            caps.return_value.available = True
            caps.return_value.routes = set()
            caps.return_value.missing = ()
            state = Service(self.paths).state()
            doctor = Service(self.paths).doctor()
        self.assertGreater(state["counts"]["unavailable"], 0)
        self.assertGreater(state["counts"]["attention"], 0)
        self.assertGreater(len(doctor["warnings"]), 0)
        self.assertTrue(doctor["summary"].startswith("1 errors, "))

    def test_theme_hook_preserves_event_context(self):
        with patch("thpm.service.apply_enabled", return_value={"changed": [], "errors": []}):
            payload = Service(self.paths).hook_run("theme-set", ["tokyo-night"])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["event"], "theme-set")
        self.assertEqual(payload["eventArgs"], ["tokyo-night"])
        self.assertEqual(payload["themeName"], "tokyo-night")
        self.assertEqual(payload["summary"], "processed theme tokyo-night: 0 applied, 0 unchanged, 0 skipped, 0 failed")

    def test_unknown_hook_event_is_rejected_without_applying_integrations(self):
        with patch("thpm.service.apply_enabled") as apply_plugins:
            payload = Service(self.paths).hook_run("unknown", ["argument"])
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["event"], "unknown")
        apply_plugins.assert_not_called()


class PresentationTests(unittest.TestCase):
    def test_verbose_result_groups_summary_changes_and_command_output(self):
        output = io.StringIO()
        console = Console(file=output, force_terminal=False, width=100)
        render(
            {
                "ok": True,
                "operation": "reconcile",
                "summary": "reconciled 2 files",
                "changed": ["/tmp/one", "/tmp/two"],
                "stdout": "renderer: complete\n",
                "errors": [],
            },
            verbose=True,
            console=console,
        )
        text = output.getvalue()
        self.assertIn("✓ reconciled 2 files", text)
        self.assertIn("Changed files", text)
        self.assertIn("/tmp/one", text)
        self.assertIn("renderer: complete", text)

    def test_activity_renders_real_reported_stages(self):
        output = io.StringIO()
        console = Console(file=output, force_terminal=True, color_system="standard", width=100)
        with Activity("reconcile", verbose=True, console=console) as activity:
            activity.step("Reading integration state")
            activity.step("Rendering managed templates")
            activity.step("Installing theme hook")
        text = output.getvalue()
        self.assertIn("Reading integration state", text)
        self.assertIn("Rendering managed templates", text)
        self.assertIn("Installing theme hook", text)
        self.assertNotIn("•", text)
        self.assertLessEqual(text.count("\n"), 1)

    def test_activity_can_adjust_update_total_without_counting_current_stage_done(self):
        output = io.StringIO()
        console = Console(file=output, force_terminal=True, color_system="standard", width=100)
        with Activity("update", verbose=True, console=console) as activity:
            activity.step("Checking for an available release")
            activity.set_total(2)
            activity.step("Upgrading AUR package", "thpm")
            task = activity._progress.tasks[activity._task]
            self.assertEqual(task.total, 2)
            self.assertEqual(task.completed, 1)
        self.assertNotIn("•", output.getvalue())

    def test_activity_does_not_show_failed_operation_as_complete(self):
        output = io.StringIO()
        console = Console(
            file=output, force_terminal=True, color_system="standard", width=100
        )
        with Activity("enable", console=console) as activity:
            activity.step("Checking integration")
            activity.finish(False)
        self.assertNotIn("100%", output.getvalue())

    def test_activity_reporter_can_suspend_live_rendering_for_terminal_subprocesses(self):
        output = io.StringIO()
        console = Console(file=output, force_terminal=True, color_system="standard", width=100)
        with Activity("update", console=console) as activity:
            callback = reporter(activity)
            self.assertIs(callback, activity)
            self.assertTrue(activity._progress.live.is_started)
            with activity.suspend():
                self.assertFalse(activity._progress.live.is_started)
                output.write("[sudo] password for user: ")
            self.assertTrue(activity._progress.live.is_started)
        self.assertIn("[sudo] password for user:", output.getvalue())

    def test_confirmation_suspends_live_progress_while_waiting_for_input(self):
        output = io.StringIO()
        console = Console(
            file=output, force_terminal=True, color_system="standard", width=100
        )
        with Activity("enable", console=console) as activity:
            def answer(_message: str) -> str:
                self.assertFalse(activity._progress.live.is_started)
                return "yes"

            with patch("builtins.input", side_effect=answer):
                self.assertTrue(_confirm("Continue? ", activity))
            self.assertTrue(activity._progress.live.is_started)


class CliTests(unittest.TestCase):
    def test_json_usage_errors_are_machine_readable(self):
        with patch("sys.stdout", new_callable=io.StringIO) as stdout, patch(
            "sys.stderr", new_callable=io.StringIO
        ) as stderr:
            with self.assertRaisesRegex(SystemExit, "2"):
                main(["--json", "not-a-command"])
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["operation"], "parse")
        self.assertEqual(stderr.getvalue(), "")

    def test_confirmation_eof_is_a_clean_decline(self):
        with patch("builtins.input", side_effect=EOFError):
            self.assertFalse(_confirm("Continue? "))

    def test_confirmation_does_not_wait_when_output_is_redirected(self):
        pending = {
            "ok": False,
            "summary": "confirmation required",
            "confirmationRequired": True,
            "errors": [],
        }
        with patch("thpm.cli.Service") as service_type, patch(
            "thpm.cli.render"
        ), patch("thpm.cli.sys.stdin.isatty", return_value=True), patch(
            "thpm.cli.sys.stdout.isatty", return_value=False
        ), patch("builtins.input") as input_prompt:
            service_type.return_value.set_enabled.return_value = pending
            exit_code = main(["enable", "firefox"])
        self.assertEqual(exit_code, 1)
        input_prompt.assert_not_called()

    def test_human_output_is_verbose_by_default(self):
        response = {"ok": True, "summary": "THPM is current", "errors": []}
        with patch("thpm.cli.Service") as service_type, patch("thpm.cli.render") as render_output:
            service_type.return_value.update_apply.return_value = response
            exit_code = main(["update"])
        self.assertEqual(exit_code, 0)
        render_output.assert_called_once_with(response, verbose=True)

    def test_quiet_opts_out_of_verbose_human_output(self):
        response = {"ok": True, "summary": "THPM is current", "errors": []}
        with patch("thpm.cli.Service") as service_type, patch("thpm.cli.render") as render_output:
            service_type.return_value.update_apply.return_value = response
            exit_code = main(["update", "--quiet"])
        self.assertEqual(exit_code, 0)
        render_output.assert_called_once_with(response, verbose=False)

    def test_bare_update_applies_the_available_update(self):
        response = {"ok": True, "summary": "THPM updated"}
        with patch("thpm.cli.Service") as service_type, patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            service_type.return_value.update_apply.return_value = response
            exit_code = main(["update", "--json"])
        self.assertEqual(exit_code, 0)
        service_type.return_value.update_apply.assert_called_once_with(interactive=False)
        service_type.return_value.update_check.assert_not_called()
        self.assertEqual(json.loads(stdout.getvalue()), response)

    def test_explicit_update_check_remains_available(self):
        response = {"ok": True, "summary": "THPM is current"}
        with patch("thpm.cli.Service") as service_type, patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            service_type.return_value.update_check.return_value = response
            exit_code = main(["update", "check", "--force", "--json"])
        self.assertEqual(exit_code, 0)
        service_type.return_value.update_check.assert_called_once_with(True)
        service_type.return_value.update_apply.assert_not_called()
        self.assertEqual(json.loads(stdout.getvalue()), response)

    def test_hook_command_forwards_event_and_all_arguments(self):
        response = {"ok": True, "summary": "applied theme tokyo-night"}
        with patch("thpm.cli.Service") as service_type, patch("sys.stdout", new_callable=io.StringIO) as stdout:
            service_type.return_value.hook_run.return_value = response
            exit_code = main(["--json", "hook-run", "theme-set", "tokyo-night", "dark"])
        self.assertEqual(exit_code, 0)
        service_type.return_value.hook_run.assert_called_once_with("theme-set", ["tokyo-night", "dark"])
        self.assertEqual(json.loads(stdout.getvalue()), response)

    def test_zed_status_and_setup_json_envelopes(self):
        status = {"ok": True, "operation": "zed-status", "result": {}}
        setup = {"ok": True, "operation": "zed-setup", "result": {}}
        with patch("thpm.cli.Service") as service_type, patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            service_type.return_value.zed_status.return_value = status
            self.assertEqual(main(["--json", "zed", "status"]), 0)
            self.assertEqual(json.loads(stdout.getvalue()), status)
        with patch("thpm.cli.Service") as service_type, patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            service_type.return_value.zed_setup.return_value = setup
            self.assertEqual(main(["--json", "zed", "setup", "--yes"]), 0)
            service_type.return_value.zed_setup.assert_called_once_with(confirmed=True)
            self.assertEqual(json.loads(stdout.getvalue()), setup)

    def test_update_parent_options_survive_nested_subcommand_parsing(self):
        response = {"ok": True, "summary": "THPM is current"}
        with patch("thpm.cli.Service") as service_type, patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            service_type.return_value.update_check.return_value = response
            self.assertEqual(main(["update", "--json", "status"]), 0)
        self.assertEqual(json.loads(stdout.getvalue()), response)

    def test_update_parent_quiet_survives_nested_subcommand_parsing(self):
        response = {"ok": True, "summary": "THPM is current"}
        with patch("thpm.cli.Service") as service_type, patch(
            "thpm.cli.render"
        ) as render_output:
            service_type.return_value.update_check.return_value = response
            self.assertEqual(main(["update", "--quiet", "status"]), 0)
        render_output.assert_called_once_with(response, verbose=False)

    def test_json_tui_is_rejected_without_opening_textual(self):
        with patch("thpm.tui.run_tui") as run_tui, patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            exit_code = main(["tui", "--json"])
        self.assertEqual(exit_code, 1)
        self.assertFalse(json.loads(stdout.getvalue())["ok"])
        run_tui.assert_not_called()

    def test_tui_command_launches_alternate_frontend(self):
        with patch("thpm.tui.run_tui") as run_tui:
            exit_code = main(["tui"])
        self.assertEqual(exit_code, 0)
        run_tui.assert_called_once()

    def test_ui_surface_command_sets_menu_target(self):
        response = {"ok": True, "summary": "Omarchy menu opens the TUI", "result": {"surface": "tui", "changed": True}}
        with patch("thpm.cli.Service") as service_type, patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            service_type.return_value.ui_surface.return_value = response
            exit_code = main(["--json", "ui", "surface", "tui"])
        self.assertEqual(exit_code, 0)
        service_type.return_value.ui_surface.assert_called_once_with("tui")
        self.assertEqual(json.loads(stdout.getvalue()), response)


class FakeTuiService:
    def __init__(self):
        self.mutations: list[tuple[str, bool]] = []
        self.doctor_calls = 0
        self.update_available = False
        self.update_apply_calls = 0
        self.menu_surface = "gui"
        self.surface_calls: list[str] = []

    def state(self):
        return {"ok": True, "menuSurface": self.menu_surface, "counts": {"enabled": 1, "disabled": 0, "native": 1, "unavailable": 0, "attention": 0}, "plugins": [
            {"id": "fish", "label": "Fish", "category": "Terminal", "description": "Synchronize Fish colors.", "ownership": "thpm", "enabled": True, "available": True, "warnings": []},
            {"id": "native-foot", "label": "Foot live colors", "category": "Native", "description": "Owned by Omarchy.", "ownership": "native", "enabled": True, "available": True, "warnings": []},
        ]}

    def set_enabled(self, plugin_id, enabled, **_kwargs):
        self.mutations.append((plugin_id, enabled))
        return {"ok": True, "summary": "changed"}

    def doctor(self):
        self.doctor_calls += 1
        return {"ok": True, "summary": "0 errors, 0 warnings", "errors": [], "warnings": [], "capabilities": {"routes": ["theme refresh"], "missing": []}}

    def run_theme(self): return {"ok": True}
    def reconcile(self, refresh=False): return {"ok": True}
    def update_check(self, force=False):
        return {"ok": True, "result": {"status": "available" if self.update_available else "current", "currentVersion": "1.0.0rc1", "availableVersion": "1.1.0" if self.update_available else None}}

    def update_apply(self):
        self.update_apply_calls += 1
        return {"ok": True, "result": {"status": "updated", "currentVersion": "1.0.0rc1", "availableVersion": "1.1.0"}}

    def ui_surface(self, requested=None):
        if requested is not None:
            self.menu_surface = requested
            self.surface_calls.append(requested)
        return {"ok": True, "result": {"surface": self.menu_surface, "changed": requested is not None}}


class TuiTests(Sandbox):
    def test_active_palette_and_missing_palette_fallback(self):
        self.write_palette()
        theme, warning = omarchy_theme(self.paths)
        self.assertEqual(theme.name, "thpm-omarchy")
        self.assertEqual(theme.variables["thpm-border"], COLORS["lighter_bg"])
        self.assertIsNone(warning)
        (self.paths.current_theme / "colors.toml").unlink()
        theme, warning = omarchy_theme(self.paths)
        self.assertEqual(theme.name, "thpm-fallback")
        self.assertIn("using fallback", warning)

    def test_tui_uses_normalized_canonical_palette(self):
        self.paths.current_theme.mkdir(parents=True)
        (self.paths.current_theme / "colors.toml").write_text('background = "#111111"\n')
        completed = subprocess.CompletedProcess(
            [], 0, resolver_output(CANONICAL_COLORS), ""
        )
        with patch("thpm.palette.shutil.which", return_value="resolver"), patch(
            "thpm.palette.subprocess.run", return_value=completed
        ):
            theme, warning = omarchy_theme(self.paths)
        self.assertIsNone(warning)
        self.assertEqual(theme.background, COLORS["bg"])
        self.assertEqual(theme.foreground, COLORS["fg"])
        self.assertEqual(theme.variables["thpm-border"], COLORS["lighter_bg"])

    def test_headless_navigation_search_toggle_and_doctor(self):
        async def exercise():
            self.write_palette()
            service = FakeTuiService()
            app = ThpmTui(service, self.paths)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause(0.2)
                self.assertEqual(app.theme, "thpm-omarchy")
                self.assertEqual(len(app.query("#plugin-list PluginRow")), 2)
                await pilot.press("2")
                search = app.query_one("#integration-search")
                search.value = "fish"
                await pilot.pause()
                self.assertEqual(len(app.query("#plugin-list PluginRow")), 1)
                search.value = ""
                await pilot.pause()
                plugin_list = app.query_one("#plugin-list")
                plugin_list.index = 0
                plugin_list.focus()
                await pilot.press("space")
                await pilot.pause(0.2)
                self.assertEqual(service.mutations, [("fish", False)])
                await pilot.press("3")
                await pilot.pause(0.2)
                self.assertGreaterEqual(service.doctor_calls, 1)
                self.assertIn("No issues found", str(app.query_one(".healthy-result").render()))
        asyncio.run(exercise())

    def test_small_terminal_uses_resize_guard(self):
        async def exercise():
            app = ThpmTui(FakeTuiService(), self.paths)
            async with app.run_test(size=(79, 23)) as pilot:
                await pilot.pause()
                self.assertTrue(app.has_class("too-small"))
        asyncio.run(exercise())

    def test_update_requires_confirmation_before_apply(self):
        async def exercise():
            service = FakeTuiService()
            service.update_available = True
            app = ThpmTui(service, self.paths)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause(0.2)
                await pilot.press("4")
                await pilot.click("#update-action")
                await pilot.pause()
                self.assertEqual(service.update_apply_calls, 0)
                await pilot.click("#confirm-update")
                await pilot.pause(0.2)
                self.assertEqual(service.update_apply_calls, 1)
                self.assertTrue(app.query_one("#restart-shell").display)
        asyncio.run(exercise())

    def test_system_menu_launcher_toggles_gui_and_tui(self):
        async def exercise():
            service = FakeTuiService()
            app = ThpmTui(service, self.paths)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause(0.2)
                await pilot.press("4")
                self.assertTrue(app.query_one("#menu-surface-gui", Button).has_class("selected"))
                await pilot.click("#menu-surface-tui")
                await pilot.pause(0.2)
                self.assertEqual(service.surface_calls, ["tui"])
                self.assertTrue(app.query_one("#menu-surface-tui", Button).has_class("selected"))
                self.assertIn("terminal interface", str(app.query_one("#menu-surface-detail").render()))
                await pilot.click("#menu-surface-gui")
                await pilot.pause(0.2)
                self.assertEqual(service.surface_calls, ["tui", "gui"])
        asyncio.run(exercise())

    def test_donation_action_opens_kofi(self):
        async def exercise():
            app = ThpmTui(FakeTuiService(), self.paths)
            with patch.object(app, "open_url") as launch:
                async with app.run_test(size=(120, 40)) as pilot:
                    await pilot.pause(0.2)
                    link = app.query_one("#donate-link", Link)
                    self.assertEqual(link.url, "https://ko-fi.com/oldjobobo")
                    await pilot.press("1")
                    self.assertTrue(link.display)
                    await pilot.click("#donate-link")
                    await pilot.pause()
            launch.assert_called_once_with("https://ko-fi.com/oldjobobo")
        asyncio.run(exercise())


class ZedTests(Sandbox):
    def setUp(self):
        super().setUp()
        command_probe = patch("thpm.snapshot.shutil.which", return_value="/usr/bin/zeditor")
        command_probe.start()
        self.addCleanup(command_probe.stop)

    def write_zed(self, name: str = "zed.json", *, appearance: str = "dark") -> Path:
        source = self.paths.current_theme / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(zed_theme(name, appearance))
        return source

    def test_authored_source_precedence_and_normalization(self):
        canonical = self.write_zed("zed.json")
        self.write_zed("aether.zed.json")
        result = apply("zed-extra", self.paths)
        target = self.paths.config_home / "zed/themes/thpm-current.json"
        payload = json.loads(target.read_text())
        self.assertEqual(payload["name"], THEME_NAME)
        self.assertEqual(payload["themes"][0]["name"], THEME_NAME)
        self.assertEqual(payload["author"], "Theme Author")
        self.assertEqual(payload["themes"][0]["style"]["background"], "#123456")
        self.assertIn(str(target), result.changed)
        self.assertEqual(zed_status(self.paths)["source"], str(canonical))

        unchanged = apply("zed-extra", self.paths)
        self.assertEqual(unchanged.status, "unchanged")
        self.assertEqual(unchanged.changed, [])

    def test_aether_source_is_supported_without_touching_aether_or_omazed(self):
        self.write_zed("aether.zed.json")
        aether = self.paths.config_home / "zed/themes/aether.json"
        omazed = self.paths.config_home / "zed/themes/omazed.json"
        aether.parent.mkdir(parents=True)
        aether.write_text("aether user theme")
        omazed.write_text("generated fallback")
        apply("zed-extra", self.paths)
        self.assertEqual(aether.read_text(), "aether user theme")
        self.assertEqual(omazed.read_text(), "generated fallback")
        self.assertTrue((self.paths.config_home / "zed/themes/thpm-current.json").is_file())

    def test_enabling_through_normal_plugin_flow_selects_the_authored_theme(self):
        self.write_zed()
        settings = self.paths.config_home / "zed/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text('{"theme": "Old"}\n')
        stages: list[str] = []
        service = Service(
            self.paths, progress=lambda message, _detail=None: stages.append(message)
        )

        completed = service.set_enabled("zed-extra", True, refresh=False)

        self.assertTrue(completed["ok"])
        self.assertNotIn("confirmationRequired", completed)
        self.assertEqual(zed_status(self.paths)["selectedTheme"], THEME_NAME)
        self.assertTrue(load(self.paths)["zed-extra"])
        self.assertEqual(
            stages,
            [
                "Checking Zed theme",
                "Backing up Zed settings",
                "Installing and selecting Zed theme",
            ],
        )

    def test_disable_removes_authored_target_without_touching_omazed(self):
        self.write_zed()
        omazed = self.paths.config_home / "zed/themes/omazed.json"
        omazed.parent.mkdir(parents=True)
        omazed.write_text("generated fallback")
        apply("zed-extra", self.paths)
        payload = Service(self.paths).set_enabled("zed-extra", False, refresh=False)
        self.assertTrue(payload["ok"])
        self.assertFalse((self.paths.config_home / "zed/themes/thpm-current.json").exists())
        self.assertEqual(omazed.read_text(), "generated fallback")

    def test_authored_source_requires_zed_but_missing_source_allows_cleanup(self):
        self.write_zed()
        available, missing, _warnings = inspect_readiness(
            "zed-extra", self.paths, which=lambda _command: None
        )
        self.assertFalse(available)
        self.assertIn("zeditor", missing)
        (self.paths.current_theme / "zed.json").unlink()
        available, missing, _warnings = inspect_readiness(
            "zed-extra", self.paths, which=lambda _command: None
        )
        self.assertTrue(available)
        self.assertEqual(missing, [])

    def test_validation_failures_do_not_mutate_target(self):
        target = self.paths.config_home / "zed/themes/thpm-current.json"
        target.parent.mkdir(parents=True)
        target.write_text("keep")
        cases = [
            "not json",
            json.dumps([]),
            json.dumps({"themes": []}),
            json.dumps({"themes": [{"appearance": "dark", "style": {}}, {"appearance": "light", "style": {}}]}),
            json.dumps({"themes": [{"appearance": "system", "style": {}}]}),
            json.dumps({"themes": [{"appearance": "dark", "style": "bad"}]}),
            '{"themes":[{"appearance":"dark","style":{"bad":NaN}}]}',
        ]
        for content in cases:
            with self.subTest(content=content):
                source = self.paths.current_theme / "zed.json"
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text(content)
                with self.assertRaises(ZedThemeError):
                    apply("zed-extra", self.paths)
                self.assertEqual(target.read_text(), "keep")
        source.write_bytes(b"\xff")
        with self.assertRaises(ZedThemeError):
            apply("zed-extra", self.paths)
        self.assertEqual(target.read_text(), "keep")
        source.write_bytes(b"x" * (MAX_THEME_BYTES + 1))
        with self.assertRaises(ZedThemeError):
            apply("zed-extra", self.paths)
        self.assertEqual(target.read_text(), "keep")

    def test_symlinked_source_is_rejected(self):
        real = self.paths.home / "theme.json"
        real.write_text(zed_theme())
        source = self.paths.current_theme / "zed.json"
        source.parent.mkdir(parents=True)
        source.symlink_to(real)
        with self.assertRaisesRegex(ZedThemeError, "regular file"):
            normalized(source)

    def test_missing_source_restores_target_and_preserves_user_changes(self):
        source = self.write_zed()
        target = self.paths.config_home / "zed/themes/thpm-current.json"
        target.parent.mkdir(parents=True)
        target.write_text("user default")
        apply("zed-extra", self.paths)
        source.unlink()
        restored = apply("zed-extra", self.paths)
        self.assertEqual(target.read_text(), "user default")
        self.assertIn(str(target), restored.changed)

        source = self.write_zed()
        apply("zed-extra", self.paths)
        target.write_text("user changed")
        source.unlink()
        preserved = apply("zed-extra", self.paths)
        self.assertEqual(target.read_text(), "user changed")
        self.assertIn("preserved user-modified file", preserved.warnings[0])

    def test_legacy_omarchy_target_state_is_migrated_fail_closed(self):
        legacy = self.paths.config_home / "zed/themes/omarchy.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("managed old")
        state = self.paths.managed_asset_state_dir / "zed-extra.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({
            "existed": False,
            "managedSha256": hashlib.sha256(b"managed old").hexdigest(),
            "managedMode": 0o644,
        }))
        self.write_zed()
        result = apply("zed-extra", self.paths)
        self.assertFalse(legacy.exists())
        self.assertIn(str(legacy), result.changed)

        legacy.write_text("user changed")
        state.write_text("invalid")
        preserved = apply("zed-extra", self.paths)
        self.assertEqual(legacy.read_text(), "user changed")
        self.assertIn("state is invalid", " ".join(preserved.warnings))

    def test_missing_source_migrates_a_positively_matched_stateless_legacy_target(self):
        installed = self.paths.config_home / "omarchy/themes/old"
        installed.mkdir(parents=True)
        content = zed_theme()
        (installed / "zed.json").write_text(content)
        legacy = self.paths.config_home / "zed/themes/omarchy.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text(content)

        result = apply("zed-extra", self.paths)

        self.assertFalse(legacy.exists())
        self.assertIn(str(legacy), result.changed)

    def test_status_reads_jsonc_string_and_mode_object(self):
        self.write_zed()
        settings = self.paths.config_home / "zed/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text('// keep\n{"theme": "THPM Current", "x": [1, 2,],}\n')
        self.assertEqual(zed_status(self.paths)["selectedTheme"], THEME_NAME)
        settings.write_text('{"theme": {"mode": "system", "light": "Light", // note\n"dark": "Dark",},}\n')
        self.assertEqual(zed_status(self.paths)["selectedTheme"], "Dark")
        (self.paths.current_theme / "zed.json").write_text(zed_theme(appearance="light"))
        self.assertEqual(zed_status(self.paths)["selectedTheme"], "Light")
        settings.write_text('{"theme": "Name, }"}\n')
        self.assertEqual(zed_status(self.paths)["selectedTheme"], "Name, }")

    def test_setup_confirmation_backup_and_comment_preservation(self):
        self.write_zed()
        settings = self.paths.config_home / "zed/settings.json"
        settings.parent.mkdir(parents=True)
        original = '// user comment\n{\n  "project_panel": {"dock": "left"},\n  "theme": {"mode": "system", "light": "One Light", "dark": "Old"}\n}\n'
        settings.write_text(original)
        pending = Service(self.paths).zed_setup()
        self.assertFalse(pending["ok"])
        self.assertTrue(pending["confirmationRequired"])
        self.assertEqual(settings.read_text(), original)
        completed = Service(self.paths).zed_setup(confirmed=True)
        self.assertTrue(completed["ok"])
        self.assertIn("// user comment", settings.read_text())
        self.assertIn('"project_panel": {"dock": "left"}', settings.read_text())
        self.assertIn('"theme": "THPM Current"', settings.read_text())
        self.assertEqual(self.paths.zed_settings_backup_file.read_text(), original)
        self.assertTrue(load(self.paths)["zed-extra"])
        backup = self.paths.zed_settings_backup_file.read_text()
        configure_settings(self.paths)
        self.assertEqual(self.paths.zed_settings_backup_file.read_text(), backup)

    def test_setup_adds_missing_theme_key_without_dropping_comments(self):
        self.write_zed()
        settings = self.paths.config_home / "zed/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text('{\n  // keep this setting\n  "buffer_font_size": 15\n}\n')
        result = Service(self.paths).zed_setup(confirmed=True)
        self.assertTrue(result["ok"])
        self.assertIn("// keep this setting", settings.read_text())
        self.assertEqual(zed_status(self.paths)["selectedTheme"], THEME_NAME)

    def test_setup_fails_before_enabling_when_settings_are_not_safe_to_edit(self):
        self.write_zed()
        settings = self.paths.config_home / "zed/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text('{"theme": "Old", broken}\n')
        result = Service(self.paths).zed_setup(confirmed=True)
        self.assertFalse(result["ok"])
        self.assertFalse(load(self.paths)["zed-extra"])
        self.assertFalse((self.paths.config_home / "zed/themes/thpm-current.json").exists())
        self.assertEqual(settings.read_text(), '{"theme": "Old", broken}\n')

        settings.write_text('{"unrelated": nope, "theme": "Old"}\n')
        result = Service(self.paths).zed_setup(confirmed=True)
        self.assertFalse(result["ok"])
        self.assertFalse(load(self.paths)["zed-extra"])
        self.assertEqual(settings.read_text(), '{"unrelated": nope, "theme": "Old"}\n')

    def test_setup_rolls_back_settings_state_and_target_when_apply_fails(self):
        self.write_zed()
        settings = self.paths.config_home / "zed/settings.json"
        settings.parent.mkdir(parents=True)
        original = '// keep\n{"theme": "Old"}\n'
        settings.write_text(original)

        with patch("thpm.service.apply_integration", side_effect=RuntimeError("apply failed")):
            result = Service(self.paths).zed_setup(confirmed=True)

        self.assertFalse(result["ok"])
        self.assertFalse(load(self.paths)["zed-extra"])
        self.assertEqual(settings.read_text(), original)
        self.assertFalse((self.paths.config_home / "zed/themes/thpm-current.json").exists())

    def test_setup_restores_legacy_target_and_backup_when_install_fails(self):
        source = self.write_zed()
        legacy = self.paths.config_home / "zed/themes/omarchy.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(source.read_bytes())
        settings = self.paths.config_home / "zed/settings.json"
        settings.write_text('{"theme": "Old"}\n')

        with patch(
            "thpm.integrations._install_optional_asset",
            side_effect=RuntimeError("install failed"),
        ):
            result = Service(self.paths).zed_setup(confirmed=True)

        self.assertFalse(result["ok"])
        self.assertEqual(legacy.read_bytes(), source.read_bytes())
        self.assertEqual(settings.read_text(), '{"theme": "Old"}\n')
        self.assertFalse(self.paths.zed_settings_backup_file.exists())
        self.assertFalse(
            (self.paths.managed_asset_state_dir / "zed-extra.legacy-checked").exists()
        )
        self.assertFalse(load(self.paths)["zed-extra"])

    def test_human_status_renders_zed_diagnostics(self):
        stream = io.StringIO()
        render(Service(self.paths).zed_status(), console=Console(file=stream, force_terminal=False))
        output = stream.getvalue()
        self.assertIn("Source", output)
        self.assertIn("Target", output)
        self.assertIn("Selected", output)
        self.assertIn("Omazed", output)

    def test_status_reports_omazed_fallback_without_claiming_automatic_selection(self):
        fallback = self.paths.config_home / "zed/themes/omazed.json"
        fallback.parent.mkdir(parents=True)
        fallback.write_text("generated")
        result = zed_status(self.paths, which=lambda command: "/usr/bin/omazed")
        self.assertEqual(result["omazed"]["command"], "/usr/bin/omazed")
        self.assertTrue(result["omazed"]["outputExists"])
        self.assertIn("select Omazed", " ".join(result["warnings"]))


class IntegrationTests(Sandbox):
    def write_local_vscode_theme(self, *, unsafe: bool = False):
        theme = self.paths.current_theme
        extension = theme / "vscode-extension"
        (extension / "themes").mkdir(parents=True)
        (theme / "vscode.json").write_text(json.dumps({"name": "Dos-Moos", "extension": "local.theme-dos-moos"}))
        manifest = {
            "name": "theme-dos-moos",
            "publisher": "local",
            "version": "1.0.0",
            "engines": {"vscode": "^1.70.0"},
            "contributes": {"themes": [{"label": "Dos-Moos", "uiTheme": "vs-dark", "path": "./themes/theme.json"}]},
        }
        if unsafe:
            manifest["main"] = "./index.js"
            (extension / "index.js").write_text("module.exports = {}\n")
        (extension / "package.json").write_text(json.dumps(manifest))
        (extension / "themes/theme.json").write_text(json.dumps({"name": "Dos-Moos", "type": "dark", "colors": {}}))

    def test_disabling_browser_restores_stylesheet_and_removes_import(self):
        base = self.paths.home / ".mozilla/firefox"
        profile = base / "profile.default"
        profile.mkdir(parents=True)
        (base / "profiles.ini").write_text("[Install1]\nDefault=profile.default\n")
        source = self.paths.current_theme / "thpm-firefox.css"
        source.parent.mkdir(parents=True)
        source.write_text("theme css")
        managed = profile / "chrome/thpm-firefox.css"
        managed.parent.mkdir(parents=True)
        managed.write_text("user css")
        apply("firefox", self.paths)
        assets = Path(__file__).parents[1] / "assets"
        enabled = load(self.paths)
        enabled["firefox"] = True
        save(self.paths, enabled)
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            payload = Service(self.paths).set_enabled("firefox", False, refresh=False)
        self.assertTrue(payload["ok"])
        self.assertEqual(managed.read_text(), "user css")
        self.assertFalse((profile / "chrome/userChrome.css").exists())
        self.assertFalse(source.exists())

    def test_browser_profile_cannot_escape_profile_root(self):
        generated = self.paths.current_theme / "thpm-firefox.css"
        generated.parent.mkdir(parents=True)
        generated.write_text("/* generated */\n")
        base = self.paths.home / ".mozilla/firefox"
        base.mkdir(parents=True)
        (base / "profiles.ini").write_text("[Install1]\nDefault=../../escape\n")
        with self.assertRaisesRegex(ValueError, "escapes"):
            _browser_import(self.paths, "firefox", base)

    def test_discord_cleanup_restores_displaced_theme(self):
        source = self.paths.current_theme / "thpm-vencord.theme.css"
        source.parent.mkdir(parents=True)
        source.write_text("theme output")
        directory = self.paths.config_home / "Vencord/themes"
        directory.mkdir(parents=True)
        target = directory / "vencord.theme.css"
        target.write_text("user theme")
        apply("discord", self.paths)
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            payload = Service(self.paths).set_enabled("discord", False, refresh=False)
        self.assertTrue(payload["ok"])
        self.assertEqual(target.read_text(), "user theme")
        self.assertFalse(source.exists())

    def test_vencord_asset_copy_does_not_require_palette(self):
        self.paths.current_theme.mkdir(parents=True)
        source = self.paths.current_theme / "vencord.theme.css"
        source.write_text("/* current theme */\n")
        target_dir = self.paths.config_home / "vesktop/themes"
        target_dir.mkdir(parents=True)
        result = apply("discord", self.paths)
        target = target_dir / "vencord.theme.css"
        self.assertEqual(target.read_bytes(), source.read_bytes())
        self.assertIn(str(target), result.changed)
        self.assertEqual(result.status, "applied")
        self.assertFalse((target_dir / "omarchy.theme.css").exists())

    def test_system24_uses_generated_fallback_when_theme_has_no_asset(self):
        generated = self.paths.current_theme / "thpm-vencord-system24.theme.css"
        generated.parent.mkdir(parents=True)
        generated.write_text('@import url("system24.css");\n')
        target_dir = self.paths.config_home / "vesktop/themes"
        target_dir.mkdir(parents=True)
        result = apply("discord-system24", self.paths)
        target = target_dir / "vencord.theme.css"
        self.assertEqual(target.read_bytes(), generated.read_bytes())
        self.assertIn(str(target), result.changed)

    def test_zellij_applies_theme_asset_and_removes_legacy_block(self):
        theme_asset = self.paths.current_theme / "zellij.kdl"
        theme_asset.parent.mkdir(parents=True)
        theme_asset.write_text('themes { current { fg "#ffffff" } }\n')
        config = self.paths.config_home / "zellij/config.kdl"
        config.parent.mkdir(parents=True)
        config.write_text('theme "current"\n\n// thpm-zellij-theme-start\nthemes { current {} }\n// thpm-zellij-theme-end\n')
        result = apply("zellij", self.paths)
        installed = self.paths.config_home / "zellij/themes/thpm.kdl"
        self.assertEqual(
            installed.read_text(), 'themes { thpm-current { fg "#ffffff" } }\n'
        )
        self.assertEqual(config.read_text(), 'theme "thpm-current"\n')
        self.assertIn(str(config), result.changed)
        self.assertIn("restart active Zellij sessions", result.warnings[0])
        saved = json.loads(self.paths.zellij_theme_state_file.read_text())
        self.assertEqual(saved["themeOption"], 'theme "current"')

    def test_zellij_without_theme_asset_restores_previous_selection(self):
        theme_asset = self.paths.current_theme / "zellij.kdl"
        theme_asset.parent.mkdir(parents=True)
        theme_asset.write_text(
            'themes { current { text_selected { background 36 55 46 } } }\n'
        )
        config = self.paths.config_home / "zellij/config.kdl"
        config.parent.mkdir(parents=True)
        config.write_text('theme "catppuccin"\npane_frames true\n')
        apply("zellij", self.paths)
        theme_asset.unlink()
        generated = self.paths.current_theme / "thpm-zellij.kdl"
        generated.write_text('themes { generated { fg "#ffffff" } }\n')
        result = apply("zellij", self.paths)
        self.assertEqual(config.read_text(), 'theme "catppuccin"\npane_frames true\n')
        self.assertFalse((self.paths.config_home / "zellij/themes/thpm.kdl").exists())
        self.assertFalse(self.paths.zellij_theme_state_file.exists())
        self.assertIn("restart active Zellij sessions", result.warnings[0])

    def test_zellij_hook_without_asset_runs_cleanup_instead_of_skipping(self):
        config = self.paths.config_home / "zellij/config.kdl"
        config.parent.mkdir(parents=True)
        config.write_text('theme "thpm-current"\n')
        target = self.paths.config_home / "zellij/themes/thpm.kdl"
        target.parent.mkdir(parents=True)
        target.write_text('themes { thpm-current {} }\n')
        with patch("thpm.integrations.shutil.which", return_value=None):
            result = apply_enabled(self.paths, {"zellij": True})
        zellij = next(item for item in result["results"] if item["id"] == "zellij")
        self.assertEqual(zellij["status"], "applied")
        self.assertEqual(config.read_text(), "")
        self.assertFalse(target.exists())
        self.assertIn("restart active Zellij sessions", str(zellij["warnings"]))

    def test_zellij_preserves_an_already_normalized_theme_asset(self):
        theme_asset = self.paths.current_theme / "zellij.kdl"
        theme_asset.parent.mkdir(parents=True)
        theme_asset.write_text('themes { thpm-current { fg "#ffffff" } }\n')
        apply("zellij", self.paths)
        installed = self.paths.config_home / "zellij/themes/thpm.kdl"
        self.assertEqual(installed.read_bytes(), theme_asset.read_bytes())

    def test_zellij_without_asset_removes_legacy_selection_to_restore_default(self):
        config = self.paths.config_home / "zellij/config.kdl"
        config.parent.mkdir(parents=True)
        config.write_text('theme "thpm-current"\npane_frames true\n')
        target = self.paths.config_home / "zellij/themes/thpm.kdl"
        target.parent.mkdir(parents=True)
        target.write_text('themes { thpm-current {} }\n')
        result = apply("zellij", self.paths)
        self.assertEqual(config.read_text(), "pane_frames true\n")
        self.assertFalse(target.exists())
        self.assertEqual(result.status, "applied")

    def test_disabling_zellij_restores_selection_and_removes_managed_theme(self):
        theme_asset = self.paths.current_theme / "zellij.kdl"
        theme_asset.parent.mkdir(parents=True)
        theme_asset.write_text('themes { current { fg "#ffffff" } }\n')
        config = self.paths.config_home / "zellij/config.kdl"
        config.parent.mkdir(parents=True)
        config.write_text('theme "default"\n')
        apply("zellij", self.paths)
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            payload = Service(self.paths).set_enabled("zellij", False, refresh=False)
        self.assertTrue(payload["ok"])
        self.assertEqual(config.read_text(), 'theme "default"\n')
        self.assertFalse((self.paths.config_home / "zellij/themes/thpm.kdl").exists())
        self.assertIn("restart active Zellij sessions", str(payload["warnings"]))

    def test_zellij_cleanup_removes_legacy_block_with_manual_selection(self):
        config = self.paths.config_home / "zellij/config.kdl"
        config.parent.mkdir(parents=True)
        config.write_text(
            'theme "catppuccin"\n// thpm-zellij-theme-start\n'
            'themes { current {} }\n// thpm-zellij-theme-end\npane_frames true\n'
        )
        result = apply("zellij", self.paths)
        self.assertEqual(config.read_text(), 'theme "catppuccin"\npane_frames true\n')
        self.assertIn(str(config), result.changed)

    def test_optional_assets_restore_the_files_they_displaced(self):
        cases = {
            "typora": ("typora.css", self.paths.config_home / "Typora/themes/omarchy.css"),
            "swaync": ("colors.css", self.paths.config_home / "swaync/colors.css"),
            "windsurf": (
                "vscode-theme.json",
                self.paths.home / ".windsurf/extensions/local.omarchy-theme/themes/omarchy.json",
            ),
            "cliamp": ("cliamp.toml", self.paths.config_home / "cliamp/themes/omarchy.toml"),
        }
        with patch("thpm.integrations._reload", return_value=[]):
            for plugin_id, (asset_name, target) in cases.items():
                with self.subTest(plugin=plugin_id):
                    source = self.paths.current_theme / asset_name
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_text(f"{plugin_id} theme")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(f"{plugin_id} user default")
                    apply(plugin_id, self.paths)
                    self.assertEqual(target.read_text(), f"{plugin_id} theme")
                    source.unlink()
                    result = apply(plugin_id, self.paths)
                    self.assertEqual(target.read_text(), f"{plugin_id} user default")
                    self.assertIn(str(target), result.changed)

    def test_legacy_optional_output_is_removed_only_when_it_matches_a_theme_asset(self):
        installed_theme = self.paths.config_home / "omarchy/themes/old"
        installed_theme.mkdir(parents=True)
        (installed_theme / "colors.css").write_text("old managed colors")
        target = self.paths.config_home / "swaync/colors.css"
        target.parent.mkdir(parents=True)
        target.write_text("old managed colors")
        with patch("thpm.integrations.shutil.which", return_value=None):
            result = apply("swaync", self.paths)
        self.assertFalse(target.exists())
        self.assertIn(str(target), result.changed)

        marker = self.paths.managed_asset_state_dir / "swaync.legacy-checked"
        marker.unlink()
        target.write_text("user colors")
        with patch("thpm.integrations.shutil.which", return_value=None):
            preserved = apply("swaync", self.paths)
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(), "user colors")
        self.assertEqual(preserved.status, "unchanged")

    def test_optional_asset_without_previous_file_is_removed_when_absent(self):
        source = self.paths.current_theme / "typora.css"
        source.parent.mkdir(parents=True)
        source.write_text("theme")
        target = self.paths.config_home / "Typora/themes/omarchy.css"
        apply("typora", self.paths)
        source.unlink()
        result = apply("typora", self.paths)
        self.assertFalse(target.exists())
        self.assertIn(str(target), result.changed)

    def test_optional_asset_interrupted_update_keeps_original_backup(self):
        source = self.paths.current_theme / "typora.css"
        source.parent.mkdir(parents=True)
        source.write_text("theme a")
        target = self.paths.config_home / "Typora/themes/omarchy.css"
        target.parent.mkdir(parents=True)
        target.write_text("user default")
        apply("typora", self.paths)
        source.write_text("theme b")
        with patch(
            "thpm.integrations.atomic_copy", side_effect=RuntimeError("interrupted")
        ), self.assertRaisesRegex(RuntimeError, "interrupted"):
            apply("typora", self.paths)
        source.unlink()
        apply("typora", self.paths)
        self.assertEqual(target.read_text(), "user default")

    def test_optional_asset_equal_bytes_normalizes_mode_and_cleans_up(self):
        source = self.paths.current_theme / "typora.css"
        source.parent.mkdir(parents=True)
        source.write_text("same")
        target = self.paths.config_home / "Typora/themes/omarchy.css"
        target.parent.mkdir(parents=True)
        target.write_text("same")
        target.chmod(0o600)
        apply("typora", self.paths)
        self.assertEqual(target.stat().st_mode & 0o777, 0o644)
        source.unlink()
        apply("typora", self.paths)
        self.assertFalse(target.exists())

    def test_optional_asset_missing_backup_fails_closed(self):
        source = self.paths.current_theme / "typora.css"
        source.parent.mkdir(parents=True)
        source.write_text("theme")
        target = self.paths.config_home / "Typora/themes/omarchy.css"
        target.parent.mkdir(parents=True)
        target.write_text("user default")
        apply("typora", self.paths)
        (self.paths.managed_asset_state_dir / "typora.backup").unlink()
        source.unlink()
        result = apply("typora", self.paths)
        self.assertEqual(target.read_text(), "theme")
        self.assertIn("backup is missing", result.warnings[0])

    def test_optional_asset_corrupt_backup_and_state_schema_fail_closed(self):
        source = self.paths.current_theme / "typora.css"
        source.parent.mkdir(parents=True)
        source.write_text("theme")
        target = self.paths.config_home / "Typora/themes/omarchy.css"
        target.parent.mkdir(parents=True)
        target.write_text("user default")
        apply("typora", self.paths)
        backup = self.paths.managed_asset_state_dir / "typora.backup"
        backup.write_text("corrupted")
        source.unlink()
        corrupted = apply("typora", self.paths)
        self.assertEqual(target.read_text(), "theme")
        self.assertIn("backup is missing or invalid", corrupted.warnings[0])

        state = self.paths.managed_asset_state_dir / "typora.json"
        state.write_text(json.dumps({"existed": True, "priorType": "bad"}))
        invalid = apply("typora", self.paths)
        self.assertEqual(target.read_text(), "theme")
        self.assertIn("state is invalid", invalid.warnings[0])

    def test_optional_asset_restores_previous_symlink(self):
        source = self.paths.current_theme / "typora.css"
        source.parent.mkdir(parents=True)
        source.write_text("theme")
        original = self.paths.home / "my-typora.css"
        original.write_text("user default")
        target = self.paths.config_home / "Typora/themes/omarchy.css"
        target.parent.mkdir(parents=True)
        target.symlink_to(original)
        apply("typora", self.paths)
        self.assertFalse(target.is_symlink())
        source.unlink()
        apply("typora", self.paths)
        self.assertTrue(target.is_symlink())
        self.assertEqual(target.readlink(), original)

    def test_optional_asset_cleanup_preserves_a_user_modified_target(self):
        source = self.paths.current_theme / "cliamp.toml"
        source.parent.mkdir(parents=True)
        source.write_text("theme")
        target = self.paths.config_home / "cliamp/themes/omarchy.toml"
        apply("cliamp", self.paths)
        target.write_text("user changed this after THPM")
        source.unlink()
        result = apply("cliamp", self.paths)
        self.assertEqual(target.read_text(), "user changed this after THPM")
        self.assertIn("preserved user-modified file", result.warnings[0])

    def test_branding_restores_missing_assets_independently(self):
        about = self.paths.current_theme / "about.txt"
        screensaver = self.paths.current_theme / "screensaver.txt"
        about.parent.mkdir(parents=True)
        about.write_text("theme about")
        screensaver.write_text("theme screensaver")
        about_target = self.paths.config_home / "omarchy/branding/about.txt"
        screen_target = self.paths.config_home / "omarchy/branding/screensaver.txt"
        about_target.parent.mkdir(parents=True)
        about_target.write_text("user about")
        screen_target.write_text("user screensaver")
        apply("branding", self.paths)
        about.unlink()
        screensaver.write_text("new theme screensaver")
        apply("branding", self.paths)
        self.assertEqual(about_target.read_text(), "user about")
        self.assertEqual(screen_target.read_text(), "new theme screensaver")

    def test_swaync_cleanup_does_not_require_the_reload_command(self):
        source = self.paths.current_theme / "colors.css"
        source.parent.mkdir(parents=True)
        source.write_text("theme")
        target = self.paths.config_home / "swaync/colors.css"
        target.parent.mkdir(parents=True)
        target.write_text("user default")
        with patch("thpm.integrations._reload", return_value=[]):
            apply("swaync", self.paths)
        source.unlink()
        with patch("thpm.integrations.shutil.which", return_value=None):
            result = apply_enabled(self.paths, {"swaync": True})
        swaync = next(item for item in result["results"] if item["id"] == "swaync")
        self.assertEqual(swaync["status"], "applied")
        self.assertEqual(target.read_text(), "user default")

    def test_optional_asset_cleanup_does_not_require_the_application(self):
        target = self.paths.config_home / "Typora/themes/omarchy.css"
        state = self.paths.managed_asset_state_dir / "typora.json"
        target.parent.mkdir(parents=True)
        target.write_text("theme")
        state.parent.mkdir(parents=True)
        state.write_text(
            json.dumps(
                {
                    "existed": False,
                    "managedSha256": hashlib.sha256(b"theme").hexdigest(),
                    "managedMode": 0o644,
                }
            )
        )
        with patch("thpm.integrations.shutil.which", return_value=None):
            result = apply_enabled(self.paths, {"typora": True})
        typora = next(item for item in result["results"] if item["id"] == "typora")
        self.assertEqual(typora["status"], "applied")
        self.assertFalse(target.exists())

    def test_zellij_rejects_unsafe_saved_theme_option(self):
        config = self.paths.config_home / "zellij/config.kdl"
        target = self.paths.config_home / "zellij/themes/thpm.kdl"
        config.parent.mkdir(parents=True)
        target.parent.mkdir(parents=True)
        config.write_text('theme "thpm-current"\npane_frames true\n')
        target.write_text("old theme")
        self.paths.zellij_theme_state_file.parent.mkdir(parents=True)
        self.paths.zellij_theme_state_file.write_text(
            json.dumps(
                {
                    "configExisted": True,
                    "themeOption": 'bogus }\ncorrupted true',
                }
            )
        )
        result = apply("zellij", self.paths)
        self.assertEqual(config.read_text(), 'theme "thpm-current"\npane_frames true\n')
        self.assertEqual(target.read_text(), "old theme")
        self.assertIn("state is invalid", result.warnings[0])

        self.paths.zellij_theme_state_file.write_text(
            json.dumps(
                {
                    "configExisted": True,
                    "themeOption": 'theme "safe" } corrupted true',
                }
            )
        )
        single_line = apply("zellij", self.paths)
        self.assertEqual(config.read_text(), 'theme "thpm-current"\npane_frames true\n')
        self.assertIn("state is invalid", single_line.warnings[0])

    def test_invalid_zellij_state_with_source_does_not_change_installed_theme(self):
        source = self.paths.current_theme / "zellij.kdl"
        source.parent.mkdir(parents=True)
        source.write_text('themes { next { fg "white" } }\n')
        config = self.paths.config_home / "zellij/config.kdl"
        target = self.paths.config_home / "zellij/themes/thpm.kdl"
        config.parent.mkdir(parents=True)
        target.parent.mkdir(parents=True)
        config.write_text('theme "thpm-current"\n')
        target.write_text("old theme")
        self.paths.zellij_theme_state_file.parent.mkdir(parents=True)
        self.paths.zellij_theme_state_file.write_text("not json")
        with self.assertRaisesRegex(RuntimeError, "state is invalid"):
            apply("zellij", self.paths)
        self.assertEqual(target.read_text(), "old theme")

    def test_invalid_zellij_state_and_legacy_block_fail_closed(self):
        config = self.paths.config_home / "zellij/config.kdl"
        target = self.paths.config_home / "zellij/themes/thpm.kdl"
        config.parent.mkdir(parents=True)
        target.parent.mkdir(parents=True)
        config.write_text('theme "thpm-current"\n')
        target.write_text("themes { thpm-current {} }\n")
        self.paths.zellij_theme_state_file.parent.mkdir(parents=True)
        self.paths.zellij_theme_state_file.write_text("not json")
        invalid_state = apply("zellij", self.paths)
        self.assertEqual(config.read_text(), 'theme "thpm-current"\n')
        self.assertTrue(target.exists())
        self.assertIn("state is invalid", invalid_state.warnings[0])

        self.paths.zellij_theme_state_file.unlink()
        config.write_text(
            'theme "thpm-current"\n// thpm-zellij-theme-start\nthemes { current {} }\n'
        )
        malformed_block = apply("zellij", self.paths)
        self.assertTrue(target.exists())
        self.assertIn("block is incomplete", malformed_block.warnings[0])

    def test_app_reload_timeout_is_reported_without_stalling(self):
        with patch("thpm.integrations.shutil.which", return_value="/usr/bin/swaync-client"), patch(
            "thpm.integrations.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["swaync-client", "--reload-css"], 5),
        ) as run, self.assertRaisesRegex(RuntimeError, "reload timed out"):
            _reload("swaync")
        run.assert_called_once_with(
            ["swaync-client", "--reload-css"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )

    def test_steam_helper_is_bounded_and_quiet(self):
        script = self.paths.home / ".local/share/steam-adwaita/install.py"
        script.parent.mkdir(parents=True)
        script.touch()
        with patch("thpm.integrations.subprocess.run") as run:
            run.return_value.returncode = 0
            result = apply("steam", self.paths)
        self.assertEqual(result.status, "applied")
        run.assert_called_once_with(
            [str(script), "--color-theme", "omarchy"],
            cwd=script.parent,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

    def test_gtk_compat_preserves_user_css_and_removes_only_managed_content(self):
        source = self.paths.current_theme / "gtk.css"
        source.parent.mkdir(parents=True)
        source.write_text("@define-color accent #abcdef;\n")
        gtk3 = self.paths.config_home / "gtk-3.0/gtk.css"
        gtk3.parent.mkdir(parents=True)
        gtk3.write_text("button { padding: 4px; }\n")
        first = apply("gtk-css-compat", self.paths)
        self.assertEqual(first.status, "applied")
        self.assertIn('import url("thpm-theme.css")', gtk3.read_text())
        self.assertIn("button { padding: 4px; }", gtk3.read_text())
        self.assertEqual((gtk3.parent / "thpm-theme.css").read_bytes(), source.read_bytes())
        second = apply("gtk-css-compat", self.paths)
        self.assertEqual(second.status, "unchanged")
        source.unlink()
        cleanup = apply("gtk-css-compat", self.paths)
        self.assertEqual(cleanup.status, "applied")
        self.assertEqual(gtk3.read_text(), "button { padding: 4px; }\n")
        self.assertFalse((gtk3.parent / "thpm-theme.css").exists())

    def test_gtk_compat_preserves_user_stylesheet_symlink(self):
        source = self.paths.current_theme / "gtk.css"
        source.parent.mkdir(parents=True)
        source.write_text("@define-color accent #abcdef;\n")
        dotfile = self.paths.home / "dotfiles/gtk.css"
        dotfile.parent.mkdir(parents=True)
        dotfile.write_text("label { color: red; }\n")
        gtk = self.paths.config_home / "gtk-3.0/gtk.css"
        gtk.parent.mkdir(parents=True)
        gtk.symlink_to(dotfile)
        apply("gtk-css-compat", self.paths)
        self.assertTrue(gtk.is_symlink())
        self.assertIn("thpm-gtk-theme-start", dotfile.read_text())
        source.unlink()
        apply("gtk-css-compat", self.paths)
        self.assertTrue(gtk.is_symlink())
        self.assertEqual(dotfile.read_text(), "label { color: red; }\n")

    def test_vscode_extension_directory_without_local_descriptor_is_not_applicable(self):
        extension = self.paths.current_theme / "vscode-extension"
        extension.mkdir(parents=True)
        (extension / "package.json").write_text("{}\n")
        result = apply("vscode-local-compat", self.paths)
        self.assertEqual(result.status, "unchanged")
        self.assertIn("does not request", result.message)

    def test_local_vscode_theme_is_installed_once_and_verified(self):
        self.write_local_vscode_theme()
        installed = subprocess.CompletedProcess([], 0, "", "")
        listed_after = subprocess.CompletedProcess([], 0, "local.theme-dos-moos\n", "")
        with patch("thpm.compat.shutil.which", side_effect=lambda command: "/usr/bin/code" if command == "code" else None), patch(
            "thpm.compat.subprocess.run", side_effect=[installed, listed_after]
        ) as run:
            first = apply("vscode-local-compat", self.paths)
        self.assertEqual(first.status, "applied")
        self.assertEqual(first.actions, ["code installed local.theme-dos-moos"])
        self.assertEqual(run.call_count, 2)
        with patch("thpm.compat.shutil.which", side_effect=lambda command: "/usr/bin/code" if command == "code" else None), patch(
            "thpm.compat.subprocess.run", return_value=listed_after
        ) as run:
            second = apply("vscode-local-compat", self.paths)
        self.assertEqual(second.status, "unchanged")
        self.assertEqual(run.call_count, 1)

    def test_local_vscode_theme_respects_omarchy_skip_toggle(self):
        self.write_local_vscode_theme()
        with patch(
            "thpm.compat.shutil.which",
            side_effect=lambda command: f"/usr/bin/{command}" if command in {"code", "omarchy-toggle-enabled"} else None,
        ), patch(
            "thpm.compat.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, "", ""),
        ) as run:
            result = apply("vscode-local-compat", self.paths)
        self.assertEqual(result.status, "unchanged")
        self.assertIn("disabled by Omarchy toggles", result.message)
        self.assertEqual(run.call_count, 1)

    def test_local_vscode_theme_rejects_escaping_theme_path(self):
        self.write_local_vscode_theme()
        manifest_path = self.paths.current_theme / "vscode-extension/package.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["contributes"]["themes"][0]["path"] = "../../outside.json"
        manifest_path.write_text(json.dumps(manifest))
        (self.paths.current_theme / "outside.json").write_text("{}\n")
        with patch(
            "thpm.compat.shutil.which",
            side_effect=lambda command: "/usr/bin/code" if command == "code" else None,
        ):
            result = apply("vscode-local-compat", self.paths)
        self.assertEqual(result.status, "failed")
        self.assertIn("escapes or is missing", result.message)

    def test_local_vscode_theme_rejects_executable_extension(self):
        self.write_local_vscode_theme(unsafe=True)
        with patch(
            "thpm.compat.shutil.which",
            side_effect=lambda command: "/usr/bin/code" if command == "code" else None,
        ), patch("thpm.compat.subprocess.run") as run:
            result = apply("vscode-local-compat", self.paths)
        self.assertEqual(result.status, "failed")
        self.assertIn("may not declare main", result.message)
        run.assert_not_called()

    def test_browser_prefers_theme_asset_and_reports_both_managed_files(self):
        theme_asset = self.paths.current_theme / "firefox.css"
        generated = self.paths.current_theme / "thpm-firefox.css"
        theme_asset.parent.mkdir(parents=True)
        theme_asset.write_text("/* preferred */\n")
        generated.write_text("/* fallback */\n")
        base = self.paths.home / ".mozilla/firefox"
        profile = base / "profile.default"
        base.mkdir(parents=True)
        (base / "profiles.ini").write_text("[Install1]\nDefault=profile.default\n")
        result = apply("firefox", self.paths)
        managed = profile / "chrome/thpm-firefox.css"
        user_chrome = profile / "chrome/userChrome.css"
        self.assertEqual(managed.read_text(), "/* preferred */\n")
        self.assertEqual(result.status, "applied")
        self.assertEqual(set(result.changed), {str(managed), str(user_chrome)})

    def test_unresolved_generated_output_is_refused_and_reported_unavailable(self):
        generated = self.paths.current_theme / "thpm-fish.fish"
        generated.parent.mkdir(parents=True)
        generated.write_text('set -gx THPM_THEME_BG "{{ background }}"\n')
        target = self.paths.config_home / "fish/conf.d/thpm-theme.fish"
        with self.assertRaisesRegex(RuntimeError, "unresolved placeholder"):
            apply("fish", self.paths)
        available, missing, _ = inspect_readiness(
            "fish", self.paths, lambda _command: "/bin/true"
        )
        self.assertFalse(available)
        self.assertIn("unresolved placeholder", " ".join(missing))
        self.assertFalse(target.exists())

    def test_declared_superfile_and_cava_assets_are_preferred(self):
        self.paths.current_theme.mkdir(parents=True)
        (self.paths.current_theme / "superfile.toml").write_text("native")
        (self.paths.current_theme / "thpm-superfile.toml").write_text("{{ unresolved }}")
        (self.paths.current_theme / "cava_theme").write_text("native cava")
        (self.paths.current_theme / "thpm-cava.ini").write_text("{{ unresolved }}")
        superfile = apply("superfile", self.paths)
        with patch("thpm.integrations._reload", return_value=[]):
            cava = apply("cava", self.paths)
        self.assertEqual((self.paths.config_home / "superfile/theme/thpm.toml").read_text(), "native")
        self.assertEqual((self.paths.config_home / "cava/themes/thpm").read_text(), "native cava")
        self.assertEqual(superfile.status, "applied")
        self.assertEqual(cava.status, "applied")

    def test_optional_integrations_without_assets_are_already_at_default(self):
        branding = apply("branding", self.paths)
        discord = apply("discord", self.paths)
        cliamp = apply("cliamp", self.paths)
        self.assertEqual(branding.status, "unchanged")
        self.assertEqual(discord.status, "skipped")
        self.assertIn("Discord client", discord.message)
        self.assertEqual(cliamp.status, "unchanged")

    def test_nwg_dock_reports_restart_requirement(self):
        generated = self.paths.current_theme / "thpm-nwg-dock.css"
        generated.parent.mkdir(parents=True)
        generated.write_text("/* dock */")
        result = apply("nwg-dock", self.paths)
        self.assertEqual(result.status, "applied")
        self.assertTrue(any("restart" in warning for warning in result.warnings))

    def test_steam_missing_helper_skips_and_failure_is_reported(self):
        skipped = apply("steam", self.paths)
        self.assertEqual(skipped.status, "skipped")
        script = self.paths.home / ".local/share/steam-adwaita/install.py"
        script.parent.mkdir(parents=True)
        script.touch()
        with patch("thpm.integrations.subprocess.run") as run:
            run.return_value.returncode = 2
            run.return_value.stderr = "installer broke"
            run.return_value.stdout = ""
            with self.assertRaisesRegex(RuntimeError, "installer broke"):
                apply("steam", self.paths)

    def test_reload_failure_preserves_files_changed_before_failure(self):
        generated = self.paths.current_theme / "thpm-spicetify.ini"
        generated.parent.mkdir(parents=True)
        generated.write_text("[base]\n")
        with patch("thpm.integrations.inspect_readiness", return_value=(True, [], [])), patch(
            "thpm.integrations._reload", side_effect=RuntimeError("reload failed")
        ):
            payload = apply_enabled(self.paths, {"spotify": True})
        target = self.paths.config_home / "spicetify/Themes/Omarchy/color.ini"
        self.assertEqual(payload["results"][0]["status"], "failed")
        self.assertIn(str(target), payload["results"][0]["changed"])
        self.assertEqual(target.read_text(), "[base]\n")

    def test_apply_enabled_isolates_failures_and_exposes_statuses(self):
        generated = self.paths.current_theme / "thpm-fish.fish"
        generated.parent.mkdir(parents=True)
        generated.write_text("set -g fish_color_normal normal\n")
        with patch("thpm.integrations.inspect_readiness", return_value=(True, [], [])), patch(
            "thpm.integrations.apply", side_effect=[apply("fish", self.paths), RuntimeError("broken")]
        ):
            payload = apply_enabled(self.paths, {"fish": True, "fzf": True})
        self.assertEqual([result["status"] for result in payload["results"]], ["applied", "failed"])
        self.assertEqual(payload["counts"]["failed"], 1)
        self.assertEqual(payload["errors"][0]["plugin"], "fzf")

    def test_hermes_template_matches_desktop_theme_contract(self):
        template = (Path(__file__).parents[1] / "assets/templates/thpm-hermes.json.tpl").read_text()
        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            self.assertIn(key, CANONICAL_COLORS)
            return CANONICAL_COLORS[key]
        rendered = re.sub(r"\{\{ ([a-z_]+) \}\}", replace, template)
        document = json.loads(rendered)
        self.assertEqual(document["schemaVersion"], 1)
        self.assertEqual(document["source"], "thpm")
        for key in ("colors", "darkColors", "terminal", "darkTerminal"):
            self.assertIn(key, document["theme"])
        self.assertIn("composerRing", document["theme"]["colors"])
        self.assertIn("brightWhite", document["theme"]["darkTerminal"])


class UpdateTests(Sandbox):
    def setUp(self):
        super().setUp()
        self.paths.install_metadata.parent.mkdir(parents=True)
        self.paths.install_metadata.write_text('origin = "source"\nrepository = "oldjobobo/thpm"\n')
        real_which = updater.shutil.which
        which_patcher = patch(
            "thpm.update.shutil.which",
            side_effect=lambda command: None if command == "thpm" else real_which(command),
        )
        which_patcher.start()
        self.addCleanup(which_patcher.stop)

    def release(self, version="1.0.1"):
        archive = f"thpm-{version}.tar.gz"
        return {"tag_name": f"v{version}", "html_url": "https://example/release", "assets": [
            {"name": archive, "browser_download_url": "https://example/archive"},
            {"name": archive + ".sha256", "browser_download_url": "https://example/checksum"},
        ]}

    def test_source_check_reports_new_stable_release_and_caches_it(self):
        with patch("thpm.update._read_json", return_value=self.release()) as read:
            first = updater.check(self.paths, force=True)
            second = updater.check(self.paths)
        self.assertEqual(first["status"], "available")
        self.assertEqual(first["availableVersion"], "1.0.1")
        self.assertTrue(second["cached"])
        self.assertEqual(read.call_count, 1)

    def test_release_without_checksum_is_rejected(self):
        release = self.release(); release["assets"] = release["assets"][:1]
        with patch("thpm.update._read_json", return_value=release):
            result = updater.check(self.paths, force=True)
        self.assertEqual(result["status"], "error")
        self.assertIn("SHA-256", result["error"])

    def test_older_release_is_not_offered(self):
        with patch("thpm.update._read_json", return_value=self.release("0.9.0")):
            result = updater.check(self.paths, force=True)
        self.assertEqual(result["status"], "current")

    def test_release_candidate_versions_sort_before_the_final_release(self):
        self.assertLess(updater._version("v1.0.0rc1"), updater._version("1.0.0rc2"))
        self.assertLess(updater._version("1.0.0rc2"), updater._version("1.0.0"))

    def test_current_release_candidate_is_not_offered_again(self):
        with patch("thpm.update._read_json", return_value=self.release("1.0.0rc1")):
            result = updater.check(self.paths, force=True)
        self.assertEqual(result["status"], "current")

    def test_archive_special_files_are_rejected(self):
        archive = self.paths.home / "special.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            info = tarfile.TarInfo("thpm/fifo")
            info.type = tarfile.FIFOTYPE
            bundle.addfile(info)
        with self.assertRaisesRegex(ValueError, "unsupported entry type"):
            updater._safe_extract(archive, self.paths.home / "extract")

    def test_rc_channel_selects_newest_prerelease(self):
        self.paths.install_metadata.parent.mkdir(parents=True, exist_ok=True)
        self.paths.install_metadata.write_text('origin = "source"\nchannel = "rc"\n')
        releases = [self.release("1.0.0rc1"), self.release("1.0.0rc7"), {**self.release("2.0.0"), "draft": True}]
        with patch("thpm.update._read_json", return_value=releases):
            result = updater.check(self.paths, force=True)
        self.assertEqual(result["availableVersion"], "1.0.0rc7")
        self.assertEqual(result["channel"], "rc")

    def test_archive_path_traversal_is_rejected(self):
        archive = self.paths.home / "bad.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            info = tarfile.TarInfo("../escape")
            payload = b"bad"
            info.size = len(payload)
            bundle.addfile(info, io.BytesIO(payload))
        with self.assertRaisesRegex(ValueError, "unsafe path"):
            updater._safe_extract(archive, self.paths.home / "extract")

    def test_install_script_validates_before_migration_or_launcher_replacement(self):
        script = (Path(__file__).parents[1] / "install.sh").read_text()
        non_mutating_check = '"$staged/bin/thpm" install --check "$@"'
        activation = 'mv "$staged" "$runtime_dir"'
        mutating_install = '"$runtime_dir/bin/thpm" install "$@"'
        launcher_replace = 'ln -sfn "$runtime_dir/bin/thpm" "$user_bin/thpm"'
        self.assertNotIn("python3 -m thpm migrate", script)
        self.assertLess(script.index(non_mutating_check), script.index(activation))
        self.assertLess(script.index(activation), script.index(mutating_install))
        self.assertLess(script.index(mutating_install), script.index(launcher_replace))
        self.assertIn('origin = "source"', script)
        self.assertIn("textual>=8.2.8,<9", script)
        self.assertIn('mv "$previous" "$runtime_dir"', script)
        committed_refresh = '"$runtime_dir/bin/thpm" reconcile --refresh'
        disable_rollback = "trap - ERR INT TERM"
        self.assertGreater(script.index(committed_refresh), script.index(disable_rollback))
        self.assertEqual((Path(__file__).parents[1] / "VERSION").read_text().strip(), "1.0.0rc14")

    def test_staged_runtime_installs_and_smoke_tests_textual(self):
        source = __import__("inspect").getsource(updater._stage_runtime)
        update_source = __import__("inspect").getsource(updater.apply)
        self.assertIn('"textual>=8.2.8,<9"', source)
        self.assertIn("from thpm.tui import ThpmTui", source)
        self.assertIn('"--defer-upgrade-refresh"', update_source)
        self.assertIn('"refreshRequired"', update_source)
        self.assertIn('"thpm reconcile --refresh"', update_source)

    def test_checksum_mismatch_stops_before_runtime_staging(self):
        result = {"status": "available", "origin": "source", "currentVersion": "1.0.0rc1", "availableVersion": "1.0.1",
            "archiveUrl": "https://example/archive", "checksumUrl": "https://example/checksum"}
        def download(url, destination):
            destination.write_text("0" * 64 if "checksum" in url else "archive")
        with patch("thpm.update.check", return_value=result), patch("thpm.update._download", side_effect=download), \
             patch("thpm.update._stage_runtime") as stage:
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                updater.apply(self.paths)
        stage.assert_not_called()

    def test_source_update_keeps_symlinked_venv_runtime_path(self):
        runtime = self.paths.home / "runtime"
        (runtime / "bin").mkdir(parents=True)
        python = runtime / "bin/python"
        python.symlink_to(Path(updater.sys.executable))
        with patch("thpm.update.sys.executable", str(python)):
            self.assertEqual(updater._source_runtime(), runtime)

    def test_failed_activation_restores_previous_runtime(self):
        fake_root = self.paths.home / "runtime"
        (fake_root / "bin").mkdir(parents=True)
        fake_python = fake_root / "bin/python"
        fake_python.write_text("runtime")
        source = self.paths.home / "source-tree"
        source.mkdir()
        (source / "VERSION").write_text("1.0.1")
        self.paths.hook_file.parent.mkdir(parents=True)
        self.paths.hook_file.write_text("original hook")
        result = {"status": "available", "origin": "source", "currentVersion": "1.0.0rc1", "availableVersion": "1.0.1",
            "archiveUrl": "archive", "checksumUrl": "checksum"}
        archive_bytes = b"archive"
        digest = __import__("hashlib").sha256(archive_bytes).hexdigest()
        def download(url, destination): destination.write_bytes((digest + "  thpm.tar.gz\n").encode() if url == "checksum" else archive_bytes)
        def stage(_source, destination):
            (destination / "bin").mkdir(parents=True)
            (destination / "bin/thpm").write_text("new")
        def fail_install(*_args, **_kwargs):
            self.paths.hook_file.write_text("partial update")
            raise RuntimeError("install failed")
        with patch("thpm.update.check", return_value=result), patch("thpm.update._download", side_effect=download), \
             patch("thpm.update._safe_extract", return_value=source), patch("thpm.update._stage_runtime", side_effect=stage), \
             patch("thpm.update.sys.executable", str(fake_python)), patch("thpm.update.subprocess.run", side_effect=fail_install):
            with self.assertRaisesRegex(RuntimeError, "install failed"):
                updater.apply(self.paths)
        self.assertEqual(fake_python.read_text(), "runtime")
        self.assertEqual(self.paths.hook_file.read_text(), "original hook")
        self.assertFalse(fake_root.with_name("runtime.previous").exists())

    def test_successful_source_update_refreshes_after_activation(self):
        runtime = self.paths.home / "runtime"
        (runtime / "bin").mkdir(parents=True)
        fake_python = runtime / "bin/python"
        fake_python.write_text("old runtime")
        source = self.paths.home / "source-tree"
        source.mkdir()
        (source / "VERSION").write_text("1.0.1")
        update = {
            "status": "available", "origin": "source", "currentVersion": "1.0.0rc4",
            "availableVersion": "1.0.1", "archiveUrl": "archive", "checksumUrl": "checksum",
        }
        archive_bytes = b"archive"
        digest = __import__("hashlib").sha256(archive_bytes).hexdigest()

        def download(url, destination):
            destination.write_bytes(
                (digest + "  thpm.tar.gz\n").encode() if url == "checksum" else archive_bytes
            )

        def stage(_source, destination):
            (destination / "bin").mkdir(parents=True)
            (destination / "bin/thpm").write_text("new runtime")

        completed = subprocess.CompletedProcess([], 0, "", "")
        with patch("thpm.update.check", return_value=update), patch(
            "thpm.update._download", side_effect=download
        ), patch("thpm.update._safe_extract", return_value=source), patch(
            "thpm.update._stage_runtime", side_effect=stage
        ), patch("thpm.update.sys.executable", str(fake_python)), patch(
            "thpm.update.subprocess.run", return_value=completed
        ) as run:
            result = updater.apply(self.paths)
        self.assertEqual(result["status"], "updated")
        self.assertFalse(result["refreshRequired"])
        self.assertIsNone(result["refreshCommand"])
        self.assertEqual(
            run.call_args_list[0].args[0],
            [str(runtime / "bin/thpm"), "reconcile", "--defer-upgrade-refresh"],
        )
        self.assertEqual(
            run.call_args_list[1].args[0],
            [str(runtime / "bin/thpm"), "ui", "install"],
        )
        self.assertEqual(
            run.call_args_list[2].args[0],
            [str(runtime / "bin/thpm"), "reconcile", "--refresh"],
        )
        self.assertFalse(runtime.with_name("runtime.previous").exists())

    def test_aur_check_does_not_offer_an_older_repository_version(self):
        install = {"origin": "thpm", "package": "thpm", "repository": "oldjobobo/thpm", "installedVersion": "1.1.0-1"}
        response = {"results": [{"Version": "1.0.0-1"}]}
        with patch("thpm.update.origin", return_value=install), patch("thpm.update._read_json", return_value=response), \
             patch("thpm.update._arch_version_is_newer", return_value=False) as newer:
            result = updater.check(self.paths, force=True)
        self.assertEqual(result["status"], "current")
        newer.assert_called_once_with("1.0.0-1", "1.1.0-1")

    def test_update_rollback_removes_new_managed_templates(self):
        self.paths.themed_dir.mkdir(parents=True)
        existing = self.paths.themed_dir / "thpm-existing.tpl"
        foreign = self.paths.themed_dir / "foreign.tpl"
        existing.write_text("old")
        foreign.write_text("keep")
        backup_root = self.paths.home / "backup"
        backups = updater._backup_integrations(self.paths, backup_root)
        existing.write_text("new")
        (self.paths.themed_dir / "thpm-added.tpl").write_text("added")
        updater._restore_integrations(backups)
        self.assertEqual(existing.read_text(), "old")
        self.assertEqual(foreign.read_text(), "keep")
        self.assertFalse((self.paths.themed_dir / "thpm-added.tpl").exists())

    def test_update_refresh_failure_is_reported_as_committed_partial_failure(self):
        result = {
            "status": "updated",
            "origin": "source",
            "refreshRequired": True,
            "refreshCommand": "thpm reconcile --refresh",
            "refreshError": "refresh failed",
        }
        with patch("thpm.service.apply_update", return_value=result):
            payload = Service(self.paths).update_apply()
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["committed"])
        self.assertIn("package updated", payload["summary"])
        self.assertIn("refresh failed", payload["errors"][0]["message"])

    def test_json_style_aur_apply_requires_a_terminal_without_launching_processes(self):
        result = {
            "status": "available",
            "origin": "thpm",
            "currentVersion": "1.0.0rc1",
            "availableVersion": "1.0.1-1",
        }
        with patch("thpm.update.check", return_value=result), patch(
            "thpm.update.subprocess.run"
        ) as run, patch("thpm.update.subprocess.Popen") as launch:
            applied = updater.apply(self.paths, interactive=False)
        self.assertEqual(applied["status"], "requires-interactive")
        self.assertEqual(applied["command"], "thpm update")
        run.assert_not_called()
        launch.assert_not_called()

    def test_aur_apply_runs_noninteractive_upgrade_in_current_terminal(self):
        result = {"status": "available", "origin": "thpm", "currentVersion": "1.0.0rc1", "availableVersion": "1.0.1-1"}

        class TerminalProgress:
            def __init__(self):
                self.events = []
                self.totals = []
                self.suspended = False

            def __call__(self, message, detail):
                self.events.append((message, detail))

            def set_total(self, total):
                self.totals.append(total)

            @contextmanager
            def suspend(self):
                self.suspended = True
                try:
                    yield
                finally:
                    self.suspended = False

        progress = TerminalProgress()
        commands = {"yay": "/usr/bin/yay", "thpm": "/usr/bin/thpm"}

        def run_command(*_args, **_kwargs):
            self.assertTrue(progress.suspended)

        with patch("thpm.update.check", return_value=result), patch(
            "thpm.update.shutil.which", side_effect=commands.get
        ), patch("thpm.update.sys.stdin.isatty", return_value=True), patch(
            "thpm.update.subprocess.run", side_effect=run_command
        ) as run, patch("thpm.update.subprocess.Popen") as launch:
            applied = updater.apply(self.paths, progress=progress)
        self.assertEqual(applied["status"], "updated")
        self.assertEqual(
            run.call_args_list,
            [
                call(
                    ["/usr/bin/yay", "-S", "--noconfirm", "--needed", "thpm"],
                    check=True,
                    timeout=updater.PACKAGE_UPDATE_TIMEOUT_SECONDS,
                ),
                call(
                    ["/usr/bin/thpm", "reconcile", "--refresh"],
                    check=True,
                    timeout=updater.RECONCILE_TIMEOUT_SECONDS,
                ),
            ],
        )
        launch.assert_not_called()
        self.assertFalse(applied["refreshRequired"])
        self.assertEqual(progress.events, [("Upgrading AUR package", "thpm")])
        self.assertEqual(progress.totals, [2])

    def test_aur_reconcile_failure_reports_committed_package_and_handoff(self):
        result = {
            "status": "available",
            "origin": "thpm",
            "currentVersion": "1.0.0rc1",
            "availableVersion": "1.0.1-1",
        }
        commands = {"yay": "/usr/bin/yay", "thpm": "/usr/bin/thpm"}
        with patch("thpm.update.check", return_value=result), patch(
            "thpm.update.shutil.which", side_effect=commands.get
        ), patch("thpm.update.sys.stdin.isatty", return_value=True), patch(
            "thpm.update.subprocess.run",
            side_effect=[None, subprocess.CalledProcessError(1, "reconcile")],
        ):
            applied = updater.apply(self.paths)
        self.assertEqual(applied["status"], "updated")
        self.assertTrue(applied["packageCommitted"])
        self.assertTrue(applied["refreshRequired"])
        self.assertEqual(applied["refreshCommand"], "thpm reconcile --refresh")
        self.assertIn("reconcile", applied["refreshError"])

    def test_aur_apply_uses_terminal_fallback_without_a_tty(self):
        result = {"status": "available", "origin": "thpm", "currentVersion": "1.0.0rc1", "availableVersion": "1.0.1-1"}
        commands = {
            "yay": "/usr/bin/yay",
            "omarchy-launch-floating-terminal-with-presentation": "/usr/bin/omarchy-launch-floating-terminal-with-presentation",
        }
        with patch("thpm.update.check", return_value=result), patch(
            "thpm.update.shutil.which", side_effect=commands.get
        ), patch("thpm.update.sys.stdin.isatty", return_value=False), patch(
            "thpm.update.subprocess.Popen"
        ) as launch:
            applied = updater.apply(self.paths)
        self.assertEqual(applied["status"], "started")
        launch.assert_called_once_with(
            [
                "/usr/bin/omarchy-launch-floating-terminal-with-presentation",
                "yay -S --noconfirm --needed thpm && thpm reconcile --refresh",
            ],
            start_new_session=True,
        )


if __name__ == "__main__":
    unittest.main()
