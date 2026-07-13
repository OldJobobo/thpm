from __future__ import annotations

import json
import os
import io
import json
import re
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from thpm import palette, ui
from thpm import update as updater
from thpm.integrations import apply
from thpm.migrate import archive, artifacts, inspect, needs_compat
from thpm.paths import Paths
from thpm.registry import PLUGINS
from thpm.service import Service
from thpm.state import load, save
from thpm.templates import reconcile


COLORS = {
    "mode": "dark", "bg": "#111111", "dark_bg": "#101010", "darker_bg": "#090909",
    "lighter_bg": "#222222", "selection": "#333333", "muted": "#777777", "dark_fg": "#999999",
    "fg": "#dddddd", "light_fg": "#eeeeee", "bright_fg": "#ffffff", "red": "#cc4444",
    "yellow": "#ccaa44", "orange": "#dd8844", "green": "#55aa66", "cyan": "#44aacc",
    "blue": "#4477cc", "magenta": "#aa55cc", "brown": "#996644", "bright_red": "#ff6666",
    "bright_yellow": "#ffdd66", "bright_green": "#77dd88", "bright_cyan": "#66ddee",
    "bright_blue": "#6699ff", "bright_magenta": "#dd77ff",
}


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
    def test_accepts_quattro_semantic_palette(self):
        self.write_palette()
        self.assertEqual(palette.load(self.paths.current_theme / "colors.toml")["mode"], "dark")

    def test_rejects_pre_quattro_palette(self):
        self.paths.current_theme.mkdir(parents=True)
        (self.paths.current_theme / "colors.toml").write_text('background = "#000000"\n')
        with self.assertRaisesRegex(ValueError, "missing semantic colors"):
            palette.load(self.paths.current_theme / "colors.toml")


class StateTests(Sandbox):
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

    def test_every_registered_template_is_packaged(self):
        templates = Path(__file__).parents[1] / "assets/templates"
        missing = [name for plugin in PLUGINS for name in plugin.templates if not (templates / name).is_file()]
        self.assertEqual(missing, [])


class MigrationTests(Sandbox):
    def test_migration_reads_names_not_legacy_contents(self):
        self.paths.hook_dir.mkdir(parents=True)
        legacy = self.paths.hook_dir / "40-firefox.sh"
        legacy.write_text("exit 99\n")
        updates, files = inspect(self.paths)
        self.assertTrue(updates["firefox"])
        self.assertEqual(files, [legacy])

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
            self.assertIn("style.theme-hooks", installed)
            ui.remove(self.paths)
        self.assertIn('"foreign"', self.paths.menu_extension.read_text())
        self.assertNotIn("style.theme-hooks", self.paths.menu_extension.read_text())

    def test_qml_manifest_contract(self):
        manifest = json.loads((Path(__file__).parents[1] / "assets/qml/manifest.json").read_text())
        self.assertEqual(manifest["id"], "io.github.oldjobobo.thpm")
        self.assertIn("panel", manifest["kinds"])
        self.assertTrue(manifest["keepLoaded"])

    def test_qml_uses_layer_shell_surface_not_desktop_window(self):
        qml = (Path(__file__).parents[1] / "assets/qml/Panel.qml").read_text()
        self.assertIn("PanelWindow {", qml)
        self.assertIn("WlrLayershell.layer: WlrLayer.Overlay", qml)
        self.assertNotIn("FloatingWindow {", qml)

    def test_qml_design_stays_single_panel_and_uses_omarchy_controls(self):
        qml = (Path(__file__).parents[1] / "assets/qml/Panel.qml").read_text()
        self.assertEqual(qml.count("PanelWindow {"), 1)
        self.assertIn("import qs.Ui", qml)
        self.assertIn("BorderSurface {", qml)
        self.assertIn("TextField {", qml)
        self.assertIn("delegate: Toggle {", qml)
        self.assertNotIn("Switch {", qml)
        self.assertNotIn('text: "Refresh"', qml)

    def test_qml_update_flow_requires_confirmation(self):
        qml = (Path(__file__).parents[1] / "assets/qml/Panel.qml").read_text()
        self.assertIn('["thpm", "--json", "update", "status"]', qml)
        self.assertIn('id: updateConfirm', qml)
        self.assertIn('command: ["thpm", "--json", "update", "apply"]', qml)
        self.assertIn('text: "Restart shell"', qml)


class ServiceTests(Sandbox):
    def test_json_envelope_and_native_ownership(self):
        payload = Service(self.paths).state()
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertTrue(any(p["ownership"] == "native" for p in payload["plugins"]))

    def test_uninstall_removes_only_thpm_integration_files(self):
        foreign = self.paths.themed_dir / "foreign.tpl"
        owned = self.paths.themed_dir / "thpm-fish.fish.tpl"
        foreign.parent.mkdir(parents=True)
        foreign.write_text("keep")
        owned.write_text("remove")
        self.paths.hook_file.parent.mkdir(parents=True)
        self.paths.hook_file.write_text("remove")
        with patch("thpm.service.ui.remove", return_value={"installed": False}):
            Service(self.paths).uninstall()
        self.assertTrue(foreign.exists())
        self.assertFalse(owned.exists())
        self.assertFalse(self.paths.hook_file.exists())

    def test_discord_plugins_remain_mutually_exclusive(self):
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            Service(self.paths).set_enabled("discord", True)
        state = load(self.paths)
        self.assertTrue(state["discord"])
        self.assertFalse(state["discord-system24"])

    def test_hermes_desktop_config_makes_plugin_available(self):
        (self.paths.config_home / "Hermes").mkdir(parents=True)
        plugin = next(item for item in Service(self.paths).state()["plugins"] if item["id"] == "hermes")
        self.assertTrue(plugin["available"])
        self.assertEqual(plugin["missing"], [])


class IntegrationTests(Sandbox):
    def test_vencord_asset_copy_does_not_require_palette(self):
        self.paths.current_theme.mkdir(parents=True)
        source = self.paths.current_theme / "vencord.theme.css"
        source.write_text("/* current theme */\n")
        target_dir = self.paths.config_home / "vesktop/themes"
        target_dir.mkdir(parents=True)
        changed = apply("discord", self.paths)
        target = target_dir / "vencord.theme.css"
        self.assertEqual(target.read_bytes(), source.read_bytes())
        self.assertIn(str(target), changed)
        self.assertFalse((target_dir / "omarchy.theme.css").exists())

    def test_hermes_template_matches_desktop_theme_contract(self):
        template = (Path(__file__).parents[1] / "assets/templates/thpm-hermes.json.tpl").read_text()
        rendered = re.sub(r"\{\{ ([a-z_]+) \}\}", lambda match: COLORS.get(match.group(1), "dark"), template)
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

    def test_archive_path_traversal_is_rejected(self):
        archive = self.paths.home / "bad.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            info = tarfile.TarInfo("../escape")
            payload = b"bad"
            info.size = len(payload)
            bundle.addfile(info, io.BytesIO(payload))
        with self.assertRaisesRegex(ValueError, "unsafe path"):
            updater._safe_extract(archive, self.paths.home / "extract")

    def test_install_script_records_source_origin_without_changing_version(self):
        script = (Path(__file__).parents[1] / "install.sh").read_text()
        self.assertIn('origin = "source"', script)
        self.assertEqual((Path(__file__).parents[1] / "VERSION").read_text().strip(), "1.0.0")

    def test_checksum_mismatch_stops_before_runtime_staging(self):
        result = {"status": "available", "origin": "source", "currentVersion": "1.0.0", "availableVersion": "1.0.1",
            "archiveUrl": "https://example/archive", "checksumUrl": "https://example/checksum"}
        def download(url, destination):
            destination.write_text("0" * 64 if "checksum" in url else "archive")
        with patch("thpm.update.check", return_value=result), patch("thpm.update._download", side_effect=download), \
             patch("thpm.update._stage_runtime") as stage:
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                updater.apply(self.paths)
        stage.assert_not_called()

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
        result = {"status": "available", "origin": "source", "currentVersion": "1.0.0", "availableVersion": "1.0.1",
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

    def test_aur_apply_hands_control_to_floating_terminal(self):
        result = {"status": "available", "origin": "thpm", "currentVersion": "1.0.0", "availableVersion": "1.0.1-1"}
        with patch("thpm.update.check", return_value=result), patch("thpm.update.shutil.which", return_value="/usr/bin/omarchy-launch-floating-terminal-with-presentation"), \
             patch("thpm.update.subprocess.Popen") as launch:
            applied = updater.apply(self.paths)
        self.assertEqual(applied["status"], "started")
        launch.assert_called_once_with(["/usr/bin/omarchy-launch-floating-terminal-with-presentation", "yay -S thpm"], start_new_session=True)


if __name__ == "__main__":
    unittest.main()
