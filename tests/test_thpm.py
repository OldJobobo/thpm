from __future__ import annotations

import ast
import asyncio
import fcntl
import hashlib
import io
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
import zipfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, call, patch

from rich.console import Console
from textual.widgets import Button, Link

from thpm import gnome_accent
from thpm import integrations as integration_adapters
from thpm import palette, ui
from thpm import update as updater
from thpm.audit import (
    append_entries,
    entries_from_payload,
    recent_entries,
    record_payload,
    sanitize,
)
from thpm.cava import (
    CavaError,
)
from thpm.cava import (
    configure_selector as configure_cava_selector,
)
from thpm.cava import (
    diagnose as diagnose_cava,
)
from thpm.cava import (
    discover_processes as discover_cava_processes,
)
from thpm.cava import (
    parse_selector as parse_cava_selector,
)
from thpm.cava import (
    parse_version as parse_cava_version,
)
from thpm.cava import (
    reload_matching_processes as reload_cava_processes,
)
from thpm.cava import (
    restore_selector as restore_cava_selector,
)
from thpm.cava import (
    restore_selector_text as restore_cava_selector_text,
)
from thpm.cava import (
    set_selector as set_cava_selector,
)
from thpm.cli import _confirm, _write_update_handoff_result, main
from thpm.compat import gtk_file_doctor_warnings, gtk_session_doctor_warnings
from thpm.config import ConfigError, Preferences
from thpm.config import load as load_config
from thpm.config import save as save_config
from thpm.integrations import (
    ApplyFailure,
    _browser_import,
    _reload,
    apply,
    apply_enabled,
    cleanup_managed_outputs,
    cleanup_optional_assets,
    inspect_readiness,
)
from thpm.migrate import archive, artifacts, inspect, needs_compat
from thpm.models import ApplyResult
from thpm.omarchy import capabilities, shell_running
from thpm.omarchy import run as run_omarchy
from thpm.paths import Paths
from thpm.presentation import Activity, operation_name, render, reporter
from thpm.registry import PLUGINS
from thpm.report import MAX_REPORT_BYTES, build_report, write_report
from thpm.service import Service, _zellij_process_running
from thpm.state import (
    StateError,
    cava_opt_in_completed,
    complete_cava_opt_in,
    load,
    save,
)
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
        self.host_omarchy_guard = patch(
            "thpm.service.run",
            side_effect=AssertionError(
                "sandbox test attempted to run a host Omarchy command; "
                "pass refresh=False or stub thpm.service.run explicitly"
            ),
        )
        self.host_omarchy_guard.start()
        self.host_ui_omarchy_guard = patch(
            "thpm.ui.run",
            side_effect=AssertionError(
                "sandbox test attempted to run a host Omarchy UI command; "
                "stub thpm.ui.run explicitly"
            ),
        )
        self.host_ui_omarchy_guard.start()

    def tearDown(self):
        self.host_ui_omarchy_guard.stop()
        self.host_omarchy_guard.stop()
        self.temp.cleanup()

    def write_palette(self):
        self.paths.current_theme.mkdir(parents=True)
        lines = [f'{key} = "{value}"' for key, value in COLORS.items()]
        (self.paths.current_theme / "colors.toml").write_text("\n".join(lines) + "\n")


class PathsTests(Sandbox):
    def test_empty_xdg_cache_home_uses_absolute_home_fallback(self):
        with patch.dict(
            os.environ,
            {"HOME": str(self.paths.home), "XDG_CACHE_HOME": ""},
            clear=False,
        ):
            discovered = Paths.discover()

        self.assertEqual(discovered.cache_root, self.paths.home / ".cache")
        self.assertTrue(discovered.cache_root.is_absolute())


class PaletteTests(Sandbox):
    def test_accepts_quattro_semantic_palette_without_host_resolver(self):
        self.write_palette()
        with patch("thpm.palette.shutil.which", return_value=None):
            result = palette.load(self.paths.current_theme / "colors.toml")
        self.assertEqual(result["mode"], "dark")

    def test_optional_native_palette_colors_are_retained_for_adapters(self):
        optional: dict[str, object] = {
            "accent": "#123456",
            "cursor": "#234567",
            "selection_background": "#345678",
            "selection_foreground": "#456789",
        }
        self.assertEqual(
            {key: palette._validate({**COLORS, **optional})[key] for key in optional},
            optional,
        )

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

    def test_rejects_unsupported_or_invalid_state_versions(self):
        self.paths.thpm_state_dir.mkdir(parents=True)
        for version in ("3", '"one"', "true"):
            with self.subTest(version=version):
                self.paths.state_file.write_text(
                    f"version = {version}\n\n[plugins]\nfish = true\n"
                )
                with self.assertRaisesRegex(StateError, "unsupported THPM state version"):
                    load(self.paths)

    def test_accepts_unversioned_legacy_state(self):
        self.paths.thpm_state_dir.mkdir(parents=True)
        self.paths.state_file.write_text("[plugins]\nfish = false\n")
        self.assertFalse(load(self.paths)["fish"])

    def test_schema_one_enablement_is_grandfathered_across_policy_change(self):
        self.paths.thpm_state_dir.mkdir(parents=True)
        self.paths.state_file.write_text(
            "version = 1\n\n[plugins]\nfish = true\ngtk-css-compat = true\n"
            "spotify = true\nbranding = true\nfirefox = true\nzed-extra = true\n"
        )
        enabled = load(self.paths)
        self.assertTrue(enabled["fish"])
        self.assertTrue(enabled["gtk-css-compat"])
        self.assertTrue(enabled["spotify"])
        self.assertTrue(enabled["branding"])
        self.assertTrue(enabled["firefox"])
        self.assertTrue(enabled["zed-extra"])

    def test_rejects_conflicting_persisted_discord_state(self):
        self.paths.thpm_state_dir.mkdir(parents=True)
        self.paths.state_file.write_text(
            "version = 1\n\n[plugins]\ndiscord = true\ndiscord-system24 = true\n"
        )
        with self.assertRaisesRegex(StateError, "conflicting THPM integrations"):
            load(self.paths)

    def test_save_rejects_conflicting_discord_state(self):
        state = load(self.paths)
        state["discord"] = True
        state["discord-system24"] = True
        with self.assertRaisesRegex(StateError, "conflicting THPM integrations"):
            save(self.paths, state)
        self.assertFalse(self.paths.state_file.exists())

    def test_state_round_trip_preserves_known_values(self):
        state = load(self.paths)
        state["firefox"] = True
        save(self.paths, state)
        self.assertTrue(load(self.paths)["firefox"])

    def test_legacy_saved_cava_true_requires_confirmed_opt_in_marker(self):
        state = load(self.paths)
        state["cava"] = True
        save(self.paths, state)

        self.assertFalse(load(self.paths)["cava"])
        self.assertFalse(cava_opt_in_completed(self.paths))
        complete_cava_opt_in(self.paths)
        self.assertTrue(load(self.paths)["cava"])
        self.assertEqual(self.paths.cava_opt_in_marker.stat().st_mode & 0o777, 0o600)

    def test_invalid_or_symlinked_cava_opt_in_marker_does_not_grant_consent(self):
        state = load(self.paths)
        state["cava"] = True
        save(self.paths, state)
        marker = self.paths.cava_opt_in_marker
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("invalid\n")
        self.assertFalse(load(self.paths)["cava"])
        marker.unlink()
        target = self.paths.home / "not-consent"
        target.write_text("version = 1\n")
        marker.symlink_to(target)
        self.assertFalse(load(self.paths)["cava"])

    def test_legacy_cava_true_is_disabled_for_hooks_and_reconcile(self):
        state = load(self.paths)
        state["cava"] = True
        save(self.paths, state)
        captured = {}

        def inspect_enabled(_paths, enabled, **_kwargs):
            captured.update(enabled)
            return {
                "results": [],
                "counts": {"applied": 0, "unchanged": 0, "skipped": 0, "failed": 0},
                "changed": [],
                "actions": [],
                "restartRequired": [],
                "errors": [],
                "warnings": [],
            }

        with patch("thpm.service.apply_enabled", side_effect=inspect_enabled):
            Service(self.paths).hook_run("theme-set")
        self.assertFalse(captured["cava"])

        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch(
            "thpm.service._refresh_templates",
            return_value=({"refreshed": False, "pending": False}, []),
        ):
            Service(self.paths).reconcile()
        self.assertIn("cava = false", self.paths.state_file.read_text())
        self.assertFalse(self.paths.cava_opt_in_marker.exists())

    def test_install_does_not_migrate_legacy_cava_into_unconfirmed_enablement(self):
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch(
            "thpm.service.capabilities"
        ) as caps, patch(
            "thpm.service.inspect_legacy", return_value=({"cava": True}, [])
        ), patch(
            "thpm.service.needs_compat", return_value=False
        ), patch(
            "thpm.service.archive_legacy", return_value=None
        ), patch(
            "thpm.service._refresh_templates",
            return_value=({"refreshed": False, "pending": False}, []),
        ):
            caps.return_value.available = True
            caps.return_value.missing = ()
            result = Service(self.paths).install(with_ui=False)
        self.assertTrue(result["ok"])
        self.assertFalse(load(self.paths)["cava"])
        self.assertIn("cava = false", self.paths.state_file.read_text())
        self.assertFalse(self.paths.cava_opt_in_marker.exists())

    def test_install_prefers_enabled_legacy_system24(self):
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch(
            "thpm.service.capabilities"
        ) as caps, patch(
            "thpm.service.inspect_legacy",
            return_value=({"discord-system24": True}, []),
        ), patch(
            "thpm.service.needs_compat", return_value=False
        ), patch(
            "thpm.service.archive_legacy", return_value=None
        ), patch(
            "thpm.service._refresh_templates",
            return_value=({"refreshed": False, "pending": False}, []),
        ):
            caps.return_value.available = True
            caps.return_value.missing = ()
            result = Service(self.paths).install(with_ui=False)

        self.assertTrue(result["ok"])
        enabled = load(self.paths)
        self.assertFalse(enabled["discord"])
        self.assertTrue(enabled["discord-system24"])

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

    def test_experimental_plugins_are_opt_in_by_default(self):
        enabled = load(self.paths)
        self.assertTrue(all(not enabled[plugin.id] for plugin in PLUGINS))
        self.assertTrue(
            all(
                plugin.support_status == "experimental"
                for plugin in PLUGINS
                if plugin.id not in {"fzf", "zellij"}
            )
        )

    def test_fzf_is_supported_after_complete_live_certification_and_signoff(self):
        fzf = next(plugin for plugin in PLUGINS if plugin.id == "fzf")
        support = (Path(__file__).parents[1] / "docs/integration-support.md").read_text()

        self.assertEqual(fzf.support_status, "supported")
        self.assertRegex(
            support,
            r"(?m)^\| `fzf` \| Complete \| Supported \| disabled \|",
        )
        record = Path(__file__).parents[1] / "docs/certifications/fzf-2026-08-28.md"
        evidence = record.parent / "evidence/fzf-2026-08-28"
        self.assertTrue(record.is_file())
        self.assertIn('omarchy-theme-set "Dune"', record.read_text())
        self.assertIn('omarchy-theme-set "Last Call"', record.read_text())
        for name in (
            "commands.txt",
            "thpm-fzf-certification-report.json",
            "thpm-fzf-dune-marked.png",
            "thpm-fzf-last-call-marked.png",
            "thpm-fzf-post-disable-fresh.png",
            "thpm-fzf-post-uninstall-fresh.png",
            "post-disable-env.txt",
            "post-uninstall-env.txt",
        ):
            self.assertTrue((evidence / name).is_file(), name)
        report = json.loads((evidence / "thpm-fzf-certification-report.json").read_text())
        self.assertEqual(report["scope"], "fzf")
        self.assertTrue(report["privacy"]["redacted"])
        expected_hashes = {
            "thpm-fzf-certification-report.json": "bd7e81b11fc9b06319abaeaa0fed08c1e0640375ed67d1659a327c1690ed6612",
            "thpm-fzf-dune-marked.png": "01ad616802cd912a866805abe6366e388e61499f67ca0ce3af5d2d0662b2072c",
            "thpm-fzf-last-call-marked.png": "bca5e6567cf1ef7fd7c57f0f0929fe930d319d7bce5eef8993eac803cdca4aae",
            "thpm-fzf-post-disable-fresh.png": "636b2a98c366f0249b32d3123378215ba17c816848badfee25f85e765a7341e3",
            "thpm-fzf-post-uninstall-fresh.png": "a8402e8f049209fbbc9f64d039c3c44459a88452042c5a3e00ca7acbe2a9d4d6",
            "post-disable-env.txt": "7d59b8c9e994c3c4ef516f6f35941b846e714cd40159f7b1e4bccc63ac0c18a1",
            "post-uninstall-env.txt": "7d59b8c9e994c3c4ef516f6f35941b846e714cd40159f7b1e4bccc63ac0c18a1",
        }
        for name, expected in expected_hashes.items():
            self.assertEqual(hashlib.sha256((evidence / name).read_bytes()).hexdigest(), expected)
        self.assertEqual((evidence / "post-disable-env.txt").read_text(), "FZF_DEFAULT_OPTS=\n")
        self.assertEqual((evidence / "post-uninstall-env.txt").read_text(), "FZF_DEFAULT_OPTS=\n")
        commands = (evidence / "commands.txt").read_text()
        self.assertIn("Post-disable application restoration gate:", commands)
        self.assertIn("thpm-fzf-post-disable", commands)
        self.assertIn("Post-uninstall application restoration gate:", commands)
        self.assertIn("thpm-fzf-post-uninstall", commands)

    def test_zellij_is_supported_after_complete_live_certification_and_signoff(self):
        zellij = next(plugin for plugin in PLUGINS if plugin.id == "zellij")
        root = Path(__file__).parents[1]
        support = (root / "docs/integration-support.md").read_text()

        self.assertEqual(zellij.support_status, "supported")
        self.assertRegex(
            support,
            r"(?m)^\| `zellij` \| Complete \| Supported \| disabled \|",
        )
        record = root / "docs/certifications/zellij-2026-08-28.md"
        evidence = record.parent / "evidence/zellij-2026-08-28"
        self.assertTrue(record.is_file())
        record_text = record.read_text()
        self.assertIn('omarchy-theme-set "Dune"', record_text)
        self.assertIn('omarchy-theme-set "Last Call"', record_text)
        for name in ("commands.txt", "zellij-dune.png", "zellij-last-call.png"):
            self.assertTrue((evidence / name).is_file(), name)
        self.assertEqual(
            hashlib.sha256((evidence / "zellij-dune.png").read_bytes()).hexdigest(),
            "11eeb389e7f966493f9c972ab27d2f77013120836750ff19e20653898240068c",
        )
        self.assertEqual(
            hashlib.sha256((evidence / "zellij-last-call.png").read_bytes()).hexdigest(),
            "922b0308f2b0b0d9fa5e4a059d8d9fe2a1421ef659c89b0e637303b45febd9ab",
        )
        commands = (evidence / "commands.txt").read_text()
        self.assertIn("user_edit_preserved=true", commands)
        self.assertIn("uninstall_restored_config=true", commands)
        self.assertIn("parser_before_after=true", commands)

    def test_every_registered_template_is_packaged(self):
        templates = Path(__file__).parents[1] / "assets/templates"
        missing = [name for plugin in PLUGINS for name in plugin.templates if not (templates / name).is_file()]
        self.assertEqual(missing, [])

    def test_support_register_matches_active_integrations_and_defaults(self):
        support = (Path(__file__).parents[1] / "docs/integration-support.md").read_text()
        rows = re.findall(
            r"^\| `([^`]+)` \| (Incomplete|Complete) "
            r"\| (Experimental|Supported|Unresolved release blocker) "
            r"\| (enabled|disabled) \|",
            support,
            flags=re.MULTILINE,
        )
        self.assertEqual([plugin_id for plugin_id, _, _, _ in rows], [p.id for p in PLUGINS])
        documented = {
            plugin_id: (audit, disposition, default)
            for plugin_id, audit, disposition, default in rows
        }
        for plugin in PLUGINS:
            self.assertEqual(
                documented[plugin.id][2],
                "enabled" if plugin.default_enabled else "disabled",
            )
        for plugin_id, audit, disposition, _default in rows:
            plugin = next(item for item in PLUGINS if item.id == plugin_id)
            expected_audit = (
                "Complete" if plugin.support_status == "supported" else "Incomplete"
            )
            self.assertEqual(audit, expected_audit)
            self.assertEqual(disposition.lower(), plugin.support_status)

    def test_templates_use_canonical_palette_keys_and_render_completely(self):
        templates = Path(__file__).parents[1] / "assets/templates"
        legacy = set(CANONICAL_NAMES)
        placeholder = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
        rendered: dict[str, str] = {}

        def substitute(match: re.Match[str]) -> str:
            expression = match.group(1).strip()
            parts = expression.split()
            if parts and parts[0] == "gradient_start":
                # Mirrors Omarchy's resolve_theme_ref: the referenced color
                # wins when the palette defines it, otherwise the fallback
                # reference does. Either way the token always renders, which
                # is what lets a template reach an optional semantic color.
                self.assertEqual(
                    len(parts), 3, f"unsupported gradient_start form: {expression}"
                )
                _, reference, fallback = parts
                self.assertNotIn(reference, legacy)
                self.assertNotIn(fallback, legacy)
                self.assertIn(fallback, CANONICAL_COLORS)
                return CANONICAL_COLORS.get(reference, CANONICAL_COLORS[fallback])
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

    def test_fish_template_sets_effective_syntax_and_pager_colors(self):
        template = (
            Path(__file__).parents[1] / "assets/templates/thpm-fish.fish.tpl"
        ).read_text()
        expected = {
            "fish_color_normal": "{{ foreground }}",
            "fish_color_command": "{{ blue }}",
            "fish_color_keyword": "{{ magenta }}",
            "fish_color_quote": "{{ green }}",
            "fish_color_redirection": "{{ cyan }}",
            "fish_color_end": "{{ yellow }}",
            "fish_color_error": "{{ red }}",
            "fish_color_param": "{{ foreground }}",
            "fish_color_comment": "{{ muted }}",
            "fish_color_selection": "{{ bright_foreground }}",
            "fish_color_search_match": "{{ bright_foreground }}",
            "fish_color_operator": "{{ cyan }}",
            "fish_color_escape": "{{ magenta }}",
            "fish_color_autosuggestion": "{{ muted }}",
            "fish_pager_color_prefix": "{{ blue }}",
            "fish_pager_color_completion": "{{ foreground }}",
            "fish_pager_color_description": "{{ muted }}",
            "fish_pager_color_selected_background": "{{ bright_foreground }}",
        }
        for variable, color in expected.items():
            with self.subTest(variable=variable):
                line = next(
                    (
                        item
                        for item in template.splitlines()
                        if item.startswith(f"set -g {variable} ")
                    ),
                    "",
                )
                self.assertIn(color, line)
        for variable in (
            "fish_color_selection",
            "fish_color_search_match",
            "fish_pager_color_selected_background",
        ):
            line = next(
                item
                for item in template.splitlines()
                if item.startswith(f"set -g {variable} ")
            )
            self.assertIn("--background={{ selection }}", line)
    def test_superfile_template_covers_the_complete_v1_6_theme_contract(self):
        template = (
            Path(__file__).parents[1] / "assets/templates/thpm-superfile.toml.tpl"
        ).read_text()
        keys = set(re.findall(r"(?m)^([a-z_]+)\s*=", template))
        required = {
            "code_syntax_highlight",
            "full_screen_fg",
            "full_screen_bg",
            "gradient_color",
            "file_panel_fg",
            "file_panel_bg",
            "file_panel_border",
            "file_panel_border_active",
            "file_panel_top_directory_icon",
            "file_panel_top_path",
            "file_panel_item_selected_fg",
            "file_panel_item_selected_bg",
            "footer_fg",
            "footer_bg",
            "footer_border",
            "footer_border_active",
            "sidebar_fg",
            "sidebar_bg",
            "sidebar_title",
            "sidebar_border",
            "sidebar_border_active",
            "sidebar_item_selected_fg",
            "sidebar_item_selected_bg",
            "sidebar_divider",
            "modal_fg",
            "modal_bg",
            "modal_border_active",
            "modal_cancel_fg",
            "modal_cancel_bg",
            "modal_confirm_fg",
            "modal_confirm_bg",
            "help_menu_hotkey",
            "help_menu_title",
            "cursor",
            "correct",
            "error",
            "hint",
            "cancel",
        }
        self.assertEqual(keys, required)
        self.assertIn('code_syntax_highlight = "catppuccin-mocha"', template)
        self.assertTrue(
            {"directory_icon", "footer", "metadata"}.isdisjoint(keys),
            "obsolete partial-theme keys must not masquerade as Superfile v1.6 fields",
        )
    def test_vencord_fallback_uses_owned_licensed_midnight_base(self):
        root = Path(__file__).parents[1]
        template = (root / "assets/templates/thpm-vencord.theme.css.tpl").read_text()
        base = (root / "assets/vencord/thpm-midnight.css").read_text()
        license_text = (root / "assets/vencord/LICENSE.midnight").read_text()
        upstream = (root / "assets/vencord/UPSTREAM.md").read_text()

        self.assertIn(
            "https://cdn.jsdelivr.net/gh/OldJobobo/thpm@main/assets/vencord/thpm-midnight.css",
            template,
        )
        self.assertNotIn("imbypass", template.lower())
        self.assertNotIn("refact0r.github.io", template)
        self.assertIn("--text-0: #000000", template)
        for role in ("red", "green", "yellow", "blue", "magenta"):
            self.assertGreaterEqual(template.count(f"{{{{ {role} }}}}, #ffffff 40%"), 2)
        self.assertIn("--accent-2: color-mix(in srgb, {{ blue }}, #ffffff 40%)", template)
        self.assertIn("--red-2: color-mix(in srgb, {{ red }}, #ffffff 40%)", template)
        self.assertIn("Derived from refact0r/midnight-discord", base)
        self.assertIn("--background-base-lowest", base)
        self.assertIn("MIT License", license_text)
        self.assertIn("Permission is hereby granted", base)
        css_commit = re.search(r"Upstream commit: ([0-9a-f]{40})", base)
        provenance_commit = re.search(r"Upstream commit: `([0-9a-f]{40})`", upstream)
        self.assertIsNotNone(css_commit)
        self.assertIsNotNone(provenance_commit)
        self.assertEqual(css_commit.group(1), provenance_commit.group(1))
        recorded_hash = re.search(r"Upstream artifact SHA-256: `([0-9a-f]{64})`", upstream)
        self.assertIsNotNone(recorded_hash)
        upstream_artifact = base[base.index("/* main.css */"):]
        self.assertEqual(
            hashlib.sha256(upstream_artifact.encode()).hexdigest(),
            recorded_hash.group(1),
        )

    def test_vencord_colored_controls_keep_readable_text(self):
        palettes = {
            "catppuccin-latte": ("#d20f39", "#40a02b", "#df8e1d", "#1e66f5", "#8839ef"),
            "flexoki-light": ("#af3029", "#66800b", "#ad8301", "#205ea6", "#a02f6f"),
            "miasma": ("#685742", "#5f875f", "#b36d43", "#78824b", "#bb7744"),
            "white": ("#2a2a2a", "#3a3a3a", "#4a4a4a", "#1a1a1a", "#2e2e2e"),
        }

        def luminance(rgb: tuple[int, int, int]) -> float:
            channels = [value / 255 for value in rgb]
            linear = [
                value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
                for value in channels
            ]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        for name, colors in palettes.items():
            for color in colors:
                raw = tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))
                lifted = tuple(round(value * 0.6 + 255 * 0.4) for value in raw)
                contrast = (luminance(lifted) + 0.05) / 0.05
                with self.subTest(theme=name, color=color):
                    self.assertGreaterEqual(contrast, 4.5)

    def test_obsidian_terminal_plugin_is_exposed_separately_from_native_obsidian(self):
        plugins = {plugin.id: plugin for plugin in PLUGINS}
        self.assertIn("obsidian-terminal", plugins)
        self.assertEqual(plugins["obsidian-terminal"].kind, "action")


class ConfigTests(Sandbox):
    def test_missing_config_uses_automatic_restart_policy(self):
        preferences = load_config(self.paths)

        self.assertEqual(preferences.restart_policy, "automatic")
        self.assertTrue(preferences.automatic_app_restarts)

    def test_restart_policy_round_trips_through_user_config(self):
        save_config(self.paths, Preferences(restart_policy="notify"))

        self.assertEqual(load_config(self.paths).restart_policy, "notify")
        self.assertIn(
            'restart_policy = "notify"', self.paths.config_file.read_text()
        )

    def test_invalid_current_config_is_reported(self):
        self.paths.config_file.parent.mkdir(parents=True)
        self.paths.config_file.write_text(
            'config_version = 1\n[behavior]\nrestart_policy = "sometimes"\n'
        )

        with self.assertRaisesRegex(ConfigError, "automatic.*notify"):
            load_config(self.paths)


class MigrationTests(Sandbox):
    def test_migration_reads_names_not_legacy_contents(self):
        self.paths.hook_dir.mkdir(parents=True)
        legacy = self.paths.hook_dir / "40-firefox.sh"
        legacy.write_text("exit 99\n")
        updates, files = inspect(self.paths)
        self.assertTrue(updates["firefox"])
        self.assertEqual(files, [legacy])

    def test_migration_preserves_hook_shaped_directories_and_symlinks(self):
        self.paths.hook_dir.mkdir(parents=True)
        directory = self.paths.hook_dir / "40-firefox.sh"
        directory.mkdir()
        child = directory / "keep"
        child.write_text("user content")
        target = self.paths.home / "external-zed-hook"
        target.write_text("external hook")
        linked = self.paths.hook_dir / "40-zed.sh"
        linked.symlink_to(target)
        dangling = self.paths.hook_dir / "40-steam.sh"
        dangling.symlink_to(self.paths.home / "missing-hook")

        updates, files = inspect(self.paths)
        destination = archive(self.paths, files)

        self.assertEqual(updates, {})
        self.assertEqual(files, [])
        self.assertIsNone(destination)
        self.assertEqual(child.read_text(), "user content")
        self.assertTrue(linked.is_symlink())
        self.assertEqual(target.read_text(), "external hook")
        self.assertTrue(dangling.is_symlink())

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

    def test_migration_replaces_legacy_obsidian_terminal_hook(self):
        self.paths.hook_dir.mkdir(parents=True)
        legacy = self.paths.hook_dir / "40-obsidian-terminal.sh"
        legacy.write_text("legacy integration\n")
        updates, files = inspect(self.paths)
        self.assertTrue(updates["obsidian-terminal"])
        self.assertIn(legacy, files)

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

    def test_upgrade_preserves_current_user_config(self):
        save_config(self.paths, Preferences(restart_policy="notify"))

        self.assertNotIn(self.paths.config_file, artifacts(self.paths))

    def test_upgrade_preserves_malformed_current_user_config_for_diagnosis(self):
        self.paths.config_file.parent.mkdir(parents=True)
        self.paths.config_file.write_text(
            'config_version=1\n[behavior\nrestart_policy = "notify"\n'
        )

        self.assertNotIn(self.paths.config_file, artifacts(self.paths))

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

    def test_service_migration_prefers_enabled_legacy_system24(self):
        self.paths.hook_dir.mkdir(parents=True)
        old_hook = self.paths.hook_dir / "40-discord-system24.sh"
        old_hook.write_text("legacy")
        assets = Path(__file__).parents[1] / "assets"

        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            payload = Service(self.paths).migrate()

        self.assertTrue(payload["ok"])
        enabled = load(self.paths)
        self.assertFalse(enabled["discord"])
        self.assertTrue(enabled["discord-system24"])

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
            self.assertIn('"action":"thpm ui open"', installed)
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
            self.assertIn('"action":"thpm ui open"', self.paths.menu_extension.read_text())
            ui.remove(self.paths)
        self.assertIn('"foreign"', self.paths.menu_extension.read_text())
        self.assertNotIn("style.theme-hooks", self.paths.menu_extension.read_text())

    def test_surface_rejects_invalid_menu_without_persisting_selection(self):
        self.paths.ui_state_file.parent.mkdir(parents=True)
        self.paths.ui_state_file.write_text('menu_surface = "gui"\n')
        self.paths.menu_extension.parent.mkdir(parents=True)

        for invalid in (
            "[]\n",
            '{"broken"\n',
            '{"broken"}\n',
            '{"foreign": t/*comment*/rue}\n',
            '{"foreign": [,]}\n',
        ):
            with self.subTest(menu=invalid):
                self.paths.menu_extension.write_text(invalid)

                with self.assertRaises(ValueError):
                    ui.surface(self.paths, "tui")

                self.assertEqual(
                    self.paths.ui_state_file.read_text(), 'menu_surface = "gui"\n'
                )
                self.assertEqual(self.paths.menu_extension.read_text(), invalid)

    def test_surface_accepts_jsonc_with_cr_only_line_endings(self):
        text = '{\r"foreign": true, // keep this entry\r}\r'
        self.assertEqual(ui._parse_jsonc(text), {"foreign": True})
        self.paths.menu_extension.parent.mkdir(parents=True)
        self.paths.menu_extension.write_bytes(text.encode())

        result = ui.surface(self.paths, "tui")

        self.assertEqual(result["surface"], "tui")
        self.assertIn('"foreign": true', self.paths.menu_extension.read_text())

    def test_surface_restores_menu_when_state_write_fails(self):
        self.paths.ui_state_file.parent.mkdir(parents=True)
        self.paths.ui_state_file.write_text('menu_surface = "gui"\n')
        self.paths.menu_extension.parent.mkdir(parents=True)
        previous_menu = '{\n  "foreign": {"label":"Mine"}\n}\n'
        self.paths.menu_extension.write_text(previous_menu)
        self.paths.menu_extension.chmod(0o600)
        hard_link = self.paths.menu_extension.with_name("menu-hard-link.jsonc")
        os.link(self.paths.menu_extension, hard_link)
        previous_inode = self.paths.menu_extension.stat().st_ino
        atomic_text = ui.atomic_text

        def fail_state(path, text, mode=0o644):
            if path == self.paths.ui_state_file:
                raise OSError("state unavailable")
            return atomic_text(path, text, mode)

        with patch("thpm.ui.atomic_text", side_effect=fail_state), self.assertRaises(
            OSError
        ):
            ui.surface(self.paths, "tui")

        self.assertEqual(self.paths.menu_extension.read_text(), previous_menu)
        self.assertEqual(self.paths.menu_extension.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.paths.menu_extension.stat().st_ino, previous_inode)
        self.assertEqual(hard_link.stat().st_ino, previous_inode)
        self.assertEqual(hard_link.read_text(), previous_menu)
        self.assertEqual(
            self.paths.ui_state_file.read_text(), 'menu_surface = "gui"\n'
        )

    def test_surface_restores_menu_after_encoding_failure(self):
        self.paths.menu_extension.parent.mkdir(parents=True)
        previous_menu = '{\n  "foreign": {"label":"Mine"}\n}\n'
        self.paths.menu_extension.write_text(previous_menu)
        previous_inode = self.paths.menu_extension.stat().st_ino
        atomic_text = ui.atomic_text

        def fail_menu(path, text, mode=0o644):
            if path == self.paths.menu_extension:
                raise UnicodeEncodeError("ascii", "󰆍", 0, 1, "unsupported")
            return atomic_text(path, text, mode)

        with patch("thpm.ui.atomic_text", side_effect=fail_menu), self.assertRaises(
            UnicodeEncodeError
        ):
            ui.surface(self.paths, "tui")

        self.assertEqual(self.paths.menu_extension.read_text(), previous_menu)
        self.assertEqual(self.paths.menu_extension.stat().st_ino, previous_inode)

    def test_surface_serializes_the_complete_transaction(self):
        with patch("thpm.ui._ui_lock", wraps=ui._ui_lock) as lock:
            ui.surface(self.paths, "tui")

        lock.assert_called_once_with(self.paths)

    def test_ui_lock_is_user_scoped_and_guards_all_menu_writers(self):
        with ui._ui_lock(self.paths):
            pass
        lock_dir = self.paths.ui_lock_dir
        self.assertTrue((lock_dir / "ui.lock").exists())
        self.assertEqual(lock_dir.stat().st_uid, os.getuid())
        self.assertEqual(lock_dir.stat().st_mode & 0o777, 0o700)
        self.paths.thpm_state_dir.mkdir(parents=True)
        shutil.rmtree(self.paths.thpm_state_dir)
        self.assertTrue((lock_dir / "ui.lock").exists())

        with patch("thpm.ui._ui_lock", wraps=ui._ui_lock) as lock, patch(
            "thpm.ui._install_locked", return_value={"installed": True}
        ):
            ui.install(self.paths)
        lock.assert_called_once_with(self.paths)

        with patch("thpm.ui._ui_lock", wraps=ui._ui_lock) as lock, patch(
            "thpm.ui._remove_locked", return_value={"installed": False}
        ):
            ui.remove(self.paths)
        lock.assert_called_once_with(self.paths)

    def test_ui_lock_rejects_a_symlinked_private_directory(self):
        external = self.paths.home / "attacker-locks"
        external.mkdir()
        lock_dir = self.paths.ui_lock_dir
        lock_dir.parent.mkdir(parents=True)
        lock_dir.symlink_to(external)

        with self.assertRaisesRegex(PermissionError, "privately owned"):
            with ui._ui_lock(self.paths):
                pass

    def test_surface_restores_menu_symlink_when_state_write_fails(self):
        self.paths.ui_state_file.parent.mkdir(parents=True)
        self.paths.ui_state_file.write_text('menu_surface = "gui"\n')
        menu_target = self.paths.home / "dotfiles/omarchy-menu.jsonc"
        menu_target.parent.mkdir(parents=True)
        previous_menu = '{\n  "foreign": {"label":"Mine"}\n}\n'
        menu_target.write_text(previous_menu)
        self.paths.menu_extension.parent.mkdir(parents=True)
        link_target = os.path.relpath(menu_target, self.paths.menu_extension.parent)
        self.paths.menu_extension.symlink_to(link_target)
        atomic_text = ui.atomic_text

        def fail_state(path, text, mode=0o644):
            if path == self.paths.ui_state_file:
                raise OSError("state unavailable")
            return atomic_text(path, text, mode)

        with patch("thpm.ui.atomic_text", side_effect=fail_state), self.assertRaises(
            OSError
        ):
            ui.surface(self.paths, "tui")

        self.assertTrue(self.paths.menu_extension.is_symlink())
        self.assertEqual(os.readlink(self.paths.menu_extension), link_target)
        self.assertEqual(menu_target.read_text(), previous_menu)
        self.assertEqual(
            self.paths.ui_state_file.read_text(), 'menu_surface = "gui"\n'
        )

    def test_open_repairs_disabled_plugin_and_confirms_active_panel(self):
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch(
            "thpm.ui.shell_running", return_value=False
        ):
            ui.install(self.paths)

        self.paths.menu_extension.write_text(
            self.paths.menu_extension.read_text().replace(
                "thpm ui open", f"omarchy shell shell summon {ui.PLUGIN_ID} '{{}}'"
            )
        )
        disabled = {"id": ui.PLUGIN_ID, "enabled": False, "active": False}
        enabled = {"id": ui.PLUGIN_ID, "enabled": True, "active": False}
        states = iter((disabled, enabled))

        def command(*args, **kwargs):
            if args == ("plugin", "list", "--json"):
                return subprocess.CompletedProcess(args, 0, json.dumps([next(states)]), "")
            if args[:2] == ("plugin", "enable"):
                return subprocess.CompletedProcess(args, 0, "Enabled\n", "")
            if args == ("menu", "refresh"):
                return subprocess.CompletedProcess(args, 0, "ok\n", "")
            if args[:3] == ("shell", "shell", "summon"):
                return subprocess.CompletedProcess(args, 0, "ok\n", "")
            if args[:3] == ("shell", "shell", "call"):
                return subprocess.CompletedProcess(args, 0, "open\n", "")
            self.fail(f"unexpected Omarchy command: {args}")

        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch(
            "thpm.ui.shell_running", return_value=True
        ), patch("thpm.ui.run", side_effect=command) as run:
            result = ui.open_manager(self.paths, fallback=False)

        self.assertTrue(result["opened"])
        self.assertTrue(result["enabled"])
        self.assertTrue(result["menuSynchronized"])
        self.assertIn('"action":"thpm ui open"', self.paths.menu_extension.read_text())
        self.assertFalse(result["synchronized"])
        self.assertIn(call("plugin", "enable", ui.PLUGIN_ID, check=False, timeout=5), run.call_args_list)

    def test_open_synchronizes_stale_qml_before_summoning(self):
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch(
            "thpm.ui.shell_running", return_value=False
        ):
            ui.install(self.paths)
        (self.paths.shell_plugin_dir / "Panel.qml").write_text("stale")

        enabled = {"id": ui.PLUGIN_ID, "enabled": True, "active": False}
        states = iter((enabled, enabled))

        def command(*args, **kwargs):
            if args == ("shell", "shell", "rescanPlugins"):
                return subprocess.CompletedProcess(args, 0, "", "")
            if args == ("plugin", "list", "--json"):
                return subprocess.CompletedProcess(args, 0, json.dumps([next(states)]), "")
            if args[:3] == ("shell", "shell", "summon"):
                return subprocess.CompletedProcess(args, 0, "ok\n", "")
            if args[:3] == ("shell", "shell", "call"):
                return subprocess.CompletedProcess(args, 0, "open\n", "")
            self.fail(f"unexpected Omarchy command: {args}")

        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch(
            "thpm.ui.shell_running", return_value=True
        ), patch("thpm.ui.run", side_effect=command):
            result = ui.open_manager(self.paths, fallback=False)

        self.assertTrue(result["synchronized"])
        self.assertEqual(
            (self.paths.shell_plugin_dir / "Panel.qml").read_bytes(),
            (assets / "qml/Panel.qml.in").read_bytes(),
        )

    def test_open_treats_unknown_stdout_as_failure_and_launches_recovery(self):
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch(
            "thpm.ui.shell_running", return_value=False
        ):
            ui.install(self.paths)
        enabled = {"id": ui.PLUGIN_ID, "enabled": True, "active": False}

        def command(*args, **kwargs):
            if args == ("plugin", "list", "--json"):
                return subprocess.CompletedProcess(args, 0, json.dumps([enabled]), "")
            if args[:3] == ("shell", "shell", "summon"):
                return subprocess.CompletedProcess(args, 0, "unknown\n", "")
            self.fail(f"unexpected Omarchy command: {args}")

        process = Mock()
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch(
            "thpm.ui.shell_running", return_value=True
        ), patch("thpm.ui.run", side_effect=command), patch(
            "thpm.ui.shutil.which", return_value="/usr/bin/omarchy-launch-floating-terminal-with-presentation"
        ), patch("thpm.ui.subprocess.Popen", return_value=process) as popen:
            result = ui.open_manager(self.paths)

        self.assertEqual(result["surface"], "recovery-tui")
        self.assertTrue(result["degraded"])
        self.assertIn("unknown", result["graphicalError"])
        popen.assert_called_once()

    def test_install_uses_supported_shell_rescan_and_verifies_enablement(self):
        assets = Path(__file__).parents[1] / "assets"
        discovered = {"id": ui.PLUGIN_ID, "enabled": False, "active": False}
        enabled = {"id": ui.PLUGIN_ID, "enabled": True, "active": False}
        states = iter((discovered, discovered, enabled))

        def command(*args, **kwargs):
            if args == ("shell", "shell", "rescanPlugins"):
                return subprocess.CompletedProcess(args, 0, "", "")
            if args == ("plugin", "list", "--json"):
                return subprocess.CompletedProcess(args, 0, json.dumps([next(states)]), "")
            if args[:2] == ("plugin", "enable"):
                return subprocess.CompletedProcess(args, 0, "Enabled\n", "")
            if args == ("menu", "refresh"):
                return subprocess.CompletedProcess(args, 0, "ok\n", "")
            self.fail(f"unexpected Omarchy command: {args}")

        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch(
            "thpm.ui.shell_running", return_value=True
        ), patch("thpm.ui.run", side_effect=command) as run:
            result = ui.install(self.paths)

        self.assertTrue(result["rescanned"])
        self.assertTrue(result["enabled"])
        self.assertNotIn(call("plugin", "rescan", check=False), run.call_args_list)

    def test_sync_preserves_explicit_no_ui_install_and_repairs_existing_ui(self):
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            self.assertTrue(ui.sync(self.paths)["skipped"])
            self.paths.shell_plugin_dir.mkdir(parents=True)
            with patch("thpm.ui.install", return_value={"installed": True}) as install:
                self.assertTrue(ui.sync(self.paths)["installed"])
        install.assert_called_once_with(self.paths)

    def test_menu_install_preserves_comment_terminated_shibumi_block(self):
        self.paths.menu_extension.parent.mkdir(parents=True)
        self.paths.menu_extension.write_text(
            "{\n"
            "  // shibumi-picker-routing-start\n"
            '  "style.theme": {"label":"Theme"},\n'
            '  "style.background": {"label":"Background"}\n'
            "  // shibumi-picker-routing-end\n"
            "}\n"
        )
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch(
            "thpm.ui.shell_running", return_value=False
        ):
            ui.install(self.paths)
            installed = self.paths.menu_extension.read_text()
            uncommented = "\n".join(
                line for line in installed.splitlines() if not line.lstrip().startswith("//")
            )
            parsed = json.loads(re.sub(r",\s*}$", "\n}", uncommented))
            self.assertEqual(parsed["style.theme-hooks"]["label"], "Theme Hook Plugins")
            self.assertEqual(parsed["style.theme"]["label"], "Theme")
            self.assertEqual(parsed["style.background"]["label"], "Background")
            self.assertNotIn("// shibumi-picker-routing-end,", installed)

    def test_post_update_hook_uses_idempotent_ui_sync(self):
        hook = (Path(__file__).parents[1] / "assets/hooks/90-thpm-ui").read_text()
        self.assertIn("exec thpm --json ui sync", hook)
        self.assertNotIn("ui install", hook)

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
        self.assertIn("function health(payloadJson)", qml)
        self.assertIn('return opened && surface.visible ? "open" : "loaded"', qml)

    def test_qml_design_stays_single_panel_and_uses_omarchy_controls(self):
        qml = (Path(__file__).parents[1] / "assets/qml/Panel.qml.in").read_text()
        self.assertEqual(qml.count("FloatingWindow {"), 1)
        self.assertIn("import qs.Ui", qml)
        self.assertIn("BorderSurface {", qml)
        self.assertIn("TextField {", qml)
        self.assertIn("delegate: Toggle {", qml)
        self.assertIn('modelData.supportStatus === "experimental"', qml)
        self.assertIn('" · Experimental"', qml)
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
        self.assertIn(
            'command: ["thpm", "--json", "update", "apply", "--terminal"]',
            qml,
        )
        self.assertIn("updateInfo.refreshRequired", qml)
        self.assertIn("updateInfo.uiRefreshRequired", qml)
        self.assertIn("updateError = payload.ok === false", qml)
        self.assertIn('updateInfo.status === "updated" && updateError', qml)
        self.assertIn("color: root.updateError ? Color.urgent", qml)
        self.assertIn("thpm reconcile --refresh", qml)
        self.assertIn("thpm ui install", qml)
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

    def test_qml_exposes_restart_policy_and_pending_apps(self):
        qml = (Path(__file__).parents[1] / "assets/qml/Panel.qml.in").read_text()
        self.assertIn('property string restartPolicy: "automatic"', qml)
        self.assertIn('label: "Restart apps automatically"', qml)
        self.assertIn(
            '["thpm", "--json", "config", "restart-policy", policy]', qml
        )
        self.assertIn('" Restart needed: " + restartRequired.join(", ")', qml)

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
    def test_json_envelope_exposes_support_status_and_native_ownership(self):
        payload = Service(self.paths).state()
        self.assertEqual(payload["schemaVersion"], 1)
        active = [p for p in payload["plugins"] if p["ownership"] != "native"]
        native = [p for p in payload["plugins"] if p["ownership"] == "native"]
        self.assertTrue(active)
        self.assertTrue(native)
        self.assertEqual(
            [p["id"] for p in active if p["supportStatus"] == "supported"],
            ["fzf", "zellij"],
        )
        self.assertTrue(
            all(
                p["supportStatus"] == "experimental"
                for p in active
                if p["id"] not in {"fzf", "zellij"}
            )
        )
        self.assertTrue(all(not p["enabled"] for p in active))
        self.assertTrue(all(p["supportStatus"] == "native" for p in native))
        self.assertEqual(payload["menuSurface"], "gui")

    def test_state_exposes_restart_policy_to_both_frontends(self):
        save_config(self.paths, Preferences(restart_policy="notify"))

        payload = Service(self.paths).state()

        self.assertEqual(payload["preferences"]["restartPolicy"], "notify")
        self.assertFalse(payload["preferences"]["automaticAppRestarts"])

    def test_restart_policy_service_writes_user_config(self):
        payload = Service(self.paths).restart_policy("notify")

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["changed"])
        self.assertEqual(load_config(self.paths).restart_policy, "notify")

    def test_invalid_config_falls_back_to_notify_only_with_warning(self):
        self.paths.config_file.parent.mkdir(parents=True)
        self.paths.config_file.write_text("config_version = 1\n[behavior\n")

        payload = Service(self.paths).state()

        self.assertEqual(payload["preferences"]["restartPolicy"], "notify")
        self.assertIn("notify-only", str(payload["warnings"]))

    def test_hook_uses_notify_policy_and_sends_one_restart_notification(self):
        save_config(self.paths, Preferences(restart_policy="notify"))
        result = {
            "results": [],
            "counts": {"applied": 0, "unchanged": 0, "skipped": 0, "failed": 0},
            "changed": [],
            "actions": [],
            "restartRequired": ["Spotify", "running GTK applications"],
            "errors": [],
            "warnings": [],
        }
        with patch.dict(os.environ, {"THPM_FORCE_RELOAD": "1"}), patch(
            "thpm.service.apply_enabled", return_value=result
        ) as apply_all, patch(
            "thpm.service._notify_restart_required", return_value=True
        ) as notify:
            payload = Service(self.paths).hook_run("theme-set", ["Test"])

        self.assertFalse(apply_all.call_args.kwargs["automatic_restarts"])
        self.assertTrue(apply_all.call_args.kwargs["force_reload"])
        self.assertTrue(payload["forced"])
        notify.assert_called_once_with(["Spotify", "running GTK applications"])
        self.assertTrue(payload["restartNotificationSent"])
        self.assertEqual(payload["restartPolicy"], "notify")

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
        self.paths.post_update_hook_file.parent.mkdir(parents=True)
        self.paths.post_update_hook_file.write_text("remove")
        self.paths.canonical_palette_migration_marker.parent.mkdir(parents=True)
        self.paths.canonical_palette_migration_marker.write_text("done\n")
        self.paths.config_file.parent.mkdir(parents=True)
        self.paths.config_file.write_text("config_version = 1\n")
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
        self.assertFalse(self.paths.post_update_hook_file.exists())
        self.assertFalse(self.paths.canonical_palette_migration_marker.exists())
        self.assertFalse(self.paths.thpm_config_dir.exists())
        self.assertFalse(self.paths.thpm_state_dir.exists())
        self.assertFalse(payload["cleanupIncomplete"])
        self.assertIsNone(payload["recoveryCommand"])
        self.assertEqual(zellij_config.read_text(), "")
        self.assertEqual(fish_target.read_text(), "user output")
        self.assertFalse(fish_source.exists())
        self.assertNotIn("restart active Zellij sessions", str(payload["warnings"]))

    def test_uninstall_reports_restart_for_a_running_zellij_session(self):
        source = self.paths.current_theme / "zellij.kdl"
        source.parent.mkdir(parents=True)
        source.write_text('themes { source { fg "white" } }\n')
        apply("zellij", self.paths)

        with patch(
            "thpm.service._zellij_process_running", return_value=True
        ), patch("thpm.service.ui.remove", return_value={"installed": False}):
            payload = Service(self.paths).uninstall()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["restartRequired"], ["Zellij"])

    def test_noop_uninstall_does_not_report_zellij_restart(self):
        with patch(
            "thpm.service._zellij_process_running", return_value=True
        ), patch("thpm.service.ui.remove", return_value={"installed": False}):
            payload = Service(self.paths).uninstall()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["restartRequired"], [])

    def test_disable_reports_incomplete_cleanup_for_invalid_optional_asset_backup(self):
        source = self.paths.current_theme / "cliamp.toml"
        source.parent.mkdir(parents=True)
        source.write_text("# thpm:cliamp-use-native\nmanaged theme")
        target = self.paths.config_home / "cliamp/themes/omarchy.toml"
        target.parent.mkdir(parents=True)
        target.write_text("user default")
        apply("cliamp", self.paths)
        backup = self.paths.managed_asset_state_dir / "cliamp.backup"
        state_file = self.paths.managed_asset_state_dir / "cliamp.json"
        backup.unlink()

        payload = Service(self.paths).set_enabled("cliamp", False, refresh=False)

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["committed"])
        self.assertTrue(payload["cleanupIncomplete"])
        self.assertEqual(payload["recoveryCommand"], "thpm disable cliamp")
        self.assertIn(str(state_file), payload["retainedPaths"])
        self.assertNotIn(str(backup), payload["retainedPaths"])
        self.assertFalse(load(self.paths)["cliamp"])
        self.assertEqual(
            target.read_text(), "# thpm:cliamp-use-native\nmanaged theme"
        )
        self.assertTrue(self.paths.managed_asset_state_dir.exists())

    def test_uninstall_retains_recovery_data_for_invalid_optional_asset_backup(self):
        source = self.paths.current_theme / "cliamp.toml"
        source.parent.mkdir(parents=True)
        source.write_text("# thpm:cliamp-use-native\nmanaged theme")
        target = self.paths.config_home / "cliamp/themes/omarchy.toml"
        target.parent.mkdir(parents=True)
        target.write_text("user default")
        apply("cliamp", self.paths)
        backup = self.paths.managed_asset_state_dir / "cliamp.backup"
        state_file = self.paths.managed_asset_state_dir / "cliamp.json"
        backup.unlink()
        self.paths.install_metadata.parent.mkdir(parents=True, exist_ok=True)
        self.paths.install_metadata.write_text('origin = "source"\n')

        with patch("thpm.service.ui.remove", return_value={"installed": False}):
            payload = Service(self.paths).uninstall()

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["committed"])
        self.assertTrue(payload["cleanupIncomplete"])
        self.assertEqual(payload["recoveryCommand"], "thpm uninstall")
        self.assertIn(str(state_file), payload["retainedPaths"])
        self.assertNotIn(str(backup), payload["retainedPaths"])
        self.assertTrue(payload["residuals"])
        self.assertEqual(
            target.read_text(), "# thpm:cliamp-use-native\nmanaged theme"
        )
        self.assertTrue(self.paths.managed_asset_state_dir.exists())
        self.assertTrue(self.paths.install_metadata.exists())

    def test_uninstall_preserves_user_modified_asset_as_successful_cleanup(self):
        source = self.paths.current_theme / "cliamp.toml"
        source.parent.mkdir(parents=True)
        source.write_text("# thpm:cliamp-use-native\nmanaged theme")
        target = self.paths.config_home / "cliamp/themes/omarchy.toml"
        target.parent.mkdir(parents=True)
        target.write_text("user default")
        apply("cliamp", self.paths)
        target.write_text("user changed")

        with patch("thpm.service.ui.remove", return_value={"installed": False}):
            payload = Service(self.paths).uninstall()

        self.assertTrue(payload["ok"])
        self.assertFalse(payload["cleanupIncomplete"])
        self.assertEqual(target.read_text(), "user changed")
        self.assertFalse(self.paths.thpm_state_dir.exists())
        self.assertIn("preserved user-modified", str(payload["warnings"]))

    def test_uninstall_restores_historical_swaync_asset(self):
        managed = b"retired SwayNC theme\n"
        prior = b"user SwayNC theme\n"
        target = self.paths.config_home / "swaync/colors.css"
        target.parent.mkdir(parents=True)
        target.write_bytes(managed)
        state = self.paths.managed_asset_state_dir / "swaync.json"
        backup = self.paths.managed_asset_state_dir / "swaync.backup"
        state.parent.mkdir(parents=True)
        backup.write_bytes(prior)
        state.write_text(
            json.dumps(
                {
                    "existed": True,
                    "priorType": "file",
                    "priorSha256": hashlib.sha256(prior).hexdigest(),
                    "priorMode": 0o644,
                    "managedSha256": hashlib.sha256(managed).hexdigest(),
                    "managedMode": 0o644,
                }
            )
        )

        with patch("thpm.service.ui.remove", return_value={"installed": False}):
            payload = Service(self.paths).uninstall()

        self.assertTrue(payload["ok"])
        self.assertEqual(target.read_bytes(), prior)
        self.assertFalse(state.exists())
        self.assertFalse(backup.exists())

    def test_uninstall_preserves_user_modified_historical_swaync_asset(self):
        managed = b"retired SwayNC theme\n"
        prior = b"user SwayNC theme\n"
        modified = b"later user edit\n"
        target = self.paths.config_home / "swaync/colors.css"
        target.parent.mkdir(parents=True)
        target.write_bytes(modified)
        state = self.paths.managed_asset_state_dir / "swaync.json"
        backup = self.paths.managed_asset_state_dir / "swaync.backup"
        state.parent.mkdir(parents=True)
        backup.write_bytes(prior)
        state.write_text(
            json.dumps(
                {
                    "existed": True,
                    "priorType": "file",
                    "priorSha256": hashlib.sha256(prior).hexdigest(),
                    "priorMode": 0o644,
                    "managedSha256": hashlib.sha256(managed).hexdigest(),
                    "managedMode": 0o644,
                }
            )
        )

        with patch("thpm.service.ui.remove", return_value={"installed": False}):
            payload = Service(self.paths).uninstall()

        self.assertTrue(payload["ok"])
        self.assertEqual(target.read_bytes(), modified)
        self.assertIn("preserved user-modified", str(payload["warnings"]))

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

    def test_retired_swaync_cannot_be_enabled(self):
        payload = Service(self.paths).set_enabled("swaync", True, refresh=False)
        self.assertFalse(payload["ok"])
        self.assertIn("unknown plugin: swaync", payload["summary"])

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
        source = self.paths.current_theme / "cliamp.toml"
        source.parent.mkdir(parents=True)
        source.write_text("# thpm:cliamp-use-native\ntheme")
        target = self.paths.config_home / "cliamp/themes/omarchy.toml"
        target.parent.mkdir(parents=True)
        target.write_text("user default")
        apply("cliamp", self.paths)
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            payload = Service(self.paths).set_enabled("cliamp", False, refresh=False)
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

    def test_fish_generated_output_lifecycle_is_safe_and_idempotent(self):
        assets = Path(__file__).parents[1] / "assets"
        source = self.paths.current_theme / "thpm-fish.fish"
        target = self.paths.config_home / "fish/conf.d/thpm-theme.fish"
        rendered = (
            "# Generated by Omarchy from a THPM-owned template.\n"
            'set -gx THPM_THEME_BG "#101820"\n'
            'set -gx THPM_THEME_FG "#d8e6e7"\n'
            'set -g fish_color_command "#668ca9"\n'
            'set -g fish_color_quote "#58ad73"\n'
            'set -g fish_color_error "#ed634c"\n'
            'set -g fish_color_selection "#e0f5f2" "--background=#42686f"\n'
            'set -g fish_pager_color_selected_background "--background=#42686f" "#e0f5f2"\n'
        )
        source.parent.mkdir(parents=True)
        target.parent.mkdir(parents=True)
        source.write_text(rendered)
        target.write_text("user baseline\n")

        changed = apply("fish", self.paths)
        metadata = target.stat()
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        unchanged = apply("fish", self.paths)

        self.assertEqual(changed.status, "applied")
        self.assertEqual(changed.restartRequired, [])
        self.assertEqual(target.read_text(), rendered)
        self.assertEqual(unchanged.status, "unchanged")
        self.assertEqual(unchanged.restartRequired, [])
        self.assertEqual(target.stat().st_ino, metadata.st_ino)
        self.assertEqual(target.stat().st_mtime_ns, metadata.st_mtime_ns)
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), digest)

        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            disabled = Service(self.paths).set_enabled("fish", False, refresh=False)
        self.assertTrue(disabled["ok"])
        self.assertEqual(target.read_text(), "user baseline\n")
        self.assertFalse(source.exists())

        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(rendered)
        apply("fish", self.paths)
        target.write_text("synthetic user modification\n")
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            preserved = Service(self.paths).set_enabled("fish", False, refresh=False)
        self.assertEqual(target.read_text(), "synthetic user modification\n")
        self.assertIn("preserved user-modified file", str(preserved["warnings"]))

        target.unlink()
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(rendered)
        apply("fish", self.paths)
        with patch("thpm.service.ui.remove", return_value={"installed": False}):
            uninstalled = Service(self.paths).uninstall()
        self.assertTrue(uninstalled["ok"])
        self.assertFalse(uninstalled["cleanupIncomplete"])
        self.assertFalse(target.exists())
        self.assertFalse(source.exists())

    def test_superfile_generated_output_lifecycle_is_safe_and_idempotent(self):
        assets = Path(__file__).parents[1] / "assets"
        source = self.paths.current_theme / "thpm-superfile.toml"
        target = self.paths.config_home / "superfile/theme/thpm.toml"
        rendered = (
            "# THPM Superfile v1.6 fixture\n"
            'code_syntax_highlight = "catppuccin-mocha"\n'
            'full_screen_fg = "#d8e6e7"\n'
            'full_screen_bg = "#101820"\n'
            'file_panel_border_active = "#668ca9"\n'
            'file_panel_item_selected_bg = "#42686f"\n'
            'sidebar_bg = "#0a1115"\n'
            'modal_border_active = "#668ca9"\n'
        )
        source.parent.mkdir(parents=True)
        target.parent.mkdir(parents=True)
        source.write_text(rendered)
        target.write_text("user baseline\n")

        changed = apply("superfile", self.paths)
        metadata = target.stat()
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        unchanged = apply("superfile", self.paths)

        self.assertEqual(changed.status, "applied")
        self.assertEqual(changed.restartRequired, [])
        self.assertEqual(target.read_text(), rendered)
        self.assertEqual(unchanged.status, "unchanged")
        self.assertEqual(unchanged.restartRequired, [])
        self.assertEqual(target.stat().st_ino, metadata.st_ino)
        self.assertEqual(target.stat().st_mtime_ns, metadata.st_mtime_ns)
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), digest)

        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            disabled = Service(self.paths).set_enabled(
                "superfile", False, refresh=False
            )
        self.assertTrue(disabled["ok"])
        self.assertEqual(target.read_text(), "user baseline\n")
        self.assertFalse(source.exists())

        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(rendered)
        apply("superfile", self.paths)
        target.write_text("synthetic user modification\n")
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            preserved = Service(self.paths).set_enabled(
                "superfile", False, refresh=False
            )
        self.assertEqual(target.read_text(), "synthetic user modification\n")
        self.assertIn("preserved user-modified file", str(preserved["warnings"]))

        target.unlink()
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(rendered)
        apply("superfile", self.paths)
        with patch("thpm.service.ui.remove", return_value={"installed": False}):
            uninstalled = Service(self.paths).uninstall()
        self.assertTrue(uninstalled["ok"])
        self.assertFalse(uninstalled["cleanupIncomplete"])
        self.assertFalse(target.exists())
        self.assertFalse(source.exists())

    def test_fzf_generated_output_lifecycle_is_safe_and_idempotent(self):
        assets = Path(__file__).parents[1] / "assets"
        source = self.paths.current_theme / "thpm-fzf.fish"
        target = self.paths.config_home / "fish/conf.d/thpm-fzf.fish"
        rendered = (
            "# Generated by Omarchy from a THPM-owned template.\n"
            'set -gx FZF_DEFAULT_OPTS "$FZF_DEFAULT_OPTS '
            "--color=bg:#101010,bg+:#202020,fg:#d0d0d0,fg+:#ffffff,"
            "hl:#4488cc,hl+:#66aaff,info:#44cccc,prompt:#cc88cc,"
            'pointer:#dd8844,marker:#66bb77,spinner:#ddbb55,header:#779999"\n'
        )
        source.parent.mkdir(parents=True)
        target.parent.mkdir(parents=True)
        source.write_text(rendered)
        target.write_text("user baseline\n")

        changed = apply("fzf", self.paths)
        metadata = target.stat()
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        unchanged = apply("fzf", self.paths)

        self.assertEqual(changed.status, "applied")
        self.assertEqual(changed.restartRequired, [])
        self.assertEqual(target.read_text(), rendered)
        self.assertEqual(unchanged.status, "unchanged")
        self.assertEqual(unchanged.restartRequired, [])
        self.assertEqual(target.stat().st_ino, metadata.st_ino)
        self.assertEqual(target.stat().st_mtime_ns, metadata.st_mtime_ns)
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), digest)

        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            disabled = Service(self.paths).set_enabled("fzf", False, refresh=False)
        self.assertTrue(disabled["ok"])
        self.assertEqual(target.read_text(), "user baseline\n")
        self.assertFalse(source.exists())

        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(rendered)
        apply("fzf", self.paths)
        target.write_text("synthetic user modification\n")
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            preserved = Service(self.paths).set_enabled("fzf", False, refresh=False)
        self.assertEqual(target.read_text(), "synthetic user modification\n")
        self.assertIn("preserved user-modified file", str(preserved["warnings"]))

        target.unlink()
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(rendered)
        apply("fzf", self.paths)
        with patch("thpm.service.ui.remove", return_value={"installed": False}):
            uninstalled = Service(self.paths).uninstall()
        self.assertTrue(uninstalled["ok"])
        self.assertFalse(uninstalled["cleanupIncomplete"])
        self.assertFalse(target.exists())
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
        self.assertEqual(
            self.paths.post_update_hook_file.read_bytes(),
            (assets / "hooks/90-thpm-ui").read_bytes(),
        )
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
        enabled = load(self.paths)
        enabled["fish"] = True
        save(self.paths, enabled)
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

    def test_doctor_warns_about_aether_gtk_override_without_theme_css(self):
        gtk = self.paths.config_home / "gtk-4.0/gtk.css"
        gtk.parent.mkdir(parents=True)
        gtk.write_text("/** Aether Theme with Sharp Corners */\nwindow { color: red; }\n")
        with patch("thpm.service.capabilities") as caps, patch(
            "thpm.service.load_palette", return_value=COLORS
        ):
            caps.return_value.available = True
            caps.return_value.routes = set()
            caps.return_value.missing = ()
            payload = Service(self.paths).doctor("gtk-css-compat")
        warnings = [
            item
            for item in payload["warnings"]
            if item.get("plugin") == "gtk-css-compat"
        ]
        self.assertEqual(len(warnings), 1)
        self.assertIn("Aether-generated", warnings[0]["message"])
        self.assertIn(str(gtk), warnings[0]["message"])

    def test_gtk_doctor_warns_about_legacy_libadwaita_setting(self):
        settings = self.paths.config_home / "gtk-4.0/settings.ini"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            "[Settings]\ngtk-application-prefer-dark-theme=true\n"
        )

        warnings = gtk_file_doctor_warnings(self.paths)

        self.assertEqual(len(warnings), 1)
        self.assertIn("unsupported by libadwaita", warnings[0])
        self.assertIn(str(settings), warnings[0])

    def test_gtk_doctor_reports_native_and_portal_drift(self):
        self.paths.current_theme.mkdir(parents=True)
        (self.paths.current_theme / "icons.theme").write_text("Yaru-olive\n")

        def command_value(command, **_kwargs):
            if "org.freedesktop.portal.Settings.Read" in command:
                return "(<<uint32 0>>,)", None
            return {
                "color-scheme": "'default'",
                "gtk-theme": "'Adwaita'",
                "icon-theme": "'Yaru-blue'",
            }[command[-1]], None

        with patch.dict(
            os.environ, {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/test-bus"}
        ), patch("thpm.compat.shutil.which", return_value="/usr/bin/tool"), patch(
            "thpm.compat._command_value", side_effect=command_value
        ):
            warnings = gtk_session_doctor_warnings(self.paths, "dark")

        self.assertEqual(len(warnings), 4)
        self.assertIn("GNOME color-scheme", warnings[0])
        self.assertIn("GNOME gtk-theme", warnings[1])
        self.assertIn("GNOME icon-theme", warnings[2])
        self.assertIn("portal color scheme is 0", warnings[3])

    def test_gtk_doctor_accepts_matching_native_and_portal_state(self):
        self.paths.current_theme.mkdir(parents=True)
        (self.paths.current_theme / "icons.theme").write_text("Yaru-olive\n")

        def command_value(command, **_kwargs):
            if "org.freedesktop.portal.Settings.Read" in command:
                return "(<<uint32 1>>,)", None
            return {
                "color-scheme": "'prefer-dark'",
                "gtk-theme": "'Adwaita-dark'",
                "icon-theme": "'Yaru-olive'",
            }[command[-1]], None

        with patch.dict(
            os.environ, {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/test-bus"}
        ), patch("thpm.compat.shutil.which", return_value="/usr/bin/tool"), patch(
            "thpm.compat._command_value", side_effect=command_value
        ):
            warnings = gtk_session_doctor_warnings(self.paths, "dark")

        self.assertEqual(warnings, [])

    def test_gtk_doctor_ignores_comments_and_unrelated_ini_sections(self):
        gtk = self.paths.config_home / "gtk-4.0/gtk.css"
        settings = gtk.with_name("settings.ini")
        gtk.parent.mkdir(parents=True)
        gtk.write_text("\ufeff/* Personal GTK notes only. */\n")
        settings.write_text(
            "[DEFAULT]\ngtk-application-prefer-dark-theme=true\n"
            "[Settings]\ngtk-font-name=Sans 10\n"
            "[Unrelated]\ngtk-application-prefer-dark-theme=true\n"
        )

        self.assertEqual(gtk_file_doctor_warnings(self.paths), [])

    def test_gtk_doctor_reports_probe_failures_and_malformed_portal_output(self):
        self.paths.current_theme.mkdir(parents=True)

        def command_value(command, **_kwargs):
            if "org.freedesktop.portal.Settings.Read" in command:
                return "unexpected", None
            return None, "timed out after 2 seconds"

        with patch.dict(
            os.environ, {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/test-bus"}
        ), patch("thpm.compat.shutil.which", return_value="/usr/bin/tool"), patch(
            "thpm.compat._command_value", side_effect=command_value
        ):
            warnings = gtk_session_doctor_warnings(self.paths, "dark")

        self.assertEqual(len(warnings), 4)
        self.assertTrue(all("cannot inspect" in warning for warning in warnings))
        self.assertIn("unexpected response", warnings[-1])

    def test_doctor_attributes_and_filters_gtk_diagnostics_by_owner(self):
        self.paths.canonical_palette_migration_marker.parent.mkdir(parents=True)
        self.paths.canonical_palette_migration_marker.write_text("complete\n")
        with patch("thpm.service.capabilities") as caps, patch(
            "thpm.service.load_palette", return_value=COLORS
        ), patch(
            "thpm.service.Paths.discover", return_value=self.paths
        ), patch(
            "thpm.service.gtk_file_doctor_warnings", return_value=["file drift"]
        ), patch(
            "thpm.service.gtk_session_doctor_warnings", return_value=["native drift"]
        ):
            caps.return_value.available = True
            caps.return_value.routes = set()
            caps.return_value.missing = ()
            full = Service(self.paths).doctor()
            gtk_only = Service(self.paths).doctor("gtk-css-compat")
            native_only = Service(self.paths).doctor("native-gnome")

        self.assertIn(
            {"plugin": "gtk-css-compat", "message": "file drift"},
            full["warnings"],
        )
        self.assertIn(
            {"plugin": "native-gnome", "message": "native drift"},
            full["warnings"],
        )
        self.assertEqual(
            gtk_only["warnings"],
            [{"plugin": "gtk-css-compat", "message": "file drift"}],
        )
        self.assertEqual(
            native_only["warnings"],
            [{"plugin": "native-gnome", "message": "native drift"}],
        )

    def test_disabling_inactive_discord_variant_keeps_active_shared_theme(self):
        source = self.paths.current_theme / "thpm-vencord.theme.css"
        source.parent.mkdir(parents=True)
        source.write_text("active discord theme")
        directory = self.paths.config_home / "Vencord/themes"
        directory.mkdir(parents=True)
        target = directory / "vencord.theme.css"
        enabled = load(self.paths)
        enabled["discord"] = True
        save(self.paths, enabled)
        apply("discord", self.paths)
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            payload = Service(self.paths).set_enabled(
                "discord-system24", False, refresh=False
            )
        self.assertTrue(payload["ok"])
        self.assertEqual(target.read_text(), "active discord theme")

    def test_discord_plugins_remain_mutually_exclusive(self):
        generated = self.paths.current_theme / "thpm-vencord.theme.css"
        generated.parent.mkdir(parents=True)
        generated.write_text("discord theme")
        (self.paths.config_home / "Vencord/themes").mkdir(parents=True)
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            Service(self.paths).set_enabled("discord", True, refresh=False)
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
        enabled = load(self.paths)
        enabled["gtk-css-compat"] = True
        save(self.paths, enabled)
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
        enabled = load(self.paths)
        enabled["fish"] = True
        save(self.paths, enabled)
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

    def test_run_theme_returns_the_hook_integration_report(self):
        hook_payload = {
            "ok": True,
            "themeName": "tokyo-night",
            "counts": {
                "applied": 1,
                "unchanged": 1,
                "skipped": 1,
                "failed": 0,
            },
            "results": [
                {"id": "fish", "status": "applied", "message": "updated", "changed": []},
                {"id": "fzf", "status": "unchanged", "message": "already current", "changed": []},
                {"id": "spotify", "status": "skipped", "message": "not installed", "changed": []},
            ],
            "changed": ["/tmp/fish-theme"],
            "actions": ["fish reload"],
            "warnings": [{"plugin": "spotify", "message": "not installed"}],
            "errors": [],
        }

        def refresh(*_args, **kwargs):
            self.assertEqual(kwargs["env"]["THPM_FORCE_RELOAD"], "1")
            Path(kwargs["env"]["THPM_HOOK_REPORT"]).write_text(json.dumps(hook_payload))
            return subprocess.CompletedProcess([], 0, "", "")

        with patch("thpm.service.run", side_effect=refresh):
            payload = Service(self.paths).run_theme()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["themeName"], "tokyo-night")
        self.assertEqual(payload["results"], hook_payload["results"])
        self.assertEqual(payload["counts"], hook_payload["counts"])
        self.assertEqual(payload["actions"], ["fish reload"])
        self.assertIn("1 applied, 1 unchanged, 1 skipped, 0 failed", payload["summary"])
        self.assertEqual(list(self.paths.runtime_dir.glob("thpm-hook-*.json")), [])
        self.assertEqual(list(self.paths.runtime_dir.glob("thpm-events-*.jsonl")), [])

    def test_run_theme_forwards_hook_events_before_refresh_returns(self):
        hook_payload = {
            "ok": True,
            "counts": {"applied": 0, "unchanged": 1, "skipped": 0, "failed": 0},
            "results": [],
            "errors": [],
        }
        observed: list[str] = []

        def refresh(*_args, **kwargs):
            kwargs["event_handler"](
                {"type": "integration_started", "plugin": "fish", "current": 1, "total": 1}
            )
            observed.append("refresh-returned")
            Path(kwargs["env"]["THPM_HOOK_REPORT"]).write_text(json.dumps(hook_payload))
            return subprocess.CompletedProcess([], 0, "", "")

        with patch("thpm.service.run", side_effect=refresh):
            payload = Service(
                self.paths, events=lambda event: observed.append(str(event["type"]))
            ).run_theme()

        self.assertTrue(payload["ok"])
        self.assertEqual(observed, ["integration_started", "refresh-returned"])

    def test_capabilities_accepts_command_groups_exposed_as_leaf_routes(self):
        routes = [
            "omarchy hook",
            "omarchy hook install",
            "omarchy theme refresh",
            "omarchy shell",
            "omarchy plugin add",
            "omarchy plugin list",
            "omarchy menu",
        ]
        completed = subprocess.CompletedProcess(
            [],
            0,
            json.dumps({"commands": [{"route": route} for route in routes]}),
            "",
        )
        with patch("thpm.omarchy.shutil.which", return_value="/usr/bin/omarchy"), patch(
            "thpm.omarchy.run", return_value=completed
        ):
            result = capabilities()
        self.assertTrue(result.available)
        self.assertEqual(result.missing, ())

    def test_shell_running_is_false_when_omarchy_is_missing(self):
        with patch("thpm.omarchy.run", side_effect=FileNotFoundError("omarchy")):
            self.assertFalse(shell_running())

    def test_omarchy_runner_consumes_events_while_process_is_running(self):
        bin_dir = self.paths.home / "bin"
        bin_dir.mkdir()
        fake_omarchy = bin_dir / "omarchy"
        fake_omarchy.write_text(
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' 'not-json' >>\"$THPM_HOOK_EVENTS\"\n"
            "printf '%s' '{\"type\":\"integration_' >>\"$THPM_HOOK_EVENTS\"\n"
            "sleep 0.1\n"
            "printf '%s\\n' 'started\",\"plugin\":\"fish\",\"current\":1,\"total\":1}' >>\"$THPM_HOOK_EVENTS\"\n"
            "sleep 0.1\n"
            ": >\"$THPM_TEST_DONE\"\n"
        )
        fake_omarchy.chmod(0o755)
        event_path = self.paths.home / "events.jsonl"
        event_path.touch()
        done_path = self.paths.home / "done"
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{bin_dir}:{environment['PATH']}",
                "THPM_HOOK_EVENTS": str(event_path),
                "THPM_TEST_DONE": str(done_path),
            }
        )
        process_was_running: list[bool] = []

        completed = run_omarchy(
            "theme",
            "refresh",
            env=environment,
            event_path=event_path,
            event_handler=lambda _event: process_was_running.append(
                not done_path.exists()
            ),
        )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(process_was_running, [True])

        done_path.unlink()
        event_path.write_text("")
        completed = run_omarchy(
            "theme",
            "refresh",
            env=environment,
            event_path=event_path,
            event_handler=lambda _event: (_ for _ in ()).throw(
                RuntimeError("presentation failed")
            ),
        )
        self.assertEqual(completed.returncode, 0)
        self.assertTrue(done_path.exists())

    def test_omarchy_runner_cleans_descendants_after_leader_exits(self):
        bin_dir = self.paths.home / "bin"
        bin_dir.mkdir()
        fake_omarchy = bin_dir / "omarchy"
        fake_omarchy.write_text(
            "#!/usr/bin/env bash\n"
            "( sleep 0.3; : >\"$THPM_TEST_CHILD_DONE\" ) &\n"
            "exit 0\n"
        )
        fake_omarchy.chmod(0o755)
        event_path = self.paths.home / "events.jsonl"
        event_path.touch()
        child_done = self.paths.home / "child-done"
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{bin_dir}:{environment['PATH']}",
                "THPM_TEST_CHILD_DONE": str(child_done),
            }
        )

        completed = run_omarchy(
            "theme",
            "refresh",
            env=environment,
            event_path=event_path,
            event_handler=lambda _event: None,
        )
        self.assertEqual(completed.returncode, 0)
        time.sleep(0.35)
        self.assertFalse(child_done.exists())

    def test_omarchy_runner_terminates_hook_descendants_on_timeout(self):
        bin_dir = self.paths.home / "bin"
        bin_dir.mkdir()
        fake_omarchy = bin_dir / "omarchy"
        fake_omarchy.write_text(
            "#!/usr/bin/env bash\n"
            "( sleep 0.3; : >\"$THPM_TEST_CHILD_DONE\" ) &\n"
            "sleep 5\n"
        )
        fake_omarchy.chmod(0o755)
        event_path = self.paths.home / "events.jsonl"
        event_path.touch()
        child_done = self.paths.home / "child-done"
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{bin_dir}:{environment['PATH']}",
                "THPM_TEST_CHILD_DONE": str(child_done),
            }
        )

        with self.assertRaises(subprocess.TimeoutExpired):
            run_omarchy(
                "theme",
                "refresh",
                timeout=0.1,
                env=environment,
                event_path=event_path,
                event_handler=lambda _event: None,
            )
        time.sleep(0.35)
        self.assertFalse(child_done.exists())

    def test_run_theme_keeps_verbose_fallback_after_partial_event_delivery(self):
        hook_payload = {
            "ok": True,
            "counts": {"applied": 0, "unchanged": 1, "skipped": 0, "failed": 0},
            "results": [
                {"id": "fish", "status": "unchanged", "message": "current", "changed": []}
            ],
            "errors": [],
        }

        def refresh(*_args, **kwargs):
            kwargs["event_handler"](
                {"type": "integrations_started", "total": 1}
            )
            Path(kwargs["env"]["THPM_HOOK_REPORT"]).write_text(json.dumps(hook_payload))
            return subprocess.CompletedProcess([], 0, "", "")

        with patch("thpm.service.run", side_effect=refresh):
            payload = Service(self.paths).run_theme()

        self.assertFalse(payload["progressReported"])
        output = io.StringIO()
        render(
            payload,
            verbose=True,
            console=Console(file=output, force_terminal=False, width=100),
        )
        self.assertIn("fish", output.getvalue())

    def test_run_theme_keeps_verbose_fallback_when_event_delivery_fails(self):
        hook_payload = {
            "ok": True,
            "counts": {"applied": 0, "unchanged": 1, "skipped": 0, "failed": 0},
            "results": [
                {"id": "fish", "status": "unchanged", "message": "current", "changed": []}
            ],
            "errors": [],
        }

        def refresh(*_args, **kwargs):
            kwargs["event_handler"](
                {
                    "type": "integration_finished",
                    "plugin": "fish",
                    "current": 1,
                    "total": 1,
                    "status": "unchanged",
                    "message": "current",
                }
            )
            Path(kwargs["env"]["THPM_HOOK_REPORT"]).write_text(json.dumps(hook_payload))
            return subprocess.CompletedProcess([], 0, "", "")

        def failed_delivery(_event):
            raise RuntimeError("presentation failed")

        with patch("thpm.service.run", side_effect=refresh):
            payload = Service(self.paths, events=failed_delivery).run_theme()

        self.assertFalse(payload["progressReported"])
        output = io.StringIO()
        render(
            payload,
            verbose=True,
            console=Console(file=output, force_terminal=False, width=100),
        )
        self.assertIn("fish", output.getvalue())

    def test_run_theme_normalizes_partial_or_invalid_counts(self):
        hook_payload = {
            "ok": True,
            "counts": {"applied": 1, "failed": "unknown"},
            "results": [],
            "errors": [],
        }

        def refresh(*_args, **kwargs):
            Path(kwargs["env"]["THPM_HOOK_REPORT"]).write_text(
                json.dumps(hook_payload)
            )
            return subprocess.CompletedProcess([], 0, "", "")

        with patch("thpm.service.run", side_effect=refresh):
            payload = Service(self.paths).run_theme()

        self.assertTrue(payload["ok"])
        self.assertEqual(
            payload["counts"],
            {"applied": 1, "unchanged": 0, "skipped": 0, "failed": 0},
        )

    def test_run_theme_fails_when_an_integration_fails(self):
        hook_payload = {
            "ok": False,
            "themeName": "tokyo-night",
            "counts": {"applied": 0, "unchanged": 0, "skipped": 0, "failed": 1},
            "results": [
                {"id": "swaync", "status": "failed", "message": "reload timed out", "changed": []}
            ],
            "changed": [],
            "warnings": [],
            "errors": [{"plugin": "swaync", "message": "reload timed out"}],
        }

        def refresh(*_args, **kwargs):
            Path(kwargs["env"]["THPM_HOOK_REPORT"]).write_text(json.dumps(hook_payload))
            return subprocess.CompletedProcess([], 0, "", "")

        with patch("thpm.service.run", side_effect=refresh):
            payload = Service(self.paths).run_theme()

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["results"][0]["status"], "failed")
        self.assertEqual(payload["errors"][0]["plugin"], "swaync")

    def test_theme_hook_uses_stderr_for_human_reports_and_file_for_json(self):
        hook = Path(__file__).parents[1] / "assets/hooks/90-thpm"
        bin_dir = self.paths.home / "bin"
        bin_dir.mkdir()
        fake_thpm = bin_dir / "thpm"
        fake_thpm.write_text(
            "#!/usr/bin/env bash\n"
            "if [[ $1 == --json ]]; then\n"
            "  printf '{\"ok\":true,\"results\":[]}'\n"
            "else\n"
            "  printf '%s\\n' \"$*\" >\"$THPM_TEST_ARGS\"\n"
            "  printf 'colored integration report\\n'\n"
            "fi\n"
        )
        fake_thpm.chmod(0o755)
        environment = os.environ.copy()
        environment["PATH"] = f"{bin_dir}:{environment['PATH']}"
        hook_args = self.paths.home / "hook-args"
        environment["THPM_TEST_ARGS"] = str(hook_args)

        human = subprocess.run(
            [str(hook), "tokyo-night"],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        self.assertEqual(human.returncode, 0)
        self.assertEqual(human.stdout, "")
        self.assertIn("colored integration report", human.stderr)
        self.assertEqual(hook_args.read_text().strip(), "hook-run theme-set tokyo-night")

        report_path = self.paths.home / "hook-report.json"
        environment["THPM_HOOK_REPORT"] = str(report_path)
        machine = subprocess.run(
            [str(hook), "tokyo-night"],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        self.assertEqual(machine.returncode, 0)
        self.assertEqual(machine.stdout, "")
        self.assertEqual(machine.stderr, "")
        self.assertEqual(json.loads(report_path.read_text()), {"ok": True, "results": []})


class PresentationTests(unittest.TestCase):
    def test_theme_hook_uses_the_same_live_run_surface(self):
        class Args:
            event = "theme-set"

        self.assertEqual(operation_name("hook-run", Args()), "run")

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

    def test_restart_requirements_are_named_in_human_output(self):
        output = io.StringIO()
        render(
            {
                "ok": True,
                "summary": "theme applied",
                "restartRequired": ["Spotify", "running GTK applications"],
                "warnings": [],
                "errors": [],
            },
            console=Console(file=output, force_terminal=False, width=100),
        )

        self.assertIn(
            "Restart needed: Spotify, running GTK applications",
            output.getvalue(),
        )

    def test_integration_outcomes_use_native_terminal_status_colors(self):
        output = io.StringIO()
        console = Console(
            file=output,
            force_terminal=True,
            color_system="standard",
            width=100,
        )
        render(
            {
                "ok": False,
                "operation": "run",
                "summary": "integration report",
                "results": [
                    {"status": "applied", "id": "fish", "message": "updated"},
                    {"status": "unchanged", "id": "fzf", "message": "current"},
                    {"status": "skipped", "id": "spotify", "message": "missing"},
                    {"status": "failed", "id": "swaync", "message": "timed out"},
                ],
                "warnings": [],
                "errors": [],
            },
            verbose=True,
            console=console,
        )
        text = output.getvalue()
        self.assertIn("\x1b[1;32mapplied", text)
        self.assertIn("\x1b[36munchanged", text)
        self.assertIn("\x1b[33mskipped", text)
        self.assertIn("\x1b[1;31mfailed", text)

    def test_verbose_activity_retains_reported_stage_history(self):
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
        self.assertGreater(text.count("\n"), 1)

    def test_activity_displays_zero_integrations_without_fabricated_work(self):
        output = io.StringIO()
        console = Console(
            file=output, force_terminal=True, color_system="standard", width=100
        )
        with Activity("run", console=console) as activity:
            activity.event({"type": "integrations_started", "total": 0})
            task = activity._progress.tasks[activity._task]
            self.assertEqual(task.total, 0)
            self.assertEqual(task.completed, 0)
        self.assertIn("0/0", output.getvalue())
        self.assertNotIn("1/1", output.getvalue())

    def test_activity_uses_live_integration_totals_and_current_plugin(self):
        output = io.StringIO()
        console = Console(
            file=output, force_terminal=True, color_system="standard", width=100
        )
        with Activity("run", console=console) as activity:
            activity.event({"type": "integrations_started", "total": 3})
            activity.event(
                {
                    "type": "integration_started",
                    "plugin": "fzf",
                    "current": 2,
                    "total": 3,
                }
            )
            task = activity._progress.tasks[activity._task]
            self.assertEqual(task.total, 3)
            self.assertEqual(task.completed, 1)
            self.assertIn("2/3 — fzf", task.description)
            activity.event(
                {
                    "type": "integration_finished",
                    "plugin": "fzf",
                    "current": 2,
                    "total": 3,
                    "status": "unchanged",
                    "message": "already current",
                }
            )
            self.assertEqual(task.completed, 2)
        text = output.getvalue()
        self.assertIn("├─", text)
        self.assertIn("fzf", text)
        self.assertIn("unchanged", text)
        self.assertNotIn("already current", text)

    def test_default_activity_retains_each_outcome_as_it_finishes(self):
        output = io.StringIO()
        console = Console(file=output, force_terminal=False, width=100)
        with Activity("run", console=console) as activity:
            activity.event({"type": "integrations_started", "total": 2})
            for current, plugin, status in (
                (1, "fish", "applied"),
                (2, "fzf", "unchanged"),
            ):
                activity.event(
                    {
                        "type": "integration_started",
                        "plugin": plugin,
                        "current": current,
                        "total": 2,
                    }
                )
                activity.event(
                    {
                        "type": "integration_finished",
                        "plugin": plugin,
                        "current": current,
                        "total": 2,
                        "status": status,
                        "message": "adapter detail",
                    }
                )
        text = output.getvalue()
        self.assertIn("├─ ✓ fish", text)
        self.assertIn("└─ • fzf", text)
        self.assertIn("applied", text)
        self.assertIn("unchanged", text)
        self.assertNotIn("adapter detail", text)

    def test_verbose_activity_adds_detail_to_retained_outcomes(self):
        output = io.StringIO()
        console = Console(file=output, force_terminal=False, width=100)
        with Activity("run", verbose=True, console=console) as activity:
            activity.event(
                {
                    "type": "integration_finished",
                    "plugin": "fish",
                    "current": 1,
                    "total": 1,
                    "status": "applied",
                    "message": "updated fish colors",
                }
            )
        self.assertIn("updated fish colors", output.getvalue())

    def test_default_result_is_compact_and_verbose_retains_table(self):
        payload = {
            "ok": True,
            "operation": "run",
            "summary": "refreshed theme: 1 applied, 1 unchanged",
            "results": [
                {"status": "applied", "id": "fish", "message": "updated"},
                {"status": "unchanged", "id": "fzf", "message": "current"},
            ],
            "warnings": [],
            "errors": [],
        }
        compact_output = io.StringIO()
        render(
            payload,
            console=Console(file=compact_output, force_terminal=False, width=100),
        )
        self.assertNotIn("Integration", compact_output.getvalue())
        self.assertNotIn("fish", compact_output.getvalue())

        verbose_output = io.StringIO()
        render(
            payload,
            verbose=True,
            console=Console(file=verbose_output, force_terminal=False, width=100),
        )
        self.assertIn("Integration", verbose_output.getvalue())
        self.assertIn("fish", verbose_output.getvalue())

        streamed_output = io.StringIO()
        render(
            {**payload, "progressReported": True},
            verbose=True,
            console=Console(file=streamed_output, force_terminal=False, width=100),
        )
        self.assertNotIn("Integration", streamed_output.getvalue())

    def test_quiet_activity_emits_no_progress(self):
        output = io.StringIO()
        console = Console(file=output, force_terminal=False, width=100)
        with Activity("run", quiet=True, console=console) as activity:
            activity.step("Rendering active theme")
            activity.event(
                {
                    "type": "integration_started",
                    "plugin": "fish",
                    "current": 1,
                    "total": 1,
                }
            )
        self.assertEqual(output.getvalue(), "")

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
    def _help_output(self, *arguments: str) -> str:
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            with self.assertRaisesRegex(SystemExit, "0"):
                main([*arguments, "--help"])
        return stdout.getvalue()

    def test_root_help_lists_every_command_with_descriptions(self):
        output = self._help_output()
        commands = (
            "list",
            "status",
            "native-status",
            "reconcile",
            "run",
            "install",
            "uninstall",
            "migrate",
            "version",
            "tui",
            "enable",
            "disable",
            "doctor",
            "report",
            "hook-run",
            "plugin",
            "ui",
            "config",
            "zed",
            "update",
        )
        for command in commands:
            self.assertRegex(output, rf"(?m)^    {re.escape(command)}\s+\S")
        self.assertIn("Run 'thpm COMMAND --help'", output)
        self.assertIn("thpm enable firefox", output)
        self.assertIn("--json", output)
        self.assertIn("machine-readable JSON", output)

    def test_nested_help_lists_available_actions(self):
        expected_actions = {
            "ui": ("state", "install", "sync", "remove", "status", "open", "surface"),
            "config": ("restart-policy",),
            "zed": ("status", "setup"),
            "update": ("check", "status", "apply"),
        }
        for command, actions in expected_actions.items():
            with self.subTest(command=command):
                output = self._help_output(command)
                for action in actions:
                    self.assertRegex(output, rf"(?m)^    {re.escape(action)}\s+\S")

    def test_command_help_explains_arguments_and_flags(self):
        enable_help = self._help_output("enable")
        self.assertIn("INTEGRATION", enable_help)
        self.assertIn("confirm sensitive enablement", enable_help)
        disable_help = self._help_output("disable")
        self.assertNotIn("--yes", disable_help)
        reconcile_help = self._help_output("reconcile")
        self.assertIn("--refresh", reconcile_help)
        self.assertIn("reapply the active theme", reconcile_help)
        report_help = self._help_output("report")
        self.assertIn("--output PATH", report_help)
        self.assertIn("redacted diagnostic report", report_help)

    def test_reviewed_help_claims_match_command_behavior(self):
        install_help = self._help_output("install")
        self.assertIn("check installation prerequisites", install_help)
        update_status_help = self._help_output("update", "status")
        self.assertIn("reusing a recent cached result", update_status_help)
        update_apply_help = self._help_output("update", "apply")
        self.assertIn("configured installation source", update_apply_help)
        ui_open_help = self._help_output("ui", "open")
        self.assertIn("interactive calls fall back to the TUI", ui_open_help)
        uninstall_help = self._help_output("uninstall")
        self.assertIn("THPM-managed", uninstall_help)

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

    def test_human_output_is_compact_by_default(self):
        response = {"ok": True, "summary": "THPM is current", "errors": []}
        with patch("thpm.cli.Service") as service_type, patch("thpm.cli.render") as render_output:
            service_type.return_value.update_apply.return_value = response
            exit_code = main(["update"])
        self.assertEqual(exit_code, 0)
        render_output.assert_called_once_with(response, verbose=False)

    def test_verbose_opts_into_detailed_human_output(self):
        response = {"ok": True, "summary": "THPM is current", "errors": []}
        with patch("thpm.cli.Service") as service_type, patch("thpm.cli.render") as render_output:
            service_type.return_value.update_apply.return_value = response
            exit_code = main(["update", "--verbose"])
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
        service_type.return_value.update_apply.assert_called_once_with(
            update_mode="deny"
        )
        service_type.return_value.update_check.assert_not_called()
        self.assertEqual(json.loads(stdout.getvalue()), response)

    def test_json_gui_update_can_request_terminal_handoff(self):
        response = {"ok": True, "summary": "package update terminal opened"}
        with patch("thpm.cli.Service") as service_type, patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            service_type.return_value.update_apply.return_value = response
            exit_code = main(["update", "apply", "--terminal", "--json"])
        self.assertEqual(exit_code, 0)
        service_type.return_value.update_apply.assert_called_once_with(
            update_mode="handoff"
        )
        self.assertEqual(json.loads(stdout.getvalue()), response)

    def test_json_inline_flag_cannot_bypass_noninteractive_update_policy(self):
        response = {"ok": False, "summary": "terminal required"}
        with patch("thpm.cli.Service") as service_type, patch(
            "sys.stdout", new_callable=io.StringIO
        ):
            service_type.return_value.update_apply.return_value = response
            exit_code = main(["update", "apply", "--inline", "--json"])
        self.assertEqual(exit_code, 1)
        service_type.return_value.update_apply.assert_called_once_with(
            update_mode="deny"
        )

    def test_human_cli_without_tty_uses_terminal_handoff(self):
        response = {"ok": True, "summary": "THPM updated", "errors": []}
        with patch("thpm.cli.Service") as service_type, patch(
            "thpm.cli.sys.stdin.isatty", return_value=False
        ), patch("thpm.cli.render"):
            service_type.return_value.update_apply.return_value = response
            exit_code = main(["update"])
        self.assertEqual(exit_code, 0)
        service_type.return_value.update_apply.assert_called_once_with(
            update_mode="handoff"
        )

    def test_terminal_worker_writes_private_machine_readable_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = Paths(
                root,
                root / "config",
                root / "data",
                root / "state",
                root / "run",
            )
            paths.runtime_dir.mkdir(parents=True)
            result_file = paths.runtime_dir / "thpm-update-result-test.json"
            payload = {"ok": True, "result": {"status": "updated"}}
            with patch.dict(
                os.environ, {"THPM_UPDATE_RESULT_FILE": str(result_file)}
            ):
                _write_update_handoff_result(paths, payload)
            self.assertEqual(json.loads(result_file.read_text()), payload)
            self.assertEqual(result_file.stat().st_mode & 0o777, 0o600)

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

    def test_config_restart_policy_is_available_to_cli_and_json_callers(self):
        response = {
            "ok": True,
            "summary": "Application restart policy: notify",
            "preferences": {"restartPolicy": "notify"},
        }
        with patch("thpm.cli.Service") as service_type, patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            service_type.return_value.restart_policy.return_value = response
            exit_code = main(
                ["--json", "config", "restart-policy", "notify"]
            )

        self.assertEqual(exit_code, 0)
        service_type.return_value.restart_policy.assert_called_once_with("notify")
        self.assertEqual(json.loads(stdout.getvalue()), response)

    def test_bare_config_reports_preferences_without_mutating(self):
        response = {
            "ok": True,
            "summary": "Application restart policy: automatic",
        }
        with patch("thpm.cli.Service") as service_type, patch(
            "thpm.cli.render"
        ) as render_output:
            service_type.return_value.preferences.return_value = response
            exit_code = main(["config"])

        self.assertEqual(exit_code, 0)
        service_type.return_value.preferences.assert_called_once_with()
        render_output.assert_called_once_with(response, verbose=False)

    def test_hook_command_forwards_event_and_all_arguments(self):
        response = {"ok": True, "summary": "applied theme tokyo-night"}
        with patch("thpm.cli.Service") as service_type, patch("sys.stdout", new_callable=io.StringIO) as stdout:
            service_type.return_value.hook_run.return_value = response
            exit_code = main(["--json", "hook-run", "theme-set", "tokyo-night", "dark"])
        self.assertEqual(exit_code, 0)
        service_type.return_value.hook_run.assert_called_once_with("theme-set", ["tokyo-night", "dark"])
        self.assertEqual(json.loads(stdout.getvalue()), response)

    def test_hook_command_writes_private_jsonl_events(self):
        response = {"ok": True, "summary": "applied active theme"}
        with tempfile.TemporaryDirectory() as root:
            event_path = Path(root) / "events.jsonl"
            with patch.dict(os.environ, {"THPM_HOOK_EVENTS": str(event_path)}), patch(
                "thpm.cli.Service"
            ) as service_type, patch("sys.stdout", new_callable=io.StringIO):
                service_type.return_value.hook_run.return_value = response
                self.assertEqual(main(["--json", "hook-run", "theme-set"]), 0)
                event_writer = service_type.call_args.kwargs["events"]
                event_writer(
                    {
                        "type": "integration_started",
                        "plugin": "fish",
                        "current": 1,
                        "total": 1,
                    }
                )
            self.assertEqual(
                json.loads(event_path.read_text()),
                {
                    "type": "integration_started",
                    "plugin": "fish",
                    "current": 1,
                    "total": 1,
                },
            )

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

    def test_json_ui_open_uses_verified_launcher_without_visual_fallback(self):
        result = {"opened": True, "surface": "gui", "synchronized": False}
        with patch("thpm.cli.ui.open_manager", return_value=result) as open_manager, patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            exit_code = main(["--json", "ui", "open"])
        self.assertEqual(exit_code, 0)
        open_manager.assert_called_once()
        self.assertFalse(open_manager.call_args.kwargs["fallback"])
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"], result)

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
        self.update_apply_modes: list[str] = []
        self.menu_surface = "gui"
        self.surface_calls: list[str] = []
        self.restart_policy_value = "automatic"
        self.restart_policy_calls: list[str] = []

    def state(self):
        return {"ok": True, "menuSurface": self.menu_surface, "preferences": {"restartPolicy": self.restart_policy_value}, "counts": {"enabled": 1, "disabled": 0, "native": 1, "unavailable": 0, "attention": 0}, "plugins": [
            {"id": "fish", "label": "Fish", "category": "Terminal", "description": "Synchronize Fish colors.", "ownership": "thpm", "enabled": True, "available": True, "warnings": [], "supportStatus": "experimental"},
            {"id": "native-foot", "label": "Foot live colors", "category": "Native", "description": "Owned by Omarchy.", "ownership": "native", "enabled": True, "available": True, "warnings": [], "supportStatus": "native"},
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

    def update_apply(self, *, update_mode="inline"):
        self.update_apply_calls += 1
        self.update_apply_modes.append(update_mode)
        return {"ok": True, "result": {"status": "updated", "currentVersion": "1.0.0rc1", "availableVersion": "1.1.0"}}

    def ui_surface(self, requested=None):
        if requested is not None:
            self.menu_surface = requested
            self.surface_calls.append(requested)
        return {"ok": True, "result": {"surface": self.menu_surface, "changed": requested is not None}}

    def restart_policy(self, requested=None):
        if requested is not None:
            self.restart_policy_value = requested
            self.restart_policy_calls.append(requested)
        return {"ok": True, "preferences": {"restartPolicy": self.restart_policy_value}}


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
                labels = [str(label.render()) for label in app.query("PluginRow .plugin-label")]
                self.assertIn("Fish · Experimental", labels)
                self.assertIn("Foot live colors", labels)
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
            async with app.run_test(size=(120, 52)) as pilot:
                for _attempt in range(20):
                    await pilot.pause(0.05)
                    if app.update_info.get("status") == "available":
                        break
                self.assertEqual(app.update_info.get("status"), "available")
                await pilot.press("4")
                await pilot.click("#update-action")
                await pilot.pause()
                self.assertEqual(service.update_apply_calls, 0)
                await pilot.click("#confirm-update")
                await pilot.pause(0.2)
                self.assertEqual(service.update_apply_calls, 1)
                self.assertEqual(service.update_apply_modes, ["handoff"])
                self.assertTrue(app.query_one("#restart-shell").display)
        asyncio.run(exercise())

    def test_committed_partial_update_shows_tui_recovery_actions(self):
        async def exercise():
            service = FakeTuiService()
            service.update_available = True

            def partial_update(*, update_mode="inline"):
                service.update_apply_calls += 1
                service.update_apply_modes.append(update_mode)
                return {
                    "ok": False,
                    "summary": "THPM update committed; run thpm ui install",
                    "result": {
                        "status": "updated",
                        "currentVersion": "1.0.0rc1",
                        "availableVersion": "1.1.0",
                        "refreshRequired": False,
                        "uiRefreshRequired": True,
                    },
                }

            service.update_apply = partial_update
            app = ThpmTui(service, self.paths)
            async with app.run_test(size=(120, 52)) as pilot:
                for _attempt in range(20):
                    await pilot.pause(0.05)
                    if app.update_info.get("status") == "available":
                        break
                await pilot.press("4")
                await pilot.click("#update-action")
                await pilot.click("#confirm-update")
                await pilot.pause(0.2)
                self.assertEqual(service.update_apply_modes, ["handoff"])
                self.assertTrue(app.query_one("#restart-shell").display)
                self.assertIn(
                    "thpm ui install",
                    str(app.query_one("#update-message").render()),
                )

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

    def test_system_restart_policy_toggle_uses_shared_service(self):
        async def exercise():
            service = FakeTuiService()
            app = ThpmTui(service, self.paths)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause(0.2)
                await pilot.press("4")
                restart_switch = app.query_one("#restart-policy-switch")
                self.assertTrue(restart_switch.value)
                await pilot.click("#restart-policy-switch")
                await pilot.pause(0.2)
                self.assertEqual(service.restart_policy_calls, ["notify"])
                self.assertFalse(restart_switch.value)
                self.assertIn(
                    "notify", str(app.query_one("#restart-policy-message").render())
                )
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
        self.assertFalse(load(self.paths)["zed-extra"])
        backup = self.paths.zed_settings_backup_file.read_text()
        configure_settings(self.paths)
        self.assertEqual(self.paths.zed_settings_backup_file.read_text(), backup)

    def test_setup_preserves_an_existing_enabled_state(self):
        self.write_zed()
        enabled = load(self.paths)
        enabled["zed-extra"] = True
        save(self.paths, enabled)

        result = Service(self.paths).zed_setup(confirmed=True)

        self.assertTrue(result["ok"])
        self.assertTrue(load(self.paths)["zed-extra"])

    def test_setup_preserves_state_changed_before_mutation_lock(self):
        self.write_zed()

        @contextmanager
        def changed_before_acquire(_paths):
            enabled = load(self.paths)
            enabled["zed-extra"] = True
            save(self.paths, enabled)
            yield

        with patch("thpm.service.mutation_lock", changed_before_acquire):
            result = Service(self.paths).zed_setup(confirmed=True)

        self.assertTrue(result["ok"])
        self.assertTrue(load(self.paths)["zed-extra"])

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


class CavaTests(Sandbox):
    def write_cava_process(
        self,
        proc_root: Path,
        pid: int,
        *,
        config: Path | None = None,
        environment: bool = True,
        relative: bool = False,
    ) -> None:
        pid_root = proc_root / str(pid)
        pid_root.mkdir(parents=True)
        executable = self.paths.home / "bin/cava"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.touch(exist_ok=True)
        (pid_root / "exe").symlink_to(executable)
        arguments = ["cava"]
        if config is not None:
            argument = config.name if relative else str(config)
            arguments.extend(("-p", argument))
            (pid_root / "cwd").symlink_to(config.parent)
        (pid_root / "cmdline").write_bytes(b"\0".join(item.encode() for item in arguments) + b"\0")
        if environment:
            (pid_root / "environ").write_bytes(
                f"HOME={self.paths.home}\0XDG_CONFIG_HOME={self.paths.config_home}\0".encode()
            )
        (pid_root / "stat").write_text(
            f"{pid} (cava) S " + " ".join(["0"] * 18 + [str(pid * 10)]) + "\n"
        )

    def test_selector_edit_preserves_formatting_and_rejects_duplicates(self):
        original = "[general]\r\nframerate = 60\r\n\r\n[color]\r\n  theme = \"omarchy\" ; keep\r\nforeground = '#fff'\r\n"
        updated, state = set_cava_selector(original)
        self.assertIn('  theme = "thpm" ; keep\r\n', updated)
        self.assertIn("framerate = 60\r\n", updated)
        restored, changed = restore_cava_selector_text(updated, state)
        self.assertTrue(changed)
        self.assertEqual(restored, original)
        with self.assertRaisesRegex(CavaError, "duplicate theme"):
            parse_cava_selector("[color]\ntheme=one\ntheme=two\n")

    def test_selector_parser_accepts_comment_markers_inside_quotes(self):
        for marker in ("#", ";"):
            with self.subTest(marker=marker):
                original = f'[color]\ntheme = "user{marker}theme" ; keep\n'
                selector = parse_cava_selector(original)
                self.assertEqual(selector.value, f"user{marker}theme")
                updated, state = set_cava_selector(original)
                self.assertEqual(updated, '[color]\ntheme = "thpm" ; keep\n')
                restored, changed = restore_cava_selector_text(updated, state)
                self.assertTrue(changed)
                self.assertEqual(restored, original)

    def test_selector_parser_refuses_malformed_configuration(self):
        malformed = (
            "[color]\ntheme = 'unterminated\n",
            "[color]\ntheme = 'valid' garbage\n",
            "[color]\ntheme == other\n",
            "[color]\ntheme other\n",
            "[color\ntheme = other\n",
        )
        for content in malformed:
            with self.subTest(content=content):
                with self.assertRaises(CavaError):
                    parse_cava_selector(content)
                with self.assertRaises(CavaError):
                    set_cava_selector(content)

    def test_selector_insertion_restores_exact_formatting(self):
        for original in (
            "[general]\nx=1\n\n\n",
            "[color]\nforeground=white",
            "[general]\nx=1",
        ):
            with self.subTest(original=original):
                updated, state = set_cava_selector(original)
                restored, changed = restore_cava_selector_text(updated, state)
                self.assertTrue(changed)
                self.assertEqual(restored, original)

    def test_created_color_section_preserves_later_user_comments(self):
        updated, state = set_cava_selector("[general]\nx=1\n")
        updated = updated.replace("theme = 'thpm'\n", "theme = 'thpm'\n# user note\n")
        restored, changed = restore_cava_selector_text(updated, state)
        self.assertTrue(changed)
        self.assertIn("[color]", restored)
        self.assertIn("# user note", restored)
        self.assertNotIn("theme = 'thpm'", restored)

    def test_selector_state_preserves_symlink_and_unrelated_later_edits(self):
        authored = self.paths.home / "dotfiles/cava/config"
        authored.parent.mkdir(parents=True)
        authored.write_text("[general]\nframerate = 30\n[color]\ntheme = 'omarchy'\n")
        config = self.paths.config_home / "cava/config"
        config.parent.mkdir(parents=True)
        config.symlink_to(authored)

        changed = configure_cava_selector(self.paths)
        self.assertEqual(changed, [str(config)])
        self.assertTrue(config.is_symlink())
        self.assertEqual(parse_cava_selector(authored.read_text()).value, "thpm")
        authored.write_text(authored.read_text() + "\n[input]\nmethod = pipewire\n")

        restored, warnings = restore_cava_selector(self.paths)
        self.assertEqual(restored, [str(config)])
        self.assertEqual(warnings, [])
        self.assertTrue(config.is_symlink())
        self.assertEqual(parse_cava_selector(authored.read_text()).value, "omarchy")
        self.assertIn("method = pipewire", authored.read_text())

    def test_repair_refreshes_restoration_state_after_user_changes_selection(self):
        config = self.paths.config_home / "cava/config"
        config.parent.mkdir(parents=True)
        config.write_text("[color]\ntheme = 'omarchy'\n")
        configure_cava_selector(self.paths)
        config.write_text("[color]\ntheme = 'user-new'\n")

        configure_cava_selector(self.paths)
        restored, warnings = restore_cava_selector(self.paths)

        self.assertEqual(warnings, [])
        self.assertEqual(restored, [str(config)])
        self.assertEqual(parse_cava_selector(config.read_text()).value, "user-new")

    def test_malformed_selector_state_is_refused_without_mutating_config(self):
        config = self.paths.config_home / "cava/config"
        config.parent.mkdir(parents=True)
        config.write_text("[color]\ntheme = 'omarchy'\n")
        state = self.paths.managed_asset_state_dir / "cava-selection.json"
        state.parent.mkdir(parents=True)
        state.write_text("[]\n")
        before = config.read_bytes()

        with self.assertRaises(CavaError):
            configure_cava_selector(self.paths)
        self.assertEqual(config.read_bytes(), before)
        _changed, warnings = restore_cava_selector(self.paths)
        self.assertIn("JSON object", warnings[0])

    def test_selector_state_rejects_multiline_and_impossible_combinations(self):
        updated, valid = set_cava_selector("[color]\ntheme = 'omarchy'\n")
        invalid_states = []
        multiline = dict(valid)
        multiline["previousLine"] = "theme = 'omarchy'\ntheme = 'attacker'\n"
        invalid_states.append(multiline)
        same_selection = dict(valid)
        same_selection["previousLine"] = "theme = 'thpm'\n"
        invalid_states.append(same_selection)
        contradictory = dict(valid)
        contradictory["createdColorSection"] = True
        contradictory["createdBlock"] = "[color]\ntheme = 'thpm'\n"
        invalid_states.append(contradictory)
        missing_insert = dict(set_cava_selector("[color]\nforeground=white\n")[1])
        missing_insert["insertedLine"] = ""
        invalid_states.append(missing_insert)

        for state in invalid_states:
            with self.subTest(state=state):
                with self.assertRaises(CavaError):
                    restore_cava_selector_text(updated, state)

    def test_version_boundary_and_diagnostics_find_unselected_target(self):
        self.assertEqual(parse_cava_version("cava 0.10.7"), (0, 10, 7))
        source = self.paths.current_theme / "thpm-cava.ini"
        target = self.paths.config_home / "cava/themes/thpm"
        config = self.paths.config_home / "cava/config"
        source.parent.mkdir(parents=True)
        target.parent.mkdir(parents=True)
        source.write_text("[color]\ngradient = 1\n")
        target.write_text(source.read_text())
        config.write_text("[color]\ntheme = 'omarchy'\n")

        result = diagnose_cava(
            self.paths,
            command_path="/usr/bin/cava",
            version=(0, 10, 7),
            proc_root=self.paths.home / "empty-proc",
        )

        selector = next(check for check in result["checks"] if check["id"] == "cava.selector")
        self.assertEqual(result["health"], "broken")
        self.assertEqual(selector["status"], "error")
        self.assertEqual(selector["repair"]["command"], "thpm doctor cava --fix")

    def test_process_discovery_resolves_relative_custom_config_and_signals_only_confirmed(self):
        proc_root = self.paths.home / "proc"
        config = self.paths.home / "profiles/cava.ini"
        config.parent.mkdir(parents=True)
        config.write_text("[color]\ntheme = 'thpm'\n")
        target = self.paths.config_home / "cava/themes/thpm"
        target.parent.mkdir(parents=True)
        target.write_text("theme\n")
        self.write_cava_process(proc_root, 321, config=config, relative=True)
        processes = discover_cava_processes(self.paths, proc_root)
        self.assertEqual(processes[0].config_path, str(config))
        self.assertEqual(processes[0].confidence, "confirmed")
        killed: list[tuple[int, int]] = []

        actions, restart_required, warnings = reload_cava_processes(
            self.paths,
            proc_root=proc_root,
            kill=lambda pid, sig: killed.append((pid, sig)),
        )

        self.assertEqual(killed, [(321, signal.SIGUSR1)])
        self.assertEqual(restart_required, [])
        self.assertEqual(warnings, [])
        self.assertIn("PID 321", actions[0])

    def test_process_discovery_confirms_default_and_absolute_custom_configs(self):
        proc_root = self.paths.home / "proc"
        default = self.paths.config_home / "cava/config"
        custom = self.paths.home / "profiles/absolute.ini"
        default.parent.mkdir(parents=True)
        custom.parent.mkdir(parents=True)
        default.write_text("[color]\ntheme='thpm'\n")
        custom.write_text("[color]\ntheme='thpm'\n")
        self.write_cava_process(proc_root, 101)
        self.write_cava_process(proc_root, 102, config=custom)

        processes = discover_cava_processes(self.paths, proc_root)

        self.assertEqual(processes[0].config_path, str(default))
        self.assertFalse(processes[0].custom_config)
        self.assertEqual(processes[1].config_path, str(custom))
        self.assertTrue(processes[1].custom_config)
        self.assertTrue(all(item.confidence == "confirmed" for item in processes))

    def test_mixed_processes_signal_only_confirmed_consumers(self):
        proc_root = self.paths.home / "proc"
        default = self.paths.config_home / "cava/config"
        other = self.paths.home / "profiles/other.ini"
        default.parent.mkdir(parents=True)
        other.parent.mkdir(parents=True)
        default.write_text("[color]\ntheme='thpm'\n")
        other.write_text("[color]\ntheme='other'\n")
        target = self.paths.config_home / "cava/themes/thpm"
        target.parent.mkdir(parents=True)
        target.write_text("theme\n")
        self.write_cava_process(proc_root, 201)
        self.write_cava_process(proc_root, 202, config=other)
        killed: list[tuple[int, int]] = []

        actions, restart_required, warnings = reload_cava_processes(
            self.paths,
            proc_root=proc_root,
            kill=lambda pid, sig: killed.append((pid, sig)),
        )

        self.assertEqual(killed, [(201, signal.SIGUSR1)])
        self.assertEqual(len(actions), 1)
        self.assertEqual(restart_required, ["Cava"])
        self.assertIn("does not use", warnings[0])

    def test_pidfd_is_opened_before_identity_revalidation_and_always_closed(self):
        proc_root = self.paths.home / "proc"
        config = self.paths.config_home / "cava/config"
        config.parent.mkdir(parents=True)
        config.write_text("[color]\ntheme='thpm'\n")
        target = self.paths.config_home / "cava/themes/thpm"
        target.parent.mkdir(parents=True)
        target.write_text("theme\n")
        self.write_cava_process(proc_root, 275)
        read_fd, write_fd = os.pipe()
        signals: list[tuple[int, int]] = []

        def acquire_after_reuse(pid: int) -> int:
            (proc_root / str(pid) / "stat").write_text(
                f"{pid} (cava) S " + " ".join(["0"] * 18 + ["changed"]) + "\n"
            )
            return read_fd

        try:
            actions, restart_required, warnings = reload_cava_processes(
                self.paths,
                proc_root=proc_root,
                pidfd_open=acquire_after_reuse,
                pidfd_signal=lambda fd, sig: signals.append((fd, sig)),
            )
            self.assertEqual(actions, [])
            self.assertEqual(signals, [])
            self.assertEqual(restart_required, ["Cava"])
            self.assertIn("restart it", warnings[0])
            with self.assertRaises(OSError):
                os.fstat(read_fd)
        finally:
            os.close(write_fd)

    def test_signal_failure_and_start_time_change_require_restart(self):
        proc_root = self.paths.home / "proc"
        config = self.paths.config_home / "cava/config"
        config.parent.mkdir(parents=True)
        config.write_text("[color]\ntheme='thpm'\n")
        target = self.paths.config_home / "cava/themes/thpm"
        target.parent.mkdir(parents=True)
        target.write_text("theme\n")
        self.write_cava_process(proc_root, 301)

        _actions, restart_required, warnings = reload_cava_processes(
            self.paths,
            proc_root=proc_root,
            kill=lambda _pid, _sig: (_ for _ in ()).throw(ProcessLookupError()),
        )

        self.assertEqual(restart_required, ["Cava"])
        self.assertIn("restart it", warnings[0])

    def test_diagnostics_report_running_custom_config_that_does_not_select_thpm(self):
        proc_root = self.paths.home / "proc"
        custom = self.paths.home / "profiles/cava.ini"
        custom.parent.mkdir(parents=True)
        custom.write_text("[color]\ntheme = 'other'\n")
        source = self.paths.current_theme / "cava_theme"
        target = self.paths.config_home / "cava/themes/thpm"
        source.parent.mkdir(parents=True)
        target.parent.mkdir(parents=True)
        source.write_text("theme\n")
        target.write_text("theme\n")
        config = self.paths.config_home / "cava/config"
        config.write_text("[color]\ntheme = 'thpm'\n")
        state = self.paths.managed_asset_state_dir / "generated-cava.json"
        state.parent.mkdir(parents=True)
        digest = hashlib.sha256(b"theme\n").hexdigest()
        state.write_text(json.dumps({"managedSha256": digest, "managedMode": 0o644}))
        self.write_cava_process(proc_root, 333, config=custom)

        result = diagnose_cava(
            self.paths,
            command_path="/usr/bin/cava",
            version=(0, 10, 7),
            proc_root=proc_root,
        )

        runtime = next(check for check in result["checks"] if check["id"] == "cava.runtime-selection")
        self.assertEqual(runtime["status"], "error")
        self.assertEqual(runtime["evidence"]["instances"][0]["pid"], 333)

    def test_unknown_process_is_never_signalled(self):
        proc_root = self.paths.home / "proc"
        config = self.paths.config_home / "cava/config"
        config.parent.mkdir(parents=True)
        config.write_text("[color]\ntheme = 'thpm'\n")
        target = self.paths.config_home / "cava/themes/thpm"
        target.parent.mkdir(parents=True)
        target.write_text("theme\n")
        self.write_cava_process(proc_root, 444, environment=False)
        killed: list[tuple[int, int]] = []

        _actions, restart_required, warnings = reload_cava_processes(
            self.paths,
            proc_root=proc_root,
            kill=lambda pid, sig: killed.append((pid, sig)),
        )

        self.assertEqual(killed, [])
        self.assertEqual(restart_required, ["Cava"])
        self.assertIn("unknown config", warnings[0])

    def test_broken_cava_apply_fails_without_installing_target(self):
        source = self.paths.current_theme / "cava_theme"
        config = self.paths.config_home / "cava/config"
        source.parent.mkdir(parents=True)
        config.parent.mkdir(parents=True)
        source.write_text("[color]\ngradient=1\n")
        config.write_text("[color]\ntheme='other'\n")
        target = self.paths.config_home / "cava/themes/thpm"

        with patch("thpm.integrations.shutil.which", return_value="/usr/bin/cava"), patch(
            "thpm.integrations.installed_cava_version", return_value=(0, 10, 7)
        ):
            result = apply("cava", self.paths)

        self.assertEqual(result.status, "failed")
        self.assertFalse(target.exists())

    def test_enabled_cava_prerequisite_failure_is_a_hook_error(self):
        with patch(
            "thpm.integrations.inspect_readiness",
            return_value=(False, ["Cava 0.10.6 or newer"], []),
        ):
            payload = apply_enabled(self.paths, {"cava": True})
        self.assertEqual(payload["results"][0]["status"], "failed")
        self.assertEqual(payload["counts"]["failed"], 1)
        self.assertEqual(payload["errors"][0]["plugin"], "cava")

    def test_doctor_is_read_only_and_returns_stable_cava_checks(self):
        self.write_palette()
        source = self.paths.current_theme / "thpm-cava.ini"
        source.write_text("[color]\ngradient = 1\n")
        config = self.paths.config_home / "cava/config"
        config.parent.mkdir(parents=True)
        config.write_text("[color]\ntheme = 'omarchy'\n")
        before = config.read_bytes()
        enabled = load(self.paths)
        enabled["cava"] = True
        save(self.paths, enabled)
        complete_cava_opt_in(self.paths)
        with patch("thpm.service.capabilities") as caps, patch(
            "thpm.service.load_palette", return_value=COLORS
        ), patch("thpm.service.shutil.which", return_value="/usr/bin/cava"), patch(
            "thpm.snapshot.shutil.which", return_value="/usr/bin/cava"
        ), patch("thpm.cava.installed_version", return_value=(0, 10, 7)):
            caps.return_value.available = True
            caps.return_value.routes = set()
            caps.return_value.missing = ()
            result = Service(self.paths).doctor("cava")
            confirmation = Service(self.paths).doctor("cava", fix=True)
        self.assertFalse(result["ok"])
        self.assertEqual(config.read_bytes(), before)
        self.assertTrue(confirmation["confirmationRequired"])
        self.assertTrue(confirmation["repairPlan"])
        self.assertEqual(config.read_bytes(), before)

    def test_doctor_fix_returns_json_error_for_corrupt_global_state(self):
        self.write_palette()
        self.paths.state_file.parent.mkdir(parents=True)
        self.paths.state_file.write_text("[invalid\n")
        with patch("thpm.service.capabilities") as caps, patch(
            "thpm.service.load_palette", return_value=COLORS
        ):
            caps.return_value.available = True
            caps.return_value.routes = set()
            caps.return_value.missing = ()
            result = Service(self.paths).doctor("cava", fix=True)
        self.assertFalse(result["ok"])
        self.assertIn("diagnostics are unavailable", result["summary"])
        self.assertTrue(result["errors"])

    def test_doctor_fix_directs_disabled_cava_to_enable(self):
        self.write_palette()
        with patch("thpm.service.capabilities") as caps, patch(
            "thpm.service.load_palette", return_value=COLORS
        ), patch("thpm.service.shutil.which", return_value="/usr/bin/cava"), patch(
            "thpm.snapshot.shutil.which", return_value="/usr/bin/cava"
        ), patch("thpm.cava.installed_version", return_value=(0, 10, 7)):
            caps.return_value.available = True
            caps.return_value.routes = set()
            caps.return_value.missing = ()
            result = Service(self.paths).doctor("cava", fix=True)
        self.assertFalse(result["ok"])
        self.assertNotIn("confirmationRequired", result)
        self.assertIn("thpm enable cava", str(result["errors"]))

    def test_human_doctor_renders_checks_and_repair_command(self):
        output = io.StringIO()
        payload = {
            "operation": "doctor",
            "ok": False,
            "summary": "1 errors, 0 warnings",
            "plugins": [],
            "errors": [],
            "warnings": [],
            "checks": [
                {
                    "id": "cava.selector",
                    "status": "error",
                    "summary": "wrong selector",
                    "repair": {"available": True},
                }
            ],
        }
        render(payload, console=Console(file=output, force_terminal=False, width=120))
        rendered = output.getvalue()
        self.assertIn("cava.selector", rendered)
        self.assertIn("thpm doctor cava --fix", rendered)

    def test_doctor_fix_json_is_one_document_with_repair_plan(self):
        self.write_palette()
        source = self.paths.current_theme / "thpm-cava.ini"
        source.write_text("[color]\ngradient = 1\n")
        config = self.paths.config_home / "cava/config"
        config.parent.mkdir(parents=True)
        config.write_text("[color]\ntheme = 'omarchy'\n")
        enabled = load(self.paths)
        enabled["cava"] = True
        save(self.paths, enabled)
        complete_cava_opt_in(self.paths)
        output = io.StringIO()
        with patch("thpm.cli.Paths.discover", return_value=self.paths), patch(
            "thpm.service.capabilities"
        ) as caps, patch("thpm.service.load_palette", return_value=COLORS), patch(
            "thpm.service.shutil.which", return_value="/usr/bin/cava"
        ), patch("thpm.snapshot.shutil.which", return_value="/usr/bin/cava"), patch(
            "thpm.cava.installed_version", return_value=(0, 10, 7)
        ), patch("sys.stdout", output):
            caps.return_value.available = True
            caps.return_value.routes = set()
            caps.return_value.missing = ()
            status = main(["doctor", "cava", "--fix", "--json"])
        payload = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertTrue(payload["confirmationRequired"])
        self.assertTrue(payload["repairPlan"])
        self.assertEqual(config.read_text(), "[color]\ntheme = 'omarchy'\n")

    def test_confirmed_doctor_fix_repairs_existing_enabled_install(self):
        self.write_palette()
        source = self.paths.current_theme / "cava_theme"
        source.write_text("[color]\ngradient = 1\n")
        config = self.paths.config_home / "cava/config"
        config.parent.mkdir(parents=True)
        config.write_text("[color]\ntheme = 'omarchy'\n")
        enabled = load(self.paths)
        enabled["cava"] = True
        save(self.paths, enabled)
        complete_cava_opt_in(self.paths)
        with patch("thpm.service.capabilities") as caps, patch(
            "thpm.service.load_palette", return_value=COLORS
        ), patch("thpm.service.shutil.which", return_value="/usr/bin/cava"), patch(
            "thpm.snapshot.shutil.which", return_value="/usr/bin/cava"
        ), patch("thpm.cava.installed_version", return_value=(0, 10, 7)), patch(
            "thpm.integrations.installed_cava_version", return_value=(0, 10, 7)
        ), patch("thpm.cava.discover_processes", return_value=[]), patch(
            "thpm.service.reload_cava_processes",
            return_value=([], ["Cava"], ["ambiguous process"]),
        ):
            caps.return_value.available = True
            caps.return_value.routes = set()
            caps.return_value.missing = ()
            fixed = Service(self.paths).doctor("cava", fix=True, confirmed=True)
            after = Service(self.paths).doctor("cava")
        self.assertTrue(fixed["ok"])
        self.assertTrue(after["ok"])
        self.assertEqual(fixed["operation"], "doctor")
        self.assertEqual(fixed["restartRequired"], ["Cava"])
        self.assertIn("ambiguous process", str(fixed["warnings"]))
        self.assertEqual(parse_cava_selector(config.read_text()).value, "thpm")
        self.assertTrue((self.paths.config_home / "cava/themes/thpm").is_file())

    def test_enable_repairs_selection_and_disable_restores_it(self):
        self.write_palette()
        source = self.paths.current_theme / "cava_theme"
        source.write_text("[color]\ngradient = 1\n")
        config = self.paths.config_home / "cava/config"
        config.parent.mkdir(parents=True)
        config.write_text("[general]\nframerate = 30\n[color]\ntheme = 'omarchy'\n")
        with patch("thpm.snapshot.shutil.which", return_value="/usr/bin/cava"), patch(
            "thpm.service.shutil.which", return_value="/usr/bin/cava"
        ), patch("thpm.cava.installed_version", return_value=(0, 10, 7)), patch(
            "thpm.integrations.installed_cava_version", return_value=(0, 10, 7)
        ):
            enabled = Service(self.paths).set_enabled(
                "cava", True, confirmed=True, refresh=False
            )
            self.assertTrue(cava_opt_in_completed(self.paths))
            config.write_text(config.read_text() + "\n[input]\nmethod = pipewire\n")
            disabled = Service(self.paths).set_enabled("cava", False)
            self.assertTrue(cava_opt_in_completed(self.paths))
            reenabled = Service(self.paths).set_enabled(
                "cava", True, confirmed=True, refresh=False
            )
            disabled_again = Service(self.paths).set_enabled("cava", False)
        self.assertTrue(enabled["ok"])
        self.assertTrue(disabled["ok"])
        self.assertTrue(reenabled["ok"])
        self.assertTrue(disabled_again["ok"])
        self.assertEqual(parse_cava_selector(config.read_text()).value, "omarchy")
        self.assertIn("method = pipewire", config.read_text())
        self.assertFalse((self.paths.config_home / "cava/themes/thpm").exists())

    def test_disable_preserves_target_when_selector_state_is_invalid(self):
        config = self.paths.config_home / "cava/config"
        target = self.paths.config_home / "cava/themes/thpm"
        config.parent.mkdir(parents=True)
        target.parent.mkdir(parents=True)
        config.write_text("[color]\ntheme='thpm'\n")
        target.write_text("managed theme\n")
        state = self.paths.managed_asset_state_dir / "cava-selection.json"
        state.parent.mkdir(parents=True)
        state.write_text("{}\n")
        enabled = load(self.paths)
        enabled["cava"] = True
        save(self.paths, enabled)
        complete_cava_opt_in(self.paths)

        result = Service(self.paths).set_enabled("cava", False)

        self.assertFalse(result["ok"])
        self.assertTrue(target.exists())
        self.assertEqual(parse_cava_selector(config.read_text()).value, "thpm")
        self.assertIn("preserved", str(result["errors"]))

    def test_disable_preserves_selected_target_when_selector_state_is_missing(self):
        config = self.paths.config_home / "cava/config"
        target = self.paths.config_home / "cava/themes/thpm"
        config.parent.mkdir(parents=True)
        target.parent.mkdir(parents=True)
        config.write_text("[color]\ntheme='thpm'\n")
        target.write_text("managed theme\n")
        enabled = load(self.paths)
        enabled["cava"] = True
        save(self.paths, enabled)
        complete_cava_opt_in(self.paths)

        result = Service(self.paths).set_enabled("cava", False)

        self.assertFalse(result["ok"])
        self.assertTrue(target.exists())
        self.assertEqual(parse_cava_selector(config.read_text()).value, "thpm")
        self.assertIn("restoration state is missing", str(result["warnings"]))
        self.assertIn("preserved", str(result["errors"]))

    def test_uninstall_preserves_selected_target_when_selector_state_is_missing(self):
        config = self.paths.config_home / "cava/config"
        target = self.paths.config_home / "cava/themes/thpm"
        config.parent.mkdir(parents=True)
        target.parent.mkdir(parents=True)
        config.write_text("[color]\ntheme='thpm'\n")
        target.write_text("managed theme\n")

        result = Service(self.paths).uninstall()

        self.assertFalse(result["ok"])
        self.assertTrue(target.exists())
        self.assertEqual(parse_cava_selector(config.read_text()).value, "thpm")
        self.assertIn("restoration state is missing", str(result["warnings"]))
        self.assertTrue(result["cleanupIncomplete"])
        self.assertEqual(result["recoveryCommand"], "thpm uninstall")
        self.assertIn(str(config), result["retainedPaths"])
        self.assertIn("cleanup is incomplete", result["summary"])
        self.assertIn("preserved", str(result["errors"]))

    def test_disable_reports_restart_for_running_cava(self):
        config = self.paths.config_home / "cava/config"
        config.parent.mkdir(parents=True)
        config.write_text("[color]\ntheme='omarchy'\n")
        configure_cava_selector(self.paths)
        enabled = load(self.paths)
        enabled["cava"] = True
        save(self.paths, enabled)
        complete_cava_opt_in(self.paths)
        with patch("thpm.service.running_cava_requires_restart", return_value=True):
            result = Service(self.paths).set_enabled("cava", False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["restartRequired"], ["Cava"])

    def test_uninstall_restores_managed_cava_selector(self):
        config = self.paths.config_home / "cava/config"
        config.parent.mkdir(parents=True)
        config.write_text("[color]\ntheme = 'omarchy'\n")
        configure_cava_selector(self.paths)
        complete_cava_opt_in(self.paths)
        config.write_text(config.read_text() + "\n[general]\nframerate = 60\n")
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            result = Service(self.paths).uninstall()
        self.assertTrue(result["ok"])
        self.assertEqual(parse_cava_selector(config.read_text()).value, "omarchy")
        self.assertIn("framerate = 60", config.read_text())
        self.assertFalse(self.paths.cava_opt_in_marker.exists())

    def test_enable_rolls_back_selector_and_state_when_apply_fails(self):
        self.write_palette()
        (self.paths.current_theme / "cava_theme").write_text("theme\n")
        config = self.paths.config_home / "cava/config"
        config.parent.mkdir(parents=True)
        original = "[color]\ntheme = 'omarchy'\n"
        config.write_text(original)

        def fail_apply(*_args, **_kwargs):
            concurrent = load(self.paths)
            concurrent["fish"] = False
            save(self.paths, concurrent)
            raise RuntimeError("apply failed")

        with patch("thpm.snapshot.shutil.which", return_value="/usr/bin/cava"), patch(
            "thpm.service.shutil.which", return_value="/usr/bin/cava"
        ), patch("thpm.cava.installed_version", return_value=(0, 10, 7)), patch(
            "thpm.integrations.installed_cava_version", return_value=(0, 10, 7)
        ), patch("thpm.service.apply_integration", side_effect=fail_apply):
            result = Service(self.paths).set_enabled(
                "cava", True, confirmed=True, refresh=False
            )
        self.assertFalse(result["ok"])
        self.assertEqual(config.read_text(), original)
        self.assertFalse(load(self.paths)["cava"])
        self.assertFalse(cava_opt_in_completed(self.paths))
        self.assertFalse(load(self.paths)["fish"])


class GsettingsFake:
    def __init__(self, value: str = "blue") -> None:
        self.value = value
        self.calls: list[list[str]] = []
        self.writable = True
        self.has_key = True
        self.fail_set = False
        self.fail_set_calls: set[int] = set()
        self.set_count = 0

    def __call__(self, command, **_kwargs):
        args = list(command)
        self.calls.append(args)
        operation = args[1]
        if operation == "list-keys":
            output = "accent-color\n" if self.has_key else "color-scheme\n"
        elif operation == "writable":
            output = "true\n" if self.writable else "false\n"
        elif operation == "get":
            output = repr(self.value) + "\n"
        elif operation == "set":
            self.set_count += 1
            if self.fail_set or self.set_count in self.fail_set_calls:
                return subprocess.CompletedProcess(args, 1, "", "set failed")
            self.value = args[-1]
            output = ""
        else:
            return subprocess.CompletedProcess(args, 1, "", "unsupported")
        return subprocess.CompletedProcess(args, 0, output, "")


class NautilusPaletteTests(Sandbox):
    def test_registry_defaults_and_optional_dependency_readiness(self):
        plugins = {plugin.id: plugin for plugin in PLUGINS}
        self.assertFalse(plugins["nautilus-palette"].default_enabled)
        self.assertFalse(plugins["gnome-accent-compat"].default_enabled)
        self.assertEqual(plugins["nautilus-palette"].support_status, "experimental")
        with patch("thpm.integrations.nautilus_python_available", return_value=False):
            ready, missing, _warnings = inspect_readiness(
                "nautilus-palette", self.paths, lambda _command: None
            )
        self.assertFalse(ready)
        self.assertIn("nautilus", missing)
        self.assertIn("nautilus-python extension loader", missing)

    def test_apply_is_xdg_aware_atomic_and_unchanged(self):
        self.write_palette()
        self.paths.current_theme_name.write_text("Dune\n")
        with patch("thpm.palette.shutil.which", return_value=None), patch.dict(
            os.environ,
            {"THPM_ASSET_DIR": str(Path(__file__).parents[1] / "assets")},
        ):
            first = apply("nautilus-palette", self.paths)
            second = apply("nautilus-palette", self.paths)
        extension = self.paths.data_home / "nautilus-python/extensions/omarchy_palette.py"
        css = (self.paths.cache_root or self.paths.home / ".cache") / "thpm/nautilus/nautilus.css"
        self.assertEqual(first.status, "applied")
        self.assertEqual(first.restartRequired, ["Nautilus"])
        self.assertEqual(second.status, "unchanged")
        self.assertEqual(second.restartRequired, [])
        self.assertIn("XDG_CACHE_HOME", extension.read_text())
        self.assertIn("@define-color window_bg_color #111111;", css.read_text())
        self.assertIn("Omarchy theme 'Dune'", css.read_text())
        self.assertEqual(css.stat().st_mode & 0o777, 0o644)

    def test_generated_css_sanitizes_comment_terminators_in_theme_name(self):
        self.write_palette()
        self.paths.current_theme_name.write_text("bad */ selector { color: red; }\n")
        with patch("thpm.palette.shutil.which", return_value=None):
            rendered = integration_adapters.render_nautilus_css(self.paths)
        self.assertNotIn("bad */", rendered)
        self.assertIn("bad * / selector", rendered)
        self.assertEqual(rendered.count("*/"), 1)

    def test_failed_first_install_restores_the_entire_preapply_surface(self):
        self.write_palette()
        transaction_paths = integration_adapters._nautilus_transaction_paths(
            self.paths
        )
        before = {
            path: integration_adapters._snapshot_path(path)
            for path in transaction_paths
        }
        with patch("thpm.palette.shutil.which", return_value=None), patch.dict(
            os.environ,
            {"THPM_ASSET_DIR": str(Path(__file__).parents[1] / "assets")},
        ), patch(
            "thpm.integrations._install_optional_asset",
            side_effect=OSError("simulated initial install failure"),
        ), self.assertRaisesRegex(OSError, "simulated initial install failure"):
            apply("nautilus-palette", self.paths)
        self.assertEqual(
            {path: integration_adapters._snapshot_path(path) for path in transaction_paths},
            before,
        )

    def test_failed_css_install_rolls_back_extension_takeover(self):
        self.write_palette()
        extension = self.paths.data_home / "nautilus-python/extensions/omarchy_palette.py"
        extension.parent.mkdir(parents=True)
        extension.write_text("prior extension\n")
        original_install = integration_adapters._install_optional_asset

        def fail_css(paths, key, source, target, **kwargs):
            if key == "nautilus-palette-css":
                raise OSError("simulated CSS install failure")
            return original_install(paths, key, source, target, **kwargs)

        with patch("thpm.palette.shutil.which", return_value=None), patch.dict(
            os.environ,
            {"THPM_ASSET_DIR": str(Path(__file__).parents[1] / "assets")},
        ), patch(
            "thpm.integrations._install_optional_asset", side_effect=fail_css
        ), self.assertRaisesRegex(OSError, "simulated CSS install failure"):
            apply("nautilus-palette", self.paths)

        self.assertEqual(extension.read_text(), "prior extension\n")
        self.assertFalse(
            (self.paths.managed_asset_state_dir / "nautilus-palette-extension.json").exists()
        )
        self.assertFalse(
            (self.paths.managed_asset_state_dir / "nautilus-palette-css.legacy-checked").exists()
        )

    def test_target_rollback_failure_retains_recoverable_metadata(self):
        self.write_palette()
        assets = Path(__file__).parents[1] / "assets"
        extension = self.paths.data_home / "nautilus-python/extensions/omarchy_palette.py"
        extension.parent.mkdir(parents=True)
        extension.write_text("prior extension\n")
        original_install = integration_adapters._install_optional_asset
        original_restore = integration_adapters._restore_path_snapshot

        def fail_css(paths, key, source, target, **kwargs):
            if key == "nautilus-palette-css":
                raise OSError("simulated CSS install failure")
            return original_install(paths, key, source, target, **kwargs)

        def fail_extension_restore(path, snapshot):
            if path == extension:
                raise OSError("simulated extension rollback failure")
            return original_restore(path, snapshot)

        with patch("thpm.palette.shutil.which", return_value=None), patch.dict(
            os.environ, {"THPM_ASSET_DIR": str(assets)}
        ), patch(
            "thpm.integrations._install_optional_asset", side_effect=fail_css
        ), patch(
            "thpm.integrations._restore_path_snapshot",
            side_effect=fail_extension_restore,
        ), self.assertRaises(ApplyFailure) as raised:
            apply("nautilus-palette", self.paths)

        state, backup = integration_adapters._asset_state_paths(
            self.paths, "nautilus-palette-extension"
        )
        saved = integration_adapters._read_asset_state(state)
        self.assertIsNotNone(saved)
        self.assertEqual(backup.read_text(), "prior extension\n")
        self.assertNotEqual(extension.read_text(), "prior extension\n")
        self.assertIn(str(extension), raised.exception.changed)
        self.assertIn(str(state), raised.exception.changed)
        self.assertIn(str(backup), raised.exception.changed)
        self.assertEqual(raised.exception.restart_required, ["Nautilus"])
        self.assertIn("retained for recovery", str(raised.exception.warnings))

        cleanup_changed, cleanup_warnings = cleanup_managed_outputs(
            self.paths, "nautilus-palette"
        )
        self.assertEqual(cleanup_warnings, [])
        self.assertIn(str(extension), cleanup_changed)
        self.assertEqual(extension.read_text(), "prior extension\n")
        self.assertFalse(state.exists())
        self.assertFalse(backup.exists())

    def test_service_reports_incomplete_rollback_paths_and_restart(self):
        self.write_palette()
        assets = Path(__file__).parents[1] / "assets"
        extension = self.paths.data_home / "nautilus-python/extensions/omarchy_palette.py"
        extension.parent.mkdir(parents=True)
        extension.write_text("prior extension\n")
        original_install = integration_adapters._install_optional_asset
        original_restore = integration_adapters._restore_path_snapshot

        def fail_css(paths, key, source, target, **kwargs):
            if key == "nautilus-palette-css":
                raise OSError("simulated CSS install failure")
            return original_install(paths, key, source, target, **kwargs)

        def fail_extension_restore(path, snapshot):
            if path == extension:
                raise OSError("simulated extension rollback failure")
            return original_restore(path, snapshot)

        enabled = {plugin.id: False for plugin in PLUGINS}
        enabled["nautilus-palette"] = True
        save(self.paths, enabled)
        with patch("thpm.palette.shutil.which", return_value=None), patch.dict(
            os.environ, {"THPM_ASSET_DIR": str(assets)}
        ), patch(
            "thpm.integrations.inspect_readiness", return_value=(True, [], [])
        ), patch(
            "thpm.integrations._install_optional_asset", side_effect=fail_css
        ), patch(
            "thpm.integrations._restore_path_snapshot",
            side_effect=fail_extension_restore,
        ), patch(
            "thpm.service._notify_restart_required", return_value=False
        ):
            payload = Service(self.paths).hook_run("theme-set", ["test-theme"])

        result = next(
            item for item in payload["results"] if item["id"] == "nautilus-palette"
        )
        state, backup = integration_adapters._asset_state_paths(
            self.paths, "nautilus-palette-extension"
        )
        self.assertFalse(payload["ok"])
        self.assertEqual(result["status"], "failed")
        self.assertIn(str(extension), result["changed"])
        self.assertIn(str(state), result["changed"])
        self.assertIn(str(backup), result["changed"])
        self.assertEqual(result["restartRequired"], ["Nautilus"])
        self.assertEqual(payload["restartRequired"], ["Nautilus"])
        self.assertIn("retained for recovery", str(result["warnings"]))
        cleanup_changed, cleanup_warnings = cleanup_managed_outputs(
            self.paths, "nautilus-palette"
        )
        self.assertEqual(cleanup_warnings, [])
        self.assertIn(str(extension), cleanup_changed)
        self.assertEqual(extension.read_text(), "prior extension\n")

    def _assert_reapply_metadata_failure_recovers_user_baseline(
        self, failed_metadata: str
    ) -> None:
        self.write_palette()
        assets = Path(__file__).parents[1] / "assets"
        css = (self.paths.cache_root or self.paths.home / ".cache") / "thpm/nautilus/nautilus.css"
        css.parent.mkdir(parents=True)
        css.write_text("displaced user css\n")
        with patch("thpm.palette.shutil.which", return_value=None), patch.dict(
            os.environ, {"THPM_ASSET_DIR": str(assets)}
        ):
            apply("nautilus-palette", self.paths)
        managed_before = css.read_bytes()
        state, backup = integration_adapters._asset_state_paths(
            self.paths, "nautilus-palette-css"
        )
        state_before = state.read_bytes()
        backup_before = backup.read_bytes()
        marker = integration_adapters._asset_legacy_marker(
            self.paths, "nautilus-palette-css"
        )
        failed_path = {"backup": backup, "state": state}[failed_metadata]
        colors = (self.paths.current_theme / "colors.toml").read_text()
        (self.paths.current_theme / "colors.toml").write_text(
            colors.replace('#4477cc', '#1177aa')
        )
        original_install = integration_adapters._install_optional_asset
        original_restore = integration_adapters._restore_path_snapshot

        def fail_after_css(paths, key, source, target, **kwargs):
            changed = original_install(paths, key, source, target, **kwargs)
            if key == "nautilus-palette-css":
                raise OSError("simulated post-CSS failure")
            return changed

        def fail_metadata_restore(path, snapshot):
            if path == failed_path:
                raise OSError(f"simulated {failed_metadata} restoration failure")
            return original_restore(path, snapshot)

        with patch("thpm.palette.shutil.which", return_value=None), patch.dict(
            os.environ, {"THPM_ASSET_DIR": str(assets)}
        ), patch(
            "thpm.integrations._install_optional_asset", side_effect=fail_after_css
        ), patch(
            "thpm.integrations._restore_path_snapshot",
            side_effect=fail_metadata_restore,
        ), self.assertRaises(ApplyFailure) as raised:
            apply("nautilus-palette", self.paths)

        saved = integration_adapters._read_asset_state(state)
        self.assertIsNotNone(saved)
        self.assertEqual(css.read_bytes(), managed_before)
        self.assertEqual(state.read_bytes(), state_before)
        self.assertEqual(backup.read_bytes(), backup_before)
        self.assertTrue(marker.is_file())
        self.assertEqual(
            saved["managedSha256"], hashlib.sha256(managed_before).hexdigest()
        )
        self.assertEqual(saved["managedMode"], css.stat().st_mode & 0o777)
        self.assertEqual(
            saved["priorSha256"], hashlib.sha256(backup_before).hexdigest()
        )
        self.assertIn(str(failed_path), raised.exception.changed)
        self.assertIn("retained for recovery", str(raised.exception.warnings))
        self.assertEqual(raised.exception.restart_required, ["Nautilus"])

        cleanup_changed, cleanup_warnings = cleanup_managed_outputs(
            self.paths, "nautilus-palette"
        )
        self.assertEqual(cleanup_warnings, [])
        self.assertIn(str(css), cleanup_changed)
        self.assertEqual(css.read_text(), "displaced user css\n")
        self.assertFalse(state.exists())
        self.assertFalse(backup.exists())

    def test_reapply_backup_rollback_failure_preserves_user_baseline(self):
        self._assert_reapply_metadata_failure_recovers_user_baseline("backup")

    def test_reapply_state_rollback_failure_preserves_user_baseline(self):
        self._assert_reapply_metadata_failure_recovers_user_baseline("state")

    def test_failed_second_reapply_restores_targets_and_state_exactly(self):
        self.write_palette()
        assets = Path(__file__).parents[1] / "assets"
        with patch("thpm.palette.shutil.which", return_value=None), patch.dict(
            os.environ, {"THPM_ASSET_DIR": str(assets)}
        ):
            apply("nautilus-palette", self.paths)
        transaction_paths = integration_adapters._nautilus_transaction_paths(
            self.paths
        )
        before = {
            path: integration_adapters._snapshot_path(path)
            for path in transaction_paths
        }
        colors = (self.paths.current_theme / "colors.toml").read_text()
        (self.paths.current_theme / "colors.toml").write_text(
            colors.replace('#4477cc', '#1177aa')
        )
        original_install = integration_adapters._install_optional_asset

        def fail_after_css(paths, key, source, target, **kwargs):
            changed = original_install(paths, key, source, target, **kwargs)
            if key == "nautilus-palette-css":
                raise OSError("simulated post-CSS failure")
            return changed

        with patch("thpm.palette.shutil.which", return_value=None), patch.dict(
            os.environ, {"THPM_ASSET_DIR": str(assets)}
        ), patch(
            "thpm.integrations._install_optional_asset", side_effect=fail_after_css
        ), self.assertRaisesRegex(OSError, "simulated post-CSS failure"):
            apply("nautilus-palette", self.paths)
        self.assertEqual(
            {path: integration_adapters._snapshot_path(path) for path in transaction_paths},
            before,
        )

    def test_disable_restores_displaced_files_and_preserves_later_edit(self):
        self.write_palette()
        extension = self.paths.data_home / "nautilus-python/extensions/omarchy_palette.py"
        css = (self.paths.cache_root or self.paths.home / ".cache") / "thpm/nautilus/nautilus.css"
        extension.parent.mkdir(parents=True)
        css.parent.mkdir(parents=True)
        extension.write_text("prior extension\n")
        css.write_text("prior css\n")
        with patch("thpm.palette.shutil.which", return_value=None), patch.dict(
            os.environ,
            {"THPM_ASSET_DIR": str(Path(__file__).parents[1] / "assets")},
        ):
            apply("nautilus-palette", self.paths)
        extension.write_text("user extension edit\n")
        enabled = load(self.paths)
        enabled["nautilus-palette"] = True
        save(self.paths, enabled)

        disabled = Service(self.paths).set_enabled(
            "nautilus-palette", False, refresh=False
        )

        self.assertTrue(disabled["ok"])
        self.assertEqual(extension.read_text(), "user extension edit\n")
        self.assertEqual(css.read_text(), "prior css\n")
        self.assertIn("preserved user-modified file", str(disabled["warnings"]))
        self.assertEqual(disabled["restartRequired"], [])

    def test_disable_preserves_preexisting_byte_identical_targets(self):
        self.write_palette()
        assets = Path(__file__).parents[1] / "assets"
        extension = self.paths.data_home / "nautilus-python/extensions/omarchy_palette.py"
        css = (self.paths.cache_root or self.paths.home / ".cache") / "thpm/nautilus/nautilus.css"
        extension.parent.mkdir(parents=True)
        css.parent.mkdir(parents=True)
        extension.write_bytes((assets / "nautilus/omarchy_palette.py").read_bytes())
        with patch("thpm.palette.shutil.which", return_value=None):
            css.write_text(integration_adapters.render_nautilus_css(self.paths))
        expected_extension = extension.read_bytes()
        expected_css = css.read_bytes()
        with patch("thpm.palette.shutil.which", return_value=None), patch.dict(
            os.environ, {"THPM_ASSET_DIR": str(assets)}
        ):
            applied = apply("nautilus-palette", self.paths)
        enabled = load(self.paths)
        enabled["nautilus-palette"] = True
        save(self.paths, enabled)
        disabled = Service(self.paths).set_enabled(
            "nautilus-palette", False, refresh=False
        )
        self.assertEqual(applied.status, "unchanged")
        self.assertTrue(disabled["ok"])
        self.assertEqual(extension.read_bytes(), expected_extension)
        self.assertEqual(css.read_bytes(), expected_css)

    def test_uninstall_removes_owned_files_and_reports_nautilus_restart(self):
        self.write_palette()
        with patch("thpm.palette.shutil.which", return_value=None), patch.dict(
            os.environ,
            {"THPM_ASSET_DIR": str(Path(__file__).parents[1] / "assets")},
        ), patch(
            "thpm.service.ui.remove", return_value={"installed": False}
        ):
            apply("nautilus-palette", self.paths)
            result = Service(self.paths).uninstall()
        extension = self.paths.data_home / "nautilus-python/extensions/omarchy_palette.py"
        css = (self.paths.cache_root or self.paths.home / ".cache") / "thpm/nautilus/nautilus.css"
        self.assertTrue(result["ok"])
        self.assertFalse(extension.exists())
        self.assertFalse(css.exists())
        self.assertEqual(result["restartRequired"], ["Nautilus"])

    def test_extension_contract_compiles_and_clears_css_on_delete(self):
        root = Path(__file__).parents[1]
        extension = root / "assets/nautilus/omarchy_palette.py"
        tree = ast.parse(extension.read_text(), filename=str(extension))
        provider = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "OmarchyPalette"
        )
        methods = {
            node.name for node in provider.body if isinstance(node, ast.FunctionDef)
        }
        self.assertIn("get_file_items", methods)
        self.assertIn("get_background_items", methods)
        compile(extension.read_text(), str(extension), "exec")

        probe = r'''
import json, os, runpy, sys, tempfile, types
class GObjectBase: pass
class MenuProvider: pass
class Display:
    @staticmethod
    def get_default(): return None
class FileMonitorEvent:
    CHANGED=1; CREATED=2; RENAMED=3; DELETED=4; MOVED_OUT=5; CHANGES_DONE_HINT=6
class File:
    def __init__(self, path): self.path = path
    def get_path(self): return self.path
    @staticmethod
    def new_for_path(path): return File(path)
callbacks = []
GLib = types.SimpleNamespace(SOURCE_REMOVE=False, Error=Exception,
    timeout_add=lambda delay, callback: callbacks.append((delay, callback)) or len(callbacks),
    source_remove=lambda source: None)
Gdk = types.SimpleNamespace(Display=Display)
Gio = types.SimpleNamespace(File=File, FileMonitorEvent=FileMonitorEvent,
    FileMonitorFlags=types.SimpleNamespace(NONE=0))
GObject = types.SimpleNamespace(GObject=GObjectBase)
Gtk = types.SimpleNamespace(CssProvider=object, StyleContext=object,
    STYLE_PROVIDER_PRIORITY_USER=1)
Nautilus = types.SimpleNamespace(MenuProvider=MenuProvider)
gi = types.ModuleType("gi")
gi.require_version = lambda *args: None
repository = types.ModuleType("gi.repository")
for name, value in {"GLib":GLib,"Gdk":Gdk,"Gio":Gio,"GObject":GObject,"Gtk":Gtk,"Nautilus":Nautilus}.items():
    setattr(repository, name, value)
sys.modules.update({"gi":gi, "gi.repository":repository})
namespace = runpy.run_path(sys.argv[1])
runtime = namespace["_reload_now"].__globals__
original_css_path = runtime["CSS_PATH"]
class Provider:
    def __init__(self): self.cleared = False
    def load_from_data(self, data): self.cleared = data == b""
provider = Provider()
runtime["_provider"] = provider
runtime["CSS_PATH"] = os.path.join(tempfile.mkdtemp(), "missing.css")
runtime["CSS_NAME"] = "missing.css"
namespace["_reload_now"]()
callbacks.clear()
namespace["_on_css_dir_changed"](None, File(runtime["CSS_PATH"]), None, FileMonitorEvent.DELETED)
print(json.dumps({
    "cleared": provider.cleared,
    "scheduled": len(callbacks),
    "cssPath": original_css_path,
}))
'''
        working_dir = self.paths.home / "nautilus-working-directory"
        working_dir.mkdir()
        environment = os.environ.copy()
        environment.update({"HOME": str(self.paths.home), "XDG_CACHE_HOME": ""})
        completed = subprocess.run(
            [sys.executable, "-c", probe, str(extension)],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
            cwd=working_dir,
            env=environment,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            json.loads(completed.stdout),
            {
                "cleared": True,
                "scheduled": 1,
                "cssPath": str(self.paths.home / ".cache/thpm/nautilus/nautilus.css"),
            },
        )

    def test_extension_loads_with_real_gi_when_available(self):
        extension = Path(__file__).parents[1] / "assets/nautilus/omarchy_palette.py"
        probe = (
            "import gi, importlib.util; "
            "gi.require_version('Gtk','4.0'); "
            "gi.require_version('Gdk','4.0'); "
            "gi.require_version('Nautilus','4.1'); "
            f"spec=importlib.util.spec_from_file_location('thpm_nautilus_palette',{str(extension)!r}); "
            "module=importlib.util.module_from_spec(spec); "
            "spec.loader.exec_module(module); "
            "provider=module.OmarchyPalette(); "
            "assert provider.get_file_items([])==[]; "
            "assert provider.get_background_items(None)==[]"
        )
        environment = os.environ.copy()
        for key in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS"):
            environment.pop(key, None)
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
            env=environment,
        )
        unavailable = (
            "No module named 'gi'",
            "Namespace Nautilus not available",
            "Typelib file for namespace 'Nautilus'",
        )
        if completed.returncode != 0 and any(
            marker in completed.stderr for marker in unavailable
        ):
            self.skipTest("PyGObject/Nautilus typelib is unavailable")
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_install_check_requires_nautilus_runtime_assets(self):
        root = Path(self.temp.name) / "assets"
        for directory in ("templates", "hooks", "qml", "spicetify", "nautilus"):
            (root / directory).mkdir(parents=True)
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(root)}), patch(
            "thpm.service.capabilities"
        ) as caps:
            caps.return_value.available = True
            caps.return_value.routes = set()
            caps.return_value.missing = ()
            result = Service(self.paths).install_check()
        self.assertFalse(result["ok"])
        messages = [str(error["message"]) for error in result["errors"]]
        self.assertIn(
            f"packaged asset missing: {root / 'nautilus/omarchy_palette.py'}",
            messages,
        )
        self.assertIn(
            f"packaged asset missing: {root / 'nautilus/LICENSE'}", messages
        )
        self.assertIn(
            f"packaged asset missing: {root / 'nautilus/UPSTREAM.md'}", messages
        )
        self.assertNotIn("packaged asset directory missing", " ".join(messages))

        (root / "qml").rmdir()
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(root)}), patch(
            "thpm.service.capabilities"
        ) as caps:
            caps.return_value.available = True
            caps.return_value.routes = set()
            caps.return_value.missing = ()
            missing_directory = Service(self.paths).install_check()
        self.assertIn(
            f"packaged asset directory missing: {root / 'qml'}",
            [str(error["message"]) for error in missing_directory["errors"]],
        )

    def test_packaged_license_and_pinned_provenance_are_retained(self):
        root = Path(__file__).parents[1]
        license_text = (root / "assets/nautilus/LICENSE").read_text()
        upstream = (root / "assets/nautilus/UPSTREAM.md").read_text()
        package = (root / "pyproject.toml").read_text()
        self.assertIn("Copyright (c) 2024 JJDizz1L", license_text)
        self.assertIn("Permission is hereby granted", license_text)
        self.assertIn("7324544a1dad9602d1c3195df3c984ed2223750a", upstream)
        self.assertIn('"share/thpm/nautilus"', package)
        self.assertIn('"assets/nautilus/LICENSE"', package)
        stable = (root / "packaging/aur/thpm/PKGBUILD").read_text()
        stable_metadata = (root / "packaging/aur/thpm/.SRCINFO").read_text()
        self.assertNotIn("nautilus-python", stable)
        self.assertNotIn('assets/nautilus/*', stable)
        self.assertNotIn("nautilus-python", stable_metadata)
        vcs = (root / "packaging/aur/thpm-git/PKGBUILD").read_text()
        vcs_metadata = (root / "packaging/aur/thpm-git/.SRCINFO").read_text()
        self.assertIn("glib2: GNOME accent compatibility through gsettings", vcs)
        self.assertIn("nautilus-python: Nautilus Python extension loader", vcs)
        self.assertIn('assets/nautilus/*', vcs)
        self.assertIn("LICENSE.paint-omarchy-nautilus", vcs)
        self.assertIn("glib2: GNOME accent compatibility through gsettings", vcs_metadata)
        self.assertIn("nautilus-python: Nautilus Python extension loader", vcs_metadata)

    def test_built_wheel_contains_nautilus_assets(self):
        root = Path(__file__).parents[1]
        output = Path(self.temp.name) / "wheel"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--no-isolation",
                "--outdir",
                str(output),
                str(root),
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
        if completed.returncode != 0 and "No module named build" in completed.stderr:
            self.skipTest("python-build is unavailable")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        wheel = next(output.glob("thpm-*.whl"))
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
        for suffix in (
            "share/thpm/nautilus/omarchy_palette.py",
            "share/thpm/nautilus/LICENSE",
            "share/thpm/nautilus/UPSTREAM.md",
        ):
            self.assertTrue(any(name.endswith(suffix) for name in names), suffix)


class GnomeAccentCompatTests(Sandbox):
    def setUp(self):
        super().setUp()
        self.desktop_session = patch.dict(
            os.environ, {"DBUS_SESSION_BUS_ADDRESS": "test-session"}
        )
        self.desktop_session.start()

    def tearDown(self):
        self.desktop_session.stop()
        super().tearDown()

    def test_readiness_requires_session_schema_key_and_writable_value(self):
        fake = GsettingsFake()
        with patch.dict(os.environ, {}, clear=True), patch(
            "thpm.gnome_accent.subprocess.run", side_effect=fake
        ):
            ready, missing, _warnings = inspect_readiness(
                "gnome-accent-compat", self.paths, lambda _command: "/usr/bin/gsettings"
            )
        self.assertFalse(ready)
        self.assertIn("desktop DBus session", missing[0])

        fake.writable = False
        with patch.dict(os.environ, {"DBUS_SESSION_BUS_ADDRESS": "test"}), patch(
            "thpm.gnome_accent.subprocess.run", side_effect=fake
        ):
            ready, missing, _warnings = inspect_readiness(
                "gnome-accent-compat", self.paths, lambda _command: "/usr/bin/gsettings"
            )
        self.assertFalse(ready)
        self.assertIn("writable GSettings key", missing[0])

    def test_apply_unchanged_and_disable_restore_prior_accent(self):
        self.write_palette()
        colors = (self.paths.current_theme / "colors.toml").read_text()
        (self.paths.current_theme / "colors.toml").write_text(
            colors + 'accent = "#dd3344"\n'
        )
        fake = GsettingsFake("blue")
        with patch("thpm.palette.shutil.which", return_value=None), patch(
            "thpm.gnome_accent.subprocess.run", side_effect=fake
        ):
            first = apply("gnome-accent-compat", self.paths)
            second = apply("gnome-accent-compat", self.paths)
            enabled = load(self.paths)
            enabled["gnome-accent-compat"] = True
            save(self.paths, enabled)
            disabled = Service(self.paths).set_enabled(
                "gnome-accent-compat", False, refresh=False
            )
        self.assertEqual(first.status, "applied")
        self.assertEqual(second.status, "unchanged")
        self.assertEqual(fake.value, "blue")
        self.assertTrue(disabled["ok"])
        self.assertFalse(
            (self.paths.managed_asset_state_dir / "gnome-accent-compat.json").exists()
        )

    def test_failed_initial_set_removes_new_restoration_state(self):
        self.write_palette()
        colors = (self.paths.current_theme / "colors.toml").read_text()
        (self.paths.current_theme / "colors.toml").write_text(
            colors + 'accent = "#dd3344"\n'
        )
        fake = GsettingsFake("blue")
        fake.fail_set = True
        with patch("thpm.palette.shutil.which", return_value=None), patch(
            "thpm.gnome_accent.subprocess.run", side_effect=fake
        ), self.assertRaisesRegex(RuntimeError, "set failed"):
            apply("gnome-accent-compat", self.paths)
        self.assertEqual(fake.value, "blue")
        self.assertFalse(
            (self.paths.managed_asset_state_dir / "gnome-accent-compat.json").exists()
        )

    def test_prepared_transition_recovers_as_not_attempted(self):
        self.write_palette()
        colors = (self.paths.current_theme / "colors.toml").read_text()
        (self.paths.current_theme / "colors.toml").write_text(
            colors + 'accent = "#dd3344"\n'
        )
        state = self.paths.managed_asset_state_dir / "gnome-accent-compat.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({
            "version": 2,
            "schema": "org.gnome.desktop.interface",
            "key": "accent-color",
            "phase": "prepared",
            "prior": "blue",
            "managed": "blue",
            "pendingFrom": "blue",
            "pendingTo": "red",
            "hadOwnership": False,
        }))
        fake = GsettingsFake("blue")
        with patch("thpm.palette.shutil.which", return_value=None), patch(
            "thpm.gnome_accent.subprocess.run", side_effect=fake
        ):
            result = apply("gnome-accent-compat", self.paths)
        saved = json.loads(state.read_text())
        self.assertEqual(saved["phase"], "committed")
        self.assertEqual(saved["managed"], fake.value)
        self.assertEqual(fake.set_count, 1)
        self.assertIn(str(state), result.changed)

    def test_may_have_succeeded_transition_recovers_then_cleanup_restores(self):
        self.write_palette()
        state = self.paths.managed_asset_state_dir / "gnome-accent-compat.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({
            "version": 2,
            "schema": "org.gnome.desktop.interface",
            "key": "accent-color",
            "phase": "may-have-succeeded",
            "prior": "blue",
            "managed": "blue",
            "pendingFrom": "blue",
            "pendingTo": "red",
            "hadOwnership": False,
        }))
        fake = GsettingsFake("red")
        with patch(
            "thpm.gnome_accent.subprocess.run", side_effect=fake
        ):
            changed, warnings = gnome_accent.cleanup(self.paths)
        self.assertEqual(warnings, [])
        self.assertEqual(fake.value, "blue")
        self.assertFalse(state.exists())
        self.assertIn(str(state), changed)

    def test_pretransition_state_write_failure_does_not_mutate_setting(self):
        self.write_palette()
        fake = GsettingsFake("blue")
        with patch("thpm.palette.shutil.which", return_value=None), patch(
            "thpm.gnome_accent.subprocess.run", side_effect=fake
        ), patch(
            "thpm.gnome_accent._write_state",
            side_effect=OSError("simulated pending-state write failure"),
        ), self.assertRaisesRegex(OSError, "pending-state write failure"):
            apply("gnome-accent-compat", self.paths)
        self.assertEqual(fake.value, "blue")
        self.assertEqual(fake.set_count, 0)

    def test_state_commit_and_setting_rollback_failure_retains_pending_state(self):
        self.write_palette()
        colors = (self.paths.current_theme / "colors.toml").read_text()
        (self.paths.current_theme / "colors.toml").write_text(
            colors + 'accent = "#dd3344"\n'
        )
        fake = GsettingsFake("blue")
        fake.fail_set_calls.add(2)
        original_write = gnome_accent._write_state
        write_count = 0

        def fail_commit(path, saved):
            nonlocal write_count
            write_count += 1
            if write_count == 3:
                raise OSError("simulated committed-state write failure")
            return original_write(path, saved)

        with patch("thpm.palette.shutil.which", return_value=None), patch(
            "thpm.gnome_accent.subprocess.run", side_effect=fake
        ), patch(
            "thpm.gnome_accent._write_state", side_effect=fail_commit
        ), self.assertRaisesRegex(RuntimeError, "rollback.*also failed"):
            apply("gnome-accent-compat", self.paths)
        state = self.paths.managed_asset_state_dir / "gnome-accent-compat.json"
        saved = json.loads(state.read_text())
        self.assertEqual(saved["phase"], "may-have-succeeded")
        self.assertEqual(saved["pendingFrom"], "blue")
        self.assertEqual(saved["pendingTo"], fake.value)

    def test_pending_transition_with_unrelated_current_value_fails_closed(self):
        self.write_palette()
        state = self.paths.managed_asset_state_dir / "gnome-accent-compat.json"
        state.parent.mkdir(parents=True)
        pending = {
            "version": 2,
            "schema": "org.gnome.desktop.interface",
            "key": "accent-color",
            "phase": "may-have-succeeded",
            "prior": "blue",
            "managed": "blue",
            "pendingFrom": "blue",
            "pendingTo": "red",
            "hadOwnership": False,
        }
        state.write_text(json.dumps(pending))
        fake = GsettingsFake("pink")
        with patch("thpm.gnome_accent.subprocess.run", side_effect=fake), self.assertRaisesRegex(
            RuntimeError, "transition is unresolved"
        ):
            apply("gnome-accent-compat", self.paths)
        self.assertEqual(json.loads(state.read_text()), pending)
        self.assertEqual(fake.set_count, 0)

    def test_user_accent_change_is_preserved_on_apply_and_uninstall(self):
        self.write_palette()
        fake = GsettingsFake("blue")
        with patch("thpm.palette.shutil.which", return_value=None), patch(
            "thpm.gnome_accent.subprocess.run", side_effect=fake
        ), patch(
            "thpm.service.ui.remove", return_value={"installed": False}
        ):
            apply("gnome-accent-compat", self.paths)
            managed = fake.value
            fake.value = "pink" if managed != "pink" else "green"
            preserved_apply = apply("gnome-accent-compat", self.paths)
            result = Service(self.paths).uninstall()
        self.assertEqual(fake.value, "pink" if managed != "pink" else "green")
        self.assertIn("preserved user-modified GNOME accent", str(preserved_apply.warnings))
        self.assertIn("preserved user-modified GNOME accent", str(result["warnings"]))
        self.assertTrue(result["ok"])

    def test_cleanup_fails_closed_without_session_access(self):
        self.write_palette()
        fake = GsettingsFake("blue")
        with patch("thpm.palette.shutil.which", return_value=None), patch(
            "thpm.gnome_accent.subprocess.run", side_effect=fake
        ):
            apply("gnome-accent-compat", self.paths)
        enabled = load(self.paths)
        enabled["gnome-accent-compat"] = True
        save(self.paths, enabled)
        with patch.dict(os.environ, {"DBUS_SESSION_BUS_ADDRESS": ""}), patch(
            "thpm.gnome_accent.subprocess.run", side_effect=OSError("no session")
        ):
            disabled = Service(self.paths).set_enabled(
                "gnome-accent-compat", False, refresh=False
            )
        self.assertFalse(disabled["ok"])
        self.assertTrue(disabled["cleanupIncomplete"])
        self.assertTrue(
            (self.paths.managed_asset_state_dir / "gnome-accent-compat.json").exists()
        )


class IntegrationTests(Sandbox):
    def test_cliamp_colors_only_preserves_native_theme_selection(self):
        self.write_palette()
        config = self.paths.config_home / "cliamp/config.toml"
        config.parent.mkdir(parents=True)
        config.write_text('theme = "miasma"\nvolume = 75\n')

        result = apply("cliamp", self.paths)

        target = self.paths.config_home / "cliamp/themes/omarchy.toml"
        self.assertEqual(result.status, "unchanged")
        self.assertFalse(target.exists())
        self.assertEqual(config.read_text(), 'theme = "miasma"\nvolume = 75\n')

    def test_cliamp_authored_theme_takes_precedence_over_invalid_palette(self):
        source = self.paths.current_theme / "cliamp.toml"
        source.parent.mkdir(parents=True)
        source.write_text(
            '# thpm:cliamp-use-native\n'
            'bg = "#010101"\naccent = "#020202"\nbright_fg = "#030303"\n'
            'fg = "#040404"\ngreen = "#050505"\nyellow = "#060606"\nred = "#070707"\n'
        )
        (self.paths.current_theme / "colors.toml").write_text("not valid TOML = [\n")

        first = apply("cliamp", self.paths)
        second = apply("cliamp", self.paths)

        target = self.paths.config_home / "cliamp/themes/omarchy.toml"
        self.assertEqual(first.status, "applied")
        self.assertEqual(second.status, "unchanged")
        self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_cliamp_unmarked_authored_file_preserves_native_theme(self):
        source = self.paths.current_theme / "cliamp.toml"
        source.parent.mkdir(parents=True)
        source.write_text(
            'bg = "#010101"\naccent = "#020202"\nbright_fg = "#030303"\n'
            'fg = "#040404"\ngreen = "#050505"\nyellow = "#060606"\nred = "#070707"\n'
        )
        config = self.paths.config_home / "cliamp/config.toml"
        config.parent.mkdir(parents=True)
        config.write_text('theme = "miasma"\n')

        result = apply("cliamp", self.paths)

        self.assertEqual(result.status, "unchanged")
        self.assertFalse((self.paths.config_home / "cliamp/themes/omarchy.toml").exists())
        self.assertEqual(config.read_text(), 'theme = "miasma"\n')

    def test_cliamp_authored_override_selects_and_restores_previous_theme(self):
        source = self.paths.current_theme / "cliamp.toml"
        source.parent.mkdir(parents=True)
        source.write_text(
            '# thpm:cliamp-use-native\n'
            'accent = "#020202"\nbright_fg = "#030303"\nfg = "#040404"\n'
            'green = "#050505"\nyellow = "#060606"\nred = "#070707"\n'
        )
        config = self.paths.config_home / "cliamp/config.toml"
        config.parent.mkdir(parents=True)
        original = 'theme = "miasma" # keep\nvolume = 75\n'
        config.write_text(original)

        applied = apply("cliamp", self.paths)

        self.assertEqual(applied.status, "applied")
        self.assertEqual(config.read_text(), 'theme = "omarchy" # keep\nvolume = 75\n')

        source.unlink()
        restored = apply("cliamp", self.paths)

        self.assertEqual(restored.status, "applied")
        self.assertEqual(config.read_text(), original)
        self.assertFalse((self.paths.config_home / "cliamp/themes/omarchy.toml").exists())

    def test_cliamp_malformed_config_rolls_back_authored_asset(self):
        source = self.paths.current_theme / "cliamp.toml"
        source.parent.mkdir(parents=True)
        source.write_text("# thpm:cliamp-use-native\naccent = \"#020202\"\n")
        target = self.paths.config_home / "cliamp/themes/omarchy.toml"
        target.parent.mkdir(parents=True)
        target.write_text("user theme\n")
        config = self.paths.config_home / "cliamp/config.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("theme = [broken\n")

        with self.assertRaisesRegex(RuntimeError, "malformed top-level theme selector"):
            apply("cliamp", self.paths)

        self.assertEqual(target.read_text(), "user theme\n")

    def test_cliamp_interrupted_selector_write_removes_false_state(self):
        from thpm.files import atomic_text as real_atomic_text

        source = self.paths.current_theme / "cliamp.toml"
        source.parent.mkdir(parents=True)
        source.write_text("# thpm:cliamp-use-native\naccent = \"#020202\"\n")
        config = self.paths.config_home / "cliamp/config.toml"
        config.parent.mkdir(parents=True)
        config.write_text('theme = "miasma"\n')

        def interrupted(path, content, **kwargs):
            if Path(path) == config:
                raise OSError("interrupted selector write")
            return real_atomic_text(path, content, **kwargs)

        with patch("thpm.cliamp.atomic_text", side_effect=interrupted), self.assertRaisesRegex(
            OSError, "interrupted selector write"
        ):
            apply("cliamp", self.paths)

        self.assertEqual(config.read_text(), 'theme = "miasma"\n')
        self.assertFalse(
            (self.paths.managed_asset_state_dir / "cliamp-selection.json").exists()
        )

    def test_cliamp_cleanup_preserves_user_edited_managed_selector_line(self):
        source = self.paths.current_theme / "cliamp.toml"
        source.parent.mkdir(parents=True)
        source.write_text("# thpm:cliamp-use-native\naccent = \"#020202\"\n")
        config = self.paths.config_home / "cliamp/config.toml"
        config.parent.mkdir(parents=True)
        config.write_text('theme = "miasma" # original\nvolume = 75\n')
        target = self.paths.config_home / "cliamp/themes/omarchy.toml"

        apply("cliamp", self.paths)
        config.write_text('theme = "omarchy" # user edited while managed\nvolume = 75\n')
        source.unlink()
        result = apply("cliamp", self.paths)

        self.assertEqual(
            config.read_text(),
            'theme = "omarchy" # user edited while managed\nvolume = 75\n',
        )
        self.assertTrue(target.is_file())
        self.assertTrue(
            (self.paths.managed_asset_state_dir / "cliamp-selection.json").is_file()
        )
        self.assertTrue(
            any(
                "preserved user-modified cliamp theme selector" in warning
                for warning in result.warnings
            )
        )

    def test_cliamp_disable_retains_theme_for_edited_managed_selector(self):
        source = self.paths.current_theme / "cliamp.toml"
        source.parent.mkdir(parents=True)
        source.write_text("# thpm:cliamp-use-native\naccent = \"#020202\"\n")
        config = self.paths.config_home / "cliamp/config.toml"
        config.parent.mkdir(parents=True)
        config.write_text('theme = "miasma" # original\n')
        target = self.paths.config_home / "cliamp/themes/omarchy.toml"
        apply("cliamp", self.paths)
        save(self.paths, {"cliamp": True})
        config.write_text('theme = "omarchy" # user edited while managed\n')

        payload = Service(self.paths).set_enabled("cliamp", False, refresh=False)

        self.assertTrue(payload["ok"])
        self.assertFalse(payload["cleanupIncomplete"])
        self.assertTrue(target.is_file())
        self.assertTrue(
            (self.paths.managed_asset_state_dir / "cliamp-selection.json").is_file()
        )

    def test_cliamp_disable_fails_closed_for_invalid_selector_state(self):
        source = self.paths.current_theme / "cliamp.toml"
        source.parent.mkdir(parents=True)
        source.write_text("# thpm:cliamp-use-native\naccent = \"#020202\"\n")
        config = self.paths.config_home / "cliamp/config.toml"
        config.parent.mkdir(parents=True)
        config.write_text('theme = "miasma"\n')
        target = self.paths.config_home / "cliamp/themes/omarchy.toml"
        apply("cliamp", self.paths)
        save(self.paths, {"cliamp": True})
        selection_state = self.paths.managed_asset_state_dir / "cliamp-selection.json"
        selection_state.write_text("not json\n")

        payload = Service(self.paths).set_enabled("cliamp", False, refresh=False)

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["cleanupIncomplete"])
        self.assertTrue(target.is_file())
        self.assertTrue(selection_state.is_file())

    def test_cliamp_colors_only_second_run_is_unchanged(self):
        self.write_palette()

        first = apply("cliamp", self.paths)
        second = apply("cliamp", self.paths)

        self.assertEqual(first.status, "unchanged")
        self.assertEqual(second.status, "unchanged")
        self.assertFalse((self.paths.config_home / "cliamp/themes/omarchy.toml").exists())

    def test_cliamp_colors_only_cleanup_remains_actionable_without_cliamp(self):
        self.write_palette()

        ready, missing, _warnings = inspect_readiness(
            "cliamp", self.paths, which=lambda _command: None
        )

        self.assertTrue(ready)
        self.assertEqual(missing, [])

    def test_cliamp_readiness_ignores_palette_and_requires_app_only_for_marked_override(self):
        self.write_palette()
        colors = self.paths.current_theme / "colors.toml"
        colors.write_text(colors.read_text().replace('red = "#cc4444"', 'red = "not-a-color"'))

        native_ready, native_missing, _warnings = inspect_readiness(
            "cliamp", self.paths, which=lambda _command: None
        )
        self.assertTrue(native_ready)
        self.assertEqual(native_missing, [])

        (self.paths.current_theme / "cliamp.toml").write_text(
            '# thpm:cliamp-use-native\n'
            'accent = "#020202"\nbright_fg = "#030303"\nfg = "#040404"\n'
            'green = "#050505"\nyellow = "#060606"\nred = "#070707"\n'
        )
        unavailable, authored_missing, _warnings = inspect_readiness(
            "cliamp", self.paths, which=lambda _command: None
        )
        available, ready_missing, _warnings = inspect_readiness(
            "cliamp", self.paths, which=lambda _command: "/usr/bin/cliamp"
        )

        self.assertFalse(unavailable)
        self.assertEqual(authored_missing, ["cliamp"])
        self.assertTrue(available)
        self.assertEqual(ready_missing, [])

    def test_cliamp_invalid_palette_is_ignored_and_preserves_user_theme(self):
        self.write_palette()
        colors = self.paths.current_theme / "colors.toml"
        colors.write_text(colors.read_text().replace('red = "#cc4444"', 'red = "invalid"'))
        target = self.paths.config_home / "cliamp/themes/omarchy.toml"
        target.parent.mkdir(parents=True)
        target.write_text("user theme\n")

        result = apply("cliamp", self.paths)

        self.assertEqual(result.status, "unchanged")
        self.assertEqual(target.read_text(), "user theme\n")

    def test_cliamp_authored_theme_cleanup_restores_prior_file(self):
        source = self.paths.current_theme / "cliamp.toml"
        source.parent.mkdir(parents=True)
        source.write_text(
            '# thpm:cliamp-use-native\n'
            'accent = "#020202"\nbright_fg = "#030303"\nfg = "#040404"\n'
            'green = "#050505"\nyellow = "#060606"\nred = "#070707"\n'
        )
        target = self.paths.config_home / "cliamp/themes/omarchy.toml"
        target.parent.mkdir(parents=True)
        target.write_text("user theme\n")

        apply("cliamp", self.paths)
        source.unlink()
        result = apply("cliamp", self.paths)

        self.assertEqual(result.status, "applied")
        self.assertEqual(target.read_text(), "user theme\n")

    def test_cliamp_authored_theme_cleanup_preserves_later_user_edit(self):
        source = self.paths.current_theme / "cliamp.toml"
        source.parent.mkdir(parents=True)
        source.write_text(
            '# thpm:cliamp-use-native\n'
            'accent = "#020202"\nbright_fg = "#030303"\nfg = "#040404"\n'
            'green = "#050505"\nyellow = "#060606"\nred = "#070707"\n'
        )
        target = self.paths.config_home / "cliamp/themes/omarchy.toml"

        apply("cliamp", self.paths)
        target.write_text("user changed authored theme\n")
        source.unlink()
        result = apply("cliamp", self.paths)

        self.assertEqual(result.status, "applied")
        self.assertEqual(target.read_text(), "user changed authored theme\n")
        self.assertTrue(
            any("preserved user-modified file" in warning for warning in result.warnings)
        )

    def test_obsidian_terminal_updates_discovered_vault_and_preserves_settings(self):
        self.write_palette()
        vault = self.paths.home / "Documents/My Vault"
        settings = vault / ".obsidian/plugins/terminal/data.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "preferredRenderer": "webgl",
                    "terminalOptions": {"fontSize": 14, "theme": {"background": "#000000"}},
                }
            )
        )
        registry = self.paths.config_home / "obsidian/obsidian.json"
        registry.parent.mkdir(parents=True)
        registry.write_text(json.dumps({"vaults": {"one": {"path": str(vault)}}}))
        colors = {
            **COLORS,
            "accent": "#abcdef",
            "cursor": "#fedcba",
            "selection_background": "#123456",
            "selection_foreground": "#654321",
        }

        with patch("thpm.integrations.load_palette", return_value=colors):
            result = apply("obsidian-terminal", self.paths)
            unchanged = apply("obsidian-terminal", self.paths)

        document = json.loads(settings.read_text())
        theme = document["terminalOptions"]["theme"]
        self.assertEqual(result.status, "applied")
        self.assertEqual(result.changed, [str(settings)])
        self.assertEqual(result.restartRequired, ["Obsidian"])
        self.assertEqual(unchanged.status, "unchanged")
        self.assertEqual(document["preferredRenderer"], "webgl")
        self.assertEqual(document["terminalOptions"]["fontSize"], 14)
        self.assertEqual(theme["background"], COLORS["bg"])
        self.assertEqual(theme["foreground"], COLORS["fg"])
        self.assertEqual(theme["cursor"], "#fedcba")
        self.assertEqual(theme["selectionBackground"], "#123456")
        self.assertEqual(theme["selectionForeground"], "#654321")
        self.assertEqual(theme["brightWhite"], COLORS["bright_fg"])

    def test_obsidian_terminal_disables_profile_follow_theme_that_overrides_palette(self):
        self.write_palette()
        settings = self.paths.home / "vault/.obsidian/plugins/terminal/data.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "profiles": {
                        "linuxIntegratedDefault": {
                            "type": "integrated",
                            "followTheme": True,
                            "terminalOptions": {"fontFamily": "monospace"},
                        },
                        "invalidProfile": "preserve me",
                    },
                    "terminalOptions": {"fontSize": 14},
                }
            )
        )

        with patch.dict(
            os.environ, {"OBSIDIAN_TERMINAL_DATA_JSON": str(settings)}
        ):
            result = apply("obsidian-terminal", self.paths)
            applied_stat = settings.stat()
            unchanged = apply("obsidian-terminal", self.paths)

        document = json.loads(settings.read_text())
        profile = document["profiles"]["linuxIntegratedDefault"]
        self.assertEqual(result.status, "applied")
        self.assertEqual(unchanged.status, "unchanged")
        self.assertEqual(settings.stat().st_ino, applied_stat.st_ino)
        self.assertEqual(settings.stat().st_mtime_ns, applied_stat.st_mtime_ns)
        self.assertFalse(profile["followTheme"])
        self.assertEqual(profile["terminalOptions"], {"fontFamily": "monospace"})
        self.assertEqual(document["profiles"]["invalidProfile"], "preserve me")
        self.assertEqual(document["terminalOptions"]["fontSize"], 14)

    def test_disabling_obsidian_terminal_restores_follow_theme_and_preserves_later_edits(self):
        self.write_palette()
        settings = self.paths.home / "vault/.obsidian/plugins/terminal/data.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "profiles": {
                        "linuxIntegratedDefault": {
                            "followTheme": True,
                            "terminalOptions": {"fontFamily": "monospace"},
                        },
                        "userOwnedFalse": {"followTheme": False},
                    },
                    "terminalOptions": {"fontSize": 14},
                }
            )
        )
        self.paths.state_file.parent.mkdir(parents=True)
        self.paths.state_file.write_text(
            'version = 1\n\n[plugins]\nobsidian-terminal = true\n'
        )

        with patch.dict(
            os.environ, {"OBSIDIAN_TERMINAL_DATA_JSON": str(settings)}
        ):
            apply("obsidian-terminal", self.paths)
            document = json.loads(settings.read_text())
            document["preferredRenderer"] = "webgl"
            settings.write_text(json.dumps(document))
            payload = Service(self.paths).set_enabled(
                "obsidian-terminal", False, refresh=False
            )

        restored = json.loads(settings.read_text())
        self.assertTrue(restored["profiles"]["linuxIntegratedDefault"]["followTheme"])
        self.assertFalse(restored["profiles"]["userOwnedFalse"]["followTheme"])
        self.assertEqual(restored["preferredRenderer"], "webgl")
        self.assertIn(str(settings), payload["changed"])
        self.assertEqual(payload["restartRequired"], ["Obsidian"])

    def test_disabling_obsidian_terminal_retains_state_for_missing_vault(self):
        self.write_palette()
        settings = self.paths.home / "vault/.obsidian/plugins/terminal/data.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "profiles": {
                        "linuxIntegratedDefault": {"followTheme": True}
                    },
                    "terminalOptions": {},
                }
            )
        )
        self.paths.state_file.parent.mkdir(parents=True)
        self.paths.state_file.write_text(
            'version = 1\n\n[plugins]\nobsidian-terminal = true\n'
        )
        restoration_state = (
            self.paths.thpm_state_dir / "obsidian-terminal-follow-theme.json"
        )

        with patch.dict(
            os.environ, {"OBSIDIAN_TERMINAL_DATA_JSON": str(settings)}
        ):
            apply("obsidian-terminal", self.paths)
            state_before = restoration_state.read_bytes()
            settings.unlink()
            payload = Service(self.paths).set_enabled(
                "obsidian-terminal", False, refresh=False
            )

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["cleanupIncomplete"])
        self.assertIn(str(settings), payload["retainedPaths"])
        self.assertTrue(any(str(settings) in str(item) for item in payload["residuals"]))
        self.assertEqual(restoration_state.read_bytes(), state_before)
        self.assertEqual(payload["restartRequired"], [])

    def test_disabling_obsidian_terminal_reports_restoration_write_failure(self):
        self.write_palette()
        settings = self.paths.home / "vault/.obsidian/plugins/terminal/data.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "profiles": {
                        "linuxIntegratedDefault": {"followTheme": True}
                    },
                    "terminalOptions": {},
                }
            )
        )
        self.paths.state_file.parent.mkdir(parents=True)
        self.paths.state_file.write_text(
            'version = 1\n\n[plugins]\nobsidian-terminal = true\n'
        )
        restoration_state = (
            self.paths.thpm_state_dir / "obsidian-terminal-follow-theme.json"
        )

        with patch.dict(
            os.environ, {"OBSIDIAN_TERMINAL_DATA_JSON": str(settings)}
        ):
            apply("obsidian-terminal", self.paths)
            state_before = restoration_state.read_bytes()
            with patch(
                "thpm.integrations.atomic_text", side_effect=OSError("disk full")
            ):
                payload = Service(self.paths).set_enabled(
                    "obsidian-terminal", False, refresh=False
                )

        current = json.loads(settings.read_text())
        self.assertFalse(current["profiles"]["linuxIntegratedDefault"]["followTheme"])
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["cleanupIncomplete"])
        self.assertIn(str(settings), payload["changed"])
        self.assertIn(str(settings), payload["retainedPaths"])
        self.assertEqual(restoration_state.read_bytes(), state_before)
        self.assertEqual(payload["restartRequired"], ["Obsidian"])

    def test_disabling_obsidian_terminal_reports_post_replace_restoration_failure(self):
        self.write_palette()
        settings = self.paths.home / "vault/.obsidian/plugins/terminal/data.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "profiles": {
                        "linuxIntegratedDefault": {"followTheme": True}
                    },
                    "terminalOptions": {},
                }
            )
        )
        with patch.dict(
            os.environ, {"OBSIDIAN_TERMINAL_DATA_JSON": str(settings)}
        ):
            apply("obsidian-terminal", self.paths)
        restoration_state = (
            self.paths.thpm_state_dir / "obsidian-terminal-follow-theme.json"
        )
        self.assertTrue(restoration_state.is_file())
        from thpm import integrations as integrations_module

        real_atomic_text = integrations_module.atomic_text
        settings_writes = 0

        def raise_after_restoration_replace(path, text, mode=0o644):
            nonlocal settings_writes
            result = real_atomic_text(path, text, mode)
            if path == settings:
                settings_writes += 1
                if settings_writes == 1:
                    raise OSError("post-replace restoration failure")
            return result

        self.paths.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.paths.state_file.write_text(
            'version = 1\n\n[plugins]\nobsidian-terminal = true\n'
        )
        with patch(
            "thpm.integrations.atomic_text",
            side_effect=raise_after_restoration_replace,
        ):
            payload = Service(self.paths).set_enabled(
                "obsidian-terminal", False, refresh=False
            )

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["cleanupIncomplete"])
        self.assertIn(str(settings), payload["changed"])
        self.assertIn(str(settings), payload["retainedPaths"])
        self.assertEqual(payload["restartRequired"], ["Obsidian"])
        self.assertTrue(restoration_state.is_file())

    def test_obsidian_terminal_apply_reports_incomplete_rollback(self):
        self.write_palette()
        first = self.paths.home / "first/.obsidian/plugins/terminal/data.json"
        second = self.paths.home / "second/.obsidian/plugins/terminal/data.json"
        for settings in (first, second):
            settings.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps(
                    {
                        "profiles": {
                            "linuxIntegratedDefault": {"followTheme": True}
                        },
                        "terminalOptions": {},
                    }
                )
            )
        restoration_state = (
            self.paths.thpm_state_dir / "obsidian-terminal-follow-theme.json"
        )
        from thpm import integrations as integrations_module

        real_atomic_text = integrations_module.atomic_text
        first_writes = 0

        def fail_second_write_and_first_rollback(path, text, mode=0o644):
            nonlocal first_writes
            if path == first:
                first_writes += 1
                if first_writes == 2:
                    raise OSError("rollback blocked")
            if path == second:
                raise OSError("second write blocked")
            return real_atomic_text(path, text, mode)

        with patch.dict(
            os.environ,
            {"OBSIDIAN_TERMINAL_DATA_JSON": os.pathsep.join((str(first), str(second)))},
        ), patch(
            "thpm.integrations.atomic_text",
            side_effect=fail_second_write_and_first_rollback,
        ), self.assertRaisesRegex(ApplyFailure, "rollback incomplete") as raised:
            apply("obsidian-terminal", self.paths)

        current = json.loads(first.read_text())
        self.assertFalse(current["profiles"]["linuxIntegratedDefault"]["followTheme"])
        self.assertEqual(raised.exception.changed, [str(second), str(first)])
        self.assertEqual(raised.exception.restart_required, ["Obsidian"])
        self.assertTrue(restoration_state.is_file())
        self.assertIn(str(first), restoration_state.read_text())

    def test_obsidian_terminal_apply_reports_state_only_rollback_failure(self):
        self.write_palette()
        settings = self.paths.home / "vault/.obsidian/plugins/terminal/data.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "profiles": {
                        "linuxIntegratedDefault": {"followTheme": True}
                    },
                    "terminalOptions": {},
                }
            )
        )
        restoration_state = (
            self.paths.thpm_state_dir / "obsidian-terminal-follow-theme.json"
        )
        restoration_state.parent.mkdir(parents=True, exist_ok=True)
        restoration_state.write_text('{"version": 1, "files": {}}\n')
        state_before = restoration_state.read_bytes()
        from thpm import integrations as integrations_module

        real_atomic_text = integrations_module.atomic_text
        state_writes = 0
        settings_writes = 0

        def fail_settings_and_state_rollback(path, text, mode=0o644):
            nonlocal settings_writes, state_writes
            if path == restoration_state:
                state_writes += 1
                if state_writes == 2:
                    raise OSError("state rollback blocked")
            if path == settings:
                settings_writes += 1
                if settings_writes == 1:
                    raise OSError("settings write blocked")
            return real_atomic_text(path, text, mode)

        with patch.dict(
            os.environ, {"OBSIDIAN_TERMINAL_DATA_JSON": str(settings)}
        ), patch(
            "thpm.integrations.atomic_text",
            side_effect=fail_settings_and_state_rollback,
        ), self.assertRaisesRegex(ApplyFailure, "rollback incomplete") as raised:
            apply("obsidian-terminal", self.paths)

        self.assertEqual(raised.exception.changed, [str(restoration_state)])
        self.assertEqual(raised.exception.restart_required, [])
        self.assertNotEqual(restoration_state.read_bytes(), state_before)
        self.assertIn(str(settings), restoration_state.read_text())

    def test_disabling_obsidian_terminal_preserves_user_modified_follow_theme(self):
        self.write_palette()
        settings = self.paths.home / "vault/.obsidian/plugins/terminal/data.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "profiles": {
                        "linuxIntegratedDefault": {"followTheme": True}
                    },
                    "terminalOptions": {},
                }
            )
        )
        self.paths.state_file.parent.mkdir(parents=True)
        self.paths.state_file.write_text(
            'version = 1\n\n[plugins]\nobsidian-terminal = true\n'
        )
        restoration_state = (
            self.paths.thpm_state_dir / "obsidian-terminal-follow-theme.json"
        )

        with patch.dict(
            os.environ, {"OBSIDIAN_TERMINAL_DATA_JSON": str(settings)}
        ):
            apply("obsidian-terminal", self.paths)
            document = json.loads(settings.read_text())
            document["profiles"]["linuxIntegratedDefault"]["followTheme"] = "manual"
            settings.write_text(json.dumps(document))
            before = settings.read_bytes()
            payload = Service(self.paths).set_enabled(
                "obsidian-terminal", False, refresh=False
            )

        self.assertTrue(payload["ok"])
        self.assertEqual(settings.read_bytes(), before)
        self.assertFalse(restoration_state.exists())
        self.assertEqual(payload["restartRequired"], [])
        self.assertTrue(
            any(
                "preserved user-modified Obsidian Terminal profile"
                in warning["message"]
                for warning in payload["warnings"]
            )
        )

    def test_corrupt_obsidian_terminal_state_blocks_apply_and_cleanup(self):
        self.write_palette()
        settings = self.paths.home / "vault/.obsidian/plugins/terminal/data.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "profiles": {
                        "linuxIntegratedDefault": {"followTheme": True}
                    },
                    "terminalOptions": {},
                }
            )
        )
        self.paths.state_file.parent.mkdir(parents=True)
        self.paths.state_file.write_text(
            'version = 1\n\n[plugins]\nobsidian-terminal = true\n'
        )
        restoration_state = (
            self.paths.thpm_state_dir / "obsidian-terminal-follow-theme.json"
        )

        with patch.dict(
            os.environ, {"OBSIDIAN_TERMINAL_DATA_JSON": str(settings)}
        ):
            apply("obsidian-terminal", self.paths)
            restoration_state.write_text("not json\n")
            settings_before = settings.read_bytes()
            with self.assertRaisesRegex(
                RuntimeError, "invalid Obsidian Terminal restoration state"
            ):
                apply("obsidian-terminal", self.paths)
            payload = Service(self.paths).set_enabled(
                "obsidian-terminal", False, refresh=False
            )

        self.assertEqual(settings.read_bytes(), settings_before)
        self.assertEqual(restoration_state.read_text(), "not json\n")
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["cleanupIncomplete"])
        self.assertIn(str(restoration_state), payload["retainedPaths"])
        self.assertEqual(payload["restartRequired"], [])

    def test_obsidian_terminal_state_cannot_target_arbitrary_json(self):
        target = self.paths.home / "other-application.json"
        target.write_text(
            json.dumps(
                {
                    "profiles": {"default": {"followTheme": False}},
                    "sentinel": "unrelated",
                }
            )
        )
        before = target.read_bytes()
        self.paths.state_file.parent.mkdir(parents=True)
        self.paths.state_file.write_text(
            'version = 1\n\n[plugins]\nobsidian-terminal = true\n'
        )
        restoration_state = (
            self.paths.thpm_state_dir / "obsidian-terminal-follow-theme.json"
        )
        restoration_state.parent.mkdir(parents=True, exist_ok=True)
        restoration_state.write_text(
            json.dumps(
                {
                    "version": 1,
                    "files": {str(target): ["default"]},
                }
            )
        )

        payload = Service(self.paths).set_enabled(
            "obsidian-terminal", False, refresh=False
        )

        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(json.loads(target.read_text())["sentinel"], "unrelated")
        self.assertEqual(
            json.loads(target.read_text())["profiles"]["default"]["followTheme"],
            False,
        )
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["cleanupIncomplete"])
        self.assertTrue(restoration_state.is_file())
        self.assertIn(str(restoration_state), payload["retainedPaths"])
        self.assertEqual(payload["restartRequired"], [])

    def test_obsidian_terminal_apply_refuses_dangling_state_symlink(self):
        self.write_palette()
        settings = self.paths.home / "vault/.obsidian/plugins/terminal/data.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "profiles": {
                        "linuxIntegratedDefault": {"followTheme": True}
                    },
                    "terminalOptions": {},
                }
            )
        )
        before = settings.read_bytes()
        restoration_state = (
            self.paths.thpm_state_dir / "obsidian-terminal-follow-theme.json"
        )
        restoration_state.parent.mkdir(parents=True, exist_ok=True)
        restoration_state.symlink_to(restoration_state.parent / "missing-state.json")

        with patch.dict(
            os.environ, {"OBSIDIAN_TERMINAL_DATA_JSON": str(settings)}
        ), self.assertRaisesRegex(
            RuntimeError, "unsafe Obsidian Terminal restoration state path"
        ):
            apply("obsidian-terminal", self.paths)

        self.assertTrue(restoration_state.is_symlink())
        self.assertEqual(settings.read_bytes(), before)

    def test_obsidian_terminal_apply_rejects_symlinked_state_ancestor(self):
        self.write_palette()
        settings = self.paths.home / "vault/.obsidian/plugins/terminal/data.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "profiles": {
                        "linuxIntegratedDefault": {"followTheme": True}
                    },
                    "terminalOptions": {},
                }
            )
        )
        before = settings.read_bytes()
        external_state = self.paths.home / "external-state"
        external_state.mkdir()
        self.paths.thpm_state_dir.parent.mkdir(parents=True, exist_ok=True)
        self.paths.thpm_state_dir.symlink_to(external_state, target_is_directory=True)
        restoration_state = (
            self.paths.thpm_state_dir / "obsidian-terminal-follow-theme.json"
        )

        with patch.dict(
            os.environ, {"OBSIDIAN_TERMINAL_DATA_JSON": str(settings)}
        ), self.assertRaisesRegex(
            RuntimeError, "unsafe Obsidian Terminal restoration state path"
        ):
            apply("obsidian-terminal", self.paths)

        self.assertEqual(settings.read_bytes(), before)
        self.assertFalse((external_state / restoration_state.name).exists())
        self.assertTrue(self.paths.thpm_state_dir.is_symlink())

    def test_disabling_obsidian_terminal_rejects_symlinked_state_ancestor(self):
        settings = self.paths.home / "vault/.obsidian/plugins/terminal/data.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "profiles": {
                        "linuxIntegratedDefault": {"followTheme": False}
                    },
                    "terminalOptions": {},
                }
            )
        )
        before = settings.read_bytes()
        external_state = self.paths.home / "external-state"
        external_state.mkdir()
        self.paths.thpm_state_dir.parent.mkdir(parents=True, exist_ok=True)
        self.paths.thpm_state_dir.symlink_to(external_state, target_is_directory=True)
        restoration_state = (
            self.paths.thpm_state_dir / "obsidian-terminal-follow-theme.json"
        )
        restoration_state.write_text(
            json.dumps(
                {
                    "version": 1,
                    "files": {str(settings): ["linuxIntegratedDefault"]},
                }
            )
        )
        state_before = restoration_state.read_bytes()
        self.paths.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.paths.state_file.write_text(
            'version = 1\n\n[plugins]\nobsidian-terminal = true\n'
        )

        payload = Service(self.paths).set_enabled(
            "obsidian-terminal", False, refresh=False
        )

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["cleanupIncomplete"])
        self.assertIn(str(restoration_state), payload["retainedPaths"])
        self.assertEqual(settings.read_bytes(), before)
        self.assertEqual(restoration_state.read_bytes(), state_before)
        self.assertEqual(payload["restartRequired"], [])
        self.assertTrue(self.paths.thpm_state_dir.is_symlink())

    def test_obsidian_terminal_apply_rejects_nonconforming_direct_override(self):
        self.write_palette()
        settings = self.paths.home / "custom-terminal-settings.json"
        settings.write_text(
            json.dumps(
                {
                    "profiles": {
                        "linuxIntegratedDefault": {"followTheme": True}
                    },
                    "terminalOptions": {},
                }
            )
        )
        before = settings.read_bytes()
        restoration_state = (
            self.paths.thpm_state_dir / "obsidian-terminal-follow-theme.json"
        )

        with patch.dict(
            os.environ, {"OBSIDIAN_TERMINAL_DATA_JSON": str(settings)}
        ), self.assertRaisesRegex(
            ValueError, "unsafe Obsidian Terminal settings path"
        ):
            apply("obsidian-terminal", self.paths)

        self.assertEqual(settings.read_bytes(), before)
        self.assertFalse(restoration_state.exists())

    def test_obsidian_terminal_apply_rejects_symlinked_path_ancestor(self):
        self.write_palette()
        external = self.paths.home / "external-obsidian"
        settings = external / "plugins/terminal/data.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "profiles": {
                        "linuxIntegratedDefault": {"followTheme": True}
                    },
                    "terminalOptions": {},
                }
            )
        )
        before = settings.read_bytes()
        vault = self.paths.home / "vault"
        vault.mkdir()
        (vault / ".obsidian").symlink_to(external, target_is_directory=True)
        redirected = vault / ".obsidian/plugins/terminal/data.json"
        restoration_state = (
            self.paths.thpm_state_dir / "obsidian-terminal-follow-theme.json"
        )

        with patch.dict(
            os.environ, {"OBSIDIAN_TERMINAL_DATA_JSON": str(redirected)}
        ), self.assertRaisesRegex(
            ValueError, "unsafe Obsidian Terminal settings path"
        ):
            apply("obsidian-terminal", self.paths)

        self.assertEqual(settings.read_bytes(), before)
        self.assertFalse(restoration_state.exists())

    def test_obsidian_terminal_apply_rejects_relative_override_traversal(self):
        self.write_palette()
        settings = self.paths.home / "vault/.obsidian/plugins/terminal/data.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "profiles": {
                        "linuxIntegratedDefault": {"followTheme": True}
                    },
                    "terminalOptions": {},
                }
            )
        )
        before = settings.read_bytes()
        restoration_state = (
            self.paths.thpm_state_dir / "obsidian-terminal-follow-theme.json"
        )
        relative = os.path.relpath(settings, Path.cwd())
        self.assertIn("..", Path(relative).parts)

        with patch.dict(
            os.environ, {"OBSIDIAN_TERMINAL_DATA_JSON": relative}
        ), self.assertRaisesRegex(ValueError, "unsafe Obsidian Terminal settings path"):
            apply("obsidian-terminal", self.paths)

        self.assertEqual(settings.read_bytes(), before)
        self.assertFalse(restoration_state.exists())

    def test_obsidian_terminal_apply_rolls_back_write_that_raises_after_replace(self):
        self.write_palette()
        settings = self.paths.home / "vault/.obsidian/plugins/terminal/data.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "profiles": {
                        "linuxIntegratedDefault": {"followTheme": True}
                    },
                    "terminalOptions": {},
                }
            )
        )
        before = settings.read_bytes()
        restoration_state = (
            self.paths.thpm_state_dir / "obsidian-terminal-follow-theme.json"
        )
        from thpm import integrations as integrations_module

        real_atomic_text = integrations_module.atomic_text
        settings_writes = 0

        def raise_after_settings_replace(path, text, mode=0o644):
            nonlocal settings_writes
            result = real_atomic_text(path, text, mode)
            if path == settings:
                settings_writes += 1
                if settings_writes == 1:
                    raise OSError("post-replace settings failure")
            return result

        with patch.dict(
            os.environ, {"OBSIDIAN_TERMINAL_DATA_JSON": str(settings)}
        ), patch(
            "thpm.integrations.atomic_text",
            side_effect=raise_after_settings_replace,
        ), self.assertRaisesRegex(OSError, "post-replace settings failure"):
            apply("obsidian-terminal", self.paths)

        self.assertEqual(settings.read_bytes(), before)
        self.assertFalse(restoration_state.exists())

    def test_obsidian_terminal_apply_rolls_back_state_write_that_raises_after_replace(self):
        self.write_palette()
        settings = self.paths.home / "vault/.obsidian/plugins/terminal/data.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "profiles": {
                        "linuxIntegratedDefault": {"followTheme": True}
                    },
                    "terminalOptions": {},
                }
            )
        )
        before = settings.read_bytes()
        restoration_state = (
            self.paths.thpm_state_dir / "obsidian-terminal-follow-theme.json"
        )
        from thpm import integrations as integrations_module

        real_atomic_text = integrations_module.atomic_text
        state_writes = 0

        def raise_after_state_replace(path, text, mode=0o644):
            nonlocal state_writes
            result = real_atomic_text(path, text, mode)
            if path == restoration_state:
                state_writes += 1
                if state_writes == 1:
                    raise OSError("post-replace state failure")
            return result

        with patch.dict(
            os.environ, {"OBSIDIAN_TERMINAL_DATA_JSON": str(settings)}
        ), patch(
            "thpm.integrations.atomic_text",
            side_effect=raise_after_state_replace,
        ), self.assertRaisesRegex(OSError, "post-replace state failure"):
            apply("obsidian-terminal", self.paths)

        self.assertEqual(settings.read_bytes(), before)
        self.assertFalse(restoration_state.exists())

    def test_obsidian_terminal_apply_revalidates_path_before_write(self):
        self.write_palette()
        vault = self.paths.home / "vault"
        settings = vault / ".obsidian/plugins/terminal/data.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "profiles": {
                        "linuxIntegratedDefault": {"followTheme": True}
                    },
                    "terminalOptions": {},
                }
            )
        )
        original_before = settings.read_bytes()
        external = self.paths.home / "external-obsidian"
        redirected = external / "plugins/terminal/data.json"
        redirected.parent.mkdir(parents=True)
        redirected.write_text(
            json.dumps(
                {
                    "profiles": {
                        "linuxIntegratedDefault": {"followTheme": True}
                    },
                    "terminalOptions": {},
                    "sentinel": "external",
                }
            )
        )
        redirected_before = redirected.read_bytes()
        restoration_state = (
            self.paths.thpm_state_dir / "obsidian-terminal-follow-theme.json"
        )
        from thpm import integrations as integrations_module

        real_atomic_text = integrations_module.atomic_text

        def swap_ancestor_after_state_write(path, text, mode=0o644):
            result = real_atomic_text(path, text, mode)
            if path == restoration_state:
                (vault / ".obsidian").rename(vault / ".obsidian-original")
                (vault / ".obsidian").symlink_to(external, target_is_directory=True)
            return result

        with patch.dict(
            os.environ, {"OBSIDIAN_TERMINAL_DATA_JSON": str(settings)}
        ), patch(
            "thpm.integrations.atomic_text",
            side_effect=swap_ancestor_after_state_write,
        ), self.assertRaisesRegex(
            ValueError, "unsafe Obsidian Terminal settings path"
        ):
            apply("obsidian-terminal", self.paths)

        self.assertEqual(redirected.read_bytes(), redirected_before)
        self.assertEqual(
            (vault / ".obsidian-original/plugins/terminal/data.json").read_bytes(),
            original_before,
        )
        self.assertFalse(restoration_state.exists())

    def test_disabling_obsidian_terminal_retains_state_for_malformed_profiles(self):
        self.write_palette()
        settings = self.paths.home / "vault/.obsidian/plugins/terminal/data.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "profiles": {
                        "linuxIntegratedDefault": {"followTheme": True}
                    },
                    "terminalOptions": {},
                }
            )
        )
        self.paths.state_file.parent.mkdir(parents=True)
        self.paths.state_file.write_text(
            'version = 1\n\n[plugins]\nobsidian-terminal = true\n'
        )
        restoration_state = (
            self.paths.thpm_state_dir / "obsidian-terminal-follow-theme.json"
        )

        with patch.dict(
            os.environ, {"OBSIDIAN_TERMINAL_DATA_JSON": str(settings)}
        ):
            apply("obsidian-terminal", self.paths)
            document = json.loads(settings.read_text())
            document["profiles"] = []
            settings.write_text(json.dumps(document))
            before = settings.read_bytes()
            state_before = restoration_state.read_bytes()
            payload = Service(self.paths).set_enabled(
                "obsidian-terminal", False, refresh=False
            )

        self.assertEqual(settings.read_bytes(), before)
        self.assertEqual(restoration_state.read_bytes(), state_before)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["cleanupIncomplete"])
        self.assertIn(str(settings), payload["retainedPaths"])
        self.assertEqual(payload["restartRequired"], [])

    def test_disabling_obsidian_terminal_retains_state_for_missing_owned_profile(self):
        self.write_palette()
        settings = self.paths.home / "vault/.obsidian/plugins/terminal/data.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "profiles": {
                        "linuxIntegratedDefault": {"followTheme": True}
                    },
                    "terminalOptions": {},
                }
            )
        )
        self.paths.state_file.parent.mkdir(parents=True)
        self.paths.state_file.write_text(
            'version = 1\n\n[plugins]\nobsidian-terminal = true\n'
        )
        restoration_state = (
            self.paths.thpm_state_dir / "obsidian-terminal-follow-theme.json"
        )

        with patch.dict(
            os.environ, {"OBSIDIAN_TERMINAL_DATA_JSON": str(settings)}
        ):
            apply("obsidian-terminal", self.paths)
            document = json.loads(settings.read_text())
            document["profiles"].pop("linuxIntegratedDefault")
            settings.write_text(json.dumps(document))
            before = settings.read_bytes()
            state_before = restoration_state.read_bytes()
            payload = Service(self.paths).set_enabled(
                "obsidian-terminal", False, refresh=False
            )

        self.assertEqual(settings.read_bytes(), before)
        self.assertEqual(restoration_state.read_bytes(), state_before)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["cleanupIncomplete"])
        self.assertIn(str(settings), payload["retainedPaths"])
        self.assertEqual(payload["restartRequired"], [])

    def test_disabling_obsidian_terminal_reports_dangling_state_symlink(self):
        self.paths.state_file.parent.mkdir(parents=True)
        self.paths.state_file.write_text(
            'version = 1\n\n[plugins]\nobsidian-terminal = true\n'
        )
        restoration_state = (
            self.paths.thpm_state_dir / "obsidian-terminal-follow-theme.json"
        )
        restoration_state.symlink_to(restoration_state.parent / "missing-state.json")

        payload = Service(self.paths).set_enabled(
            "obsidian-terminal", False, refresh=False
        )

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["cleanupIncomplete"])
        self.assertTrue(restoration_state.is_symlink())
        self.assertIn(str(restoration_state), payload["retainedPaths"])
        self.assertEqual(payload["restartRequired"], [])

    def test_uninstall_reports_dangling_obsidian_terminal_state_symlink(self):
        self.paths.state_file.parent.mkdir(parents=True)
        self.paths.state_file.write_text(
            'version = 1\n\n[plugins]\nobsidian-terminal = true\n'
        )
        restoration_state = (
            self.paths.thpm_state_dir / "obsidian-terminal-follow-theme.json"
        )
        restoration_state.symlink_to(restoration_state.parent / "missing-state.json")

        payload = Service(self.paths).uninstall()

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["cleanupIncomplete"])
        self.assertTrue(restoration_state.is_symlink())
        self.assertIn(str(restoration_state), payload["retainedPaths"])
        self.assertEqual(payload["restartRequired"], [])

    def test_uninstall_restores_obsidian_terminal_follow_theme(self):
        self.write_palette()
        settings = self.paths.home / "vault/.obsidian/plugins/terminal/data.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "profiles": {
                        "linuxIntegratedDefault": {"followTheme": True}
                    },
                    "terminalOptions": {},
                }
            )
        )

        with patch.dict(
            os.environ, {"OBSIDIAN_TERMINAL_DATA_JSON": str(settings)}
        ):
            apply("obsidian-terminal", self.paths)
            with patch("thpm.service.ui.remove", return_value={"installed": False}):
                payload = Service(self.paths).uninstall()

        restored = json.loads(settings.read_text())
        self.assertTrue(restored["profiles"]["linuxIntegratedDefault"]["followTheme"])
        self.assertIn(str(settings), payload["changed"])
        self.assertEqual(payload["restartRequired"], ["Obsidian"])

    def test_obsidian_terminal_readiness_reports_missing_or_invalid_settings(self):
        ready, missing, warnings = inspect_readiness(
            "obsidian-terminal", self.paths, which=lambda _command: "/bin/true"
        )
        self.assertFalse(ready)
        self.assertIn("OBSIDIAN_VAULT_PATH", " ".join(missing))
        self.assertEqual(warnings, [])

        settings = self.paths.home / "vault/.obsidian/plugins/terminal/data.json"
        settings.parent.mkdir(parents=True)
        settings.write_text("not json\n")
        with patch.dict(os.environ, {"OBSIDIAN_TERMINAL_DATA_JSON": str(settings)}):
            ready, missing, _warnings = inspect_readiness(
                "obsidian-terminal", self.paths, which=lambda _command: "/bin/true"
            )
        self.assertFalse(ready)
        self.assertIn("invalid Obsidian Terminal settings JSON", " ".join(missing))

    def test_pi_hot_reload_touches_synchronized_theme_without_replacing_it(self):
        content = '{"name":"omarchy-system"}\n'
        source = self.paths.current_theme / "pi.json"
        target = self.paths.home / ".pi/agent/themes/omarchy-system.json"
        source.parent.mkdir(parents=True)
        target.parent.mkdir(parents=True)
        source.write_text(content)
        target.write_text(content)
        os.utime(target, ns=(1_000_000_000, 1_000_000_000))
        inode = target.stat().st_ino

        result = apply("pi-hot-reload", self.paths)

        self.assertEqual(result.status, "applied")
        self.assertEqual(result.changed, [str(target)])
        self.assertEqual(result.message, "Pi omarchy-system theme change event emitted")
        self.assertEqual(target.stat().st_ino, inode)
        self.assertEqual(target.stat().st_atime_ns, 1_000_000_000)
        self.assertGreater(target.stat().st_mtime_ns, 1_000_000_000)
        self.assertEqual(target.read_text(), content)

    def test_pi_hot_reload_requires_native_generated_theme(self):
        ready, missing, warnings = inspect_readiness(
            "pi-hot-reload", self.paths, which=lambda _command: "/usr/bin/pi"
        )
        self.assertFalse(ready)
        self.assertIn("regular current Omarchy Pi theme source", " ".join(missing))
        self.assertIn("regular Omarchy-generated Pi theme", " ".join(missing))
        self.assertEqual(warnings, [])
        result = apply("pi-hot-reload", self.paths)
        self.assertEqual(result.status, "skipped")
        self.assertFalse((self.paths.home / ".pi").exists())

    def test_pi_hot_reload_refuses_stale_native_theme(self):
        source = self.paths.current_theme / "pi.json"
        target = self.paths.home / ".pi/agent/themes/omarchy-system.json"
        source.parent.mkdir(parents=True)
        target.parent.mkdir(parents=True)
        source.write_text("current theme\n")
        target.write_text("stale theme\n")
        os.utime(target, ns=(1_000_000_000, 2_000_000_000))
        before = target.stat()

        ready, missing, _warnings = inspect_readiness(
            "pi-hot-reload", self.paths, which=lambda _command: "/usr/bin/pi"
        )
        result = apply("pi-hot-reload", self.paths)

        self.assertFalse(ready)
        self.assertIn("Pi theme synchronized from the current Omarchy pi.json", missing)
        self.assertEqual(result.status, "skipped")
        self.assertIn("synchronization is stale", result.message)
        self.assertEqual(target.stat().st_atime_ns, before.st_atime_ns)
        self.assertEqual(target.stat().st_mtime_ns, before.st_mtime_ns)

    def test_pi_hot_reload_refuses_symlink_target(self):
        target = self.paths.home / ".pi/agent/themes/omarchy-system.json"
        source = self.paths.home / "user-theme.json"
        target.parent.mkdir(parents=True)
        source.write_text("user theme\n")
        target.symlink_to(source)

        with self.assertRaisesRegex(RuntimeError, "refusing symlink theme target"):
            apply("pi-hot-reload", self.paths)
        self.assertEqual(source.read_text(), "user theme\n")

    def test_pi_hot_reload_refuses_symlink_source(self):
        source = self.paths.current_theme / "pi.json"
        authored = self.paths.home / "authored-theme.json"
        target = self.paths.home / ".pi/agent/themes/omarchy-system.json"
        source.parent.mkdir(parents=True)
        target.parent.mkdir(parents=True)
        authored.write_text("authored theme\n")
        target.write_text("authored theme\n")
        source.symlink_to(authored)

        with self.assertRaisesRegex(RuntimeError, "refusing symlink theme source"):
            apply("pi-hot-reload", self.paths)
        self.assertEqual(authored.read_text(), "authored theme\n")

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

    def test_disabling_browser_restores_stylesheet_and_reports_restart(self):
        assets = Path(__file__).parents[1] / "assets"
        cases = (
            ("firefox", "Firefox", ".mozilla/firefox"),
            ("zen", "Zen Browser", ".zen"),
        )
        for plugin_id, label, base_name in cases:
            with self.subTest(plugin_id=plugin_id):
                base = self.paths.home / base_name
                profile = base / "profile.default"
                profile.mkdir(parents=True)
                (base / "profiles.ini").write_text(
                    "[Install1]\nDefault=profile.default\n"
                )
                source = self.paths.current_theme / f"thpm-{plugin_id}.css"
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text("theme css")
                managed = profile / f"chrome/thpm-{plugin_id}.css"
                managed.parent.mkdir(parents=True)
                managed.write_text("user css")
                apply(plugin_id, self.paths)
                enabled = load(self.paths)
                enabled[plugin_id] = True
                save(self.paths, enabled)
                with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
                    payload = Service(self.paths).set_enabled(
                        plugin_id, False, refresh=False
                    )
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["restartRequired"], [label])
                self.assertEqual(managed.read_text(), "user css")
                self.assertFalse((profile / "chrome/userChrome.css").exists())
                self.assertFalse(source.exists())

    def test_disabling_browser_without_profile_change_does_not_require_restart(self):
        source = self.paths.current_theme / "thpm-zen.css"
        source.parent.mkdir(parents=True)
        source.write_text("theme css")
        enabled = load(self.paths)
        enabled["zen"] = True
        save(self.paths, enabled)
        assets = Path(__file__).parents[1] / "assets"

        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            payload = Service(self.paths).set_enabled("zen", False, refresh=False)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["restartRequired"], [])
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
        self.assertEqual(result.warnings, [])
        saved = json.loads(self.paths.zellij_theme_state_file.read_text())
        self.assertEqual(saved["themeOption"], 'theme "current"')

    def test_zellij_generates_theme_from_colors_toml_without_authored_asset(self):
        self.write_palette()
        config = self.paths.config_home / "zellij/config.kdl"
        config.parent.mkdir(parents=True)
        config.write_text('theme "default"\n')
        with patch("thpm.palette.shutil.which", return_value=None):
            result = apply("zellij", self.paths)
        installed = self.paths.config_home / "zellij/themes/thpm.kdl"
        content = installed.read_text()
        self.assertIn("themes {\n    thpm-current {", content)
        self.assertIn("base 221 221 221", content)
        self.assertIn("background 17 17 17", content)
        self.assertIn("base 68 119 204", content)
        self.assertEqual(config.read_text(), 'theme "thpm-current"\n')
        self.assertIn(str(installed), result.changed)

    def test_zellij_authored_asset_takes_precedence_over_generated_palette(self):
        self.write_palette()
        source = self.paths.current_theme / "zellij.kdl"
        source.write_text('themes { authored { fg "white" } }\n')
        with patch("thpm.palette.shutil.which", return_value=None):
            apply("zellij", self.paths)
        installed = self.paths.config_home / "zellij/themes/thpm.kdl"
        self.assertEqual(
            installed.read_text(), 'themes { thpm-current { fg "white" } }\n'
        )

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
        self.assertEqual(result.warnings, [])

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
        self.assertTrue(target.exists())
        self.assertIn("preserved untracked Zellij theme", str(zellij["warnings"]))
        self.assertNotIn("restart active Zellij sessions", str(zellij["warnings"]))

    def test_zellij_preserves_an_already_normalized_theme_asset(self):
        theme_asset = self.paths.current_theme / "zellij.kdl"
        theme_asset.parent.mkdir(parents=True)
        theme_asset.write_text('themes { thpm-current { fg "#ffffff" } }\n')
        apply("zellij", self.paths)
        installed = self.paths.config_home / "zellij/themes/thpm.kdl"
        self.assertEqual(installed.read_bytes(), theme_asset.read_bytes())

    def test_zellij_without_asset_preserves_untracked_theme_and_restores_default(self):
        config = self.paths.config_home / "zellij/config.kdl"
        config.parent.mkdir(parents=True)
        config.write_text('theme "thpm-current"\npane_frames true\n')
        target = self.paths.config_home / "zellij/themes/thpm.kdl"
        target.parent.mkdir(parents=True)
        target.write_text('themes { thpm-current {} }\n')
        result = apply("zellij", self.paths)
        self.assertEqual(config.read_text(), "pane_frames true\n")
        self.assertTrue(target.exists())
        self.assertIn("preserved untracked Zellij theme", str(result.warnings))
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
        self.assertNotIn("restart active Zellij sessions", str(payload["warnings"]))

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

    def test_zellij_restores_displaced_theme_and_preserves_later_user_edits(self):
        source = self.paths.current_theme / "zellij.kdl"
        source.parent.mkdir(parents=True)
        source.write_text('themes { source { fg "white" } }\n')
        target = self.paths.config_home / "zellij/themes/thpm.kdl"
        target.parent.mkdir(parents=True)
        target.write_text("user theme\n")

        apply("zellij", self.paths)
        source.unlink()
        apply("zellij", self.paths)
        self.assertEqual(target.read_text(), "user theme\n")

        source.write_text('themes { source { fg "white" } }\n')
        apply("zellij", self.paths)
        target.write_text("user changed managed theme\n")
        source.unlink()
        result = apply("zellij", self.paths)
        self.assertEqual(target.read_text(), "user changed managed theme\n")
        self.assertIn("preserved user-modified file", str(result.warnings))

    def test_zellij_uses_environment_config_and_configured_theme_directory(self):
        source = self.paths.current_theme / "zellij.kdl"
        source.parent.mkdir(parents=True)
        source.write_text('themes { source { fg "white" } }\n')
        config_dir = self.paths.home / "custom-zellij"
        config = config_dir / "config.kdl"
        theme_dir = config_dir / "alternate-themes"
        config.parent.mkdir(parents=True)
        config.write_text(
            f"theme_dir {json.dumps(str(theme_dir))}; /* keep */\ntheme \"old\";\n"
        )
        with patch.dict(
            os.environ, {"ZELLIJ_CONFIG_DIR": str(config_dir)}, clear=True
        ):
            result = apply("zellij", self.paths)
            source.write_text('themes { source { fg "black" } }\n')
            refreshed = apply("zellij", self.paths)
        target = theme_dir / "thpm.kdl"
        self.assertTrue(target.is_file())
        self.assertIn(str(target), result.changed)
        self.assertIn(str(target), refreshed.changed)
        self.assertIn(str(config), refreshed.changed)
        self.assertEqual(
            config.read_text(),
            f"theme_dir {json.dumps(str(theme_dir))}; /* keep */\n"
            'theme "thpm-current";\n',
        )
        self.assertFalse((self.paths.config_home / "zellij/config.kdl").exists())
        source.unlink()
        apply("zellij", self.paths)
        self.assertEqual(
            config.read_text(),
            f"theme_dir {json.dumps(str(theme_dir))}; /* keep */\ntheme \"old\";\n",
        )
        self.assertFalse(target.exists())

    def test_zellij_uses_explicit_environment_config_file(self):
        source = self.paths.current_theme / "zellij.kdl"
        source.parent.mkdir(parents=True)
        source.write_text('themes { source { fg "white" } }\n')
        config = self.paths.home / "explicit-zellij/config.kdl"
        theme_dir = config.parent / "absolute-themes"
        config.parent.mkdir(parents=True)
        config.write_text(
            f"theme_dir {json.dumps(str(theme_dir))}\ntheme \"old\"\n"
        )

        with patch.dict(
            os.environ, {"ZELLIJ_CONFIG_FILE": str(config)}, clear=True
        ):
            apply("zellij", self.paths)
            source.write_text('themes { source { fg "black" } }\n')
            refreshed = apply("zellij", self.paths)

        self.assertEqual(
            config.read_text(),
            f"theme_dir {json.dumps(str(theme_dir))}\ntheme \"thpm-current\"\n",
        )
        self.assertIn(str(config), refreshed.changed)
        self.assertTrue((theme_dir / "thpm.kdl").is_file())

    def test_zellij_rejects_ambiguous_custom_theme_locations(self):
        source = self.paths.current_theme / "zellij.kdl"
        source.parent.mkdir(parents=True)
        source.write_text('themes { source { fg "white" } }\n')
        config = self.paths.home / "custom-zellij/config.kdl"
        config.parent.mkdir(parents=True)

        config.write_text('theme "old"\n')
        with patch.dict(
            os.environ, {"ZELLIJ_CONFIG_FILE": str(config)}, clear=True
        ), self.assertRaisesRegex(ValueError, "absolute root-level theme_dir"):
            apply("zellij", self.paths)

        config.write_text('theme_dir "relative-themes"\ntheme "old"\n')
        with patch.dict(
            os.environ, {"ZELLIJ_CONFIG_FILE": str(config)}, clear=True
        ), self.assertRaisesRegex(ValueError, "theme_dir must be absolute"):
            apply("zellij", self.paths)

    def test_zellij_rereads_config_after_watcher_wait(self):
        source = self.paths.current_theme / "zellij.kdl"
        source.parent.mkdir(parents=True)
        source.write_text('themes { source { fg "white" } }\n')
        config = self.paths.config_home / "zellij/config.kdl"
        config.parent.mkdir(parents=True)
        config.write_text('theme "old"\n')

        def user_edit(_path: Path) -> None:
            config.write_text('theme "new-user-theme"\npane_frames false\n')

        with patch(
            "thpm.integrations._wait_for_zellij_config_tick",
            side_effect=user_edit,
        ):
            apply("zellij", self.paths)

        self.assertEqual(
            config.read_text(), 'theme "thpm-current"\npane_frames false\n'
        )
        saved = json.loads(self.paths.zellij_theme_state_file.read_text())
        self.assertEqual(saved["themeOption"], 'theme "new-user-theme"')

    def test_zellij_rejects_future_dated_config_before_installing_theme(self):
        source = self.paths.current_theme / "zellij.kdl"
        source.parent.mkdir(parents=True)
        source.write_text('themes { source { fg "white" } }\n')
        config = self.paths.config_home / "zellij/config.kdl"
        config.parent.mkdir(parents=True)
        config.write_text('theme "old"\n')
        future = time.time() + 10
        os.utime(config, (future, future))

        with self.assertRaisesRegex(RuntimeError, "unsupported future timestamp"):
            apply("zellij", self.paths)

        self.assertEqual(config.read_text(), 'theme "old"\n')
        self.assertFalse((config.parent / "themes/thpm.kdl").exists())
        self.assertFalse(self.paths.zellij_theme_state_file.exists())

    def test_zellij_preserves_symlink_and_config_mode(self):
        source = self.paths.current_theme / "zellij.kdl"
        source.parent.mkdir(parents=True)
        source.write_text('themes { source { fg "white" } }\n')
        real_config = self.paths.home / "dotfiles/zellij.kdl"
        real_config.parent.mkdir(parents=True)
        real_config.write_text('theme "old"\n')
        real_config.chmod(0o600)
        config = self.paths.config_home / "zellij/config.kdl"
        config.parent.mkdir(parents=True)
        config.symlink_to(real_config)

        apply("zellij", self.paths)
        self.assertTrue(config.is_symlink())
        self.assertEqual(real_config.stat().st_mode & 0o777, 0o600)
        source.write_text('themes { source { fg "black" } }\n')
        refreshed = apply("zellij", self.paths)
        self.assertIn(str(config), refreshed.changed)
        self.assertTrue(config.is_symlink())
        self.assertEqual(real_config.stat().st_mode & 0o777, 0o600)
        source.unlink()
        apply("zellij", self.paths)
        self.assertTrue(config.is_symlink())
        self.assertEqual(real_config.read_text(), 'theme "old"\n')
        self.assertEqual(real_config.stat().st_mode & 0o777, 0o600)

    def test_zellij_normalization_ignores_comments_and_rejects_malformed_kdl(self):
        source = self.paths.current_theme / "zellij.kdl"
        source.parent.mkdir(parents=True)
        source.write_text(
            '/*\nthemes { commented {} }\n*/\nthemes { actual { fg "white" } }\n'
        )
        apply("zellij", self.paths)
        target = self.paths.config_home / "zellij/themes/thpm.kdl"
        self.assertEqual(
            target.read_text(),
            '/*\nthemes { commented {} }\n*/\nthemes { thpm-current { fg "white" } }\n',
        )
        installed = target.read_text()
        source.write_text('themes { broken { fg "white" }\n')
        with self.assertRaisesRegex(ValueError, "unbalanced braces"):
            apply("zellij", self.paths)
        self.assertEqual(target.read_text(), installed)

    def test_zellij_restores_semicolon_option_with_block_comment(self):
        source = self.paths.current_theme / "zellij.kdl"
        source.parent.mkdir(parents=True)
        source.write_text('themes { source { fg "white" } }\n')
        config = self.paths.config_home / "zellij/config.kdl"
        config.parent.mkdir(parents=True)
        original = 'theme "catppuccin"; /* keep */\npane_frames true\n'
        config.write_text(original)
        apply("zellij", self.paths)
        self.assertEqual(
            config.read_text(),
            'theme "thpm-current"; /* keep */\npane_frames true\n',
        )
        source.unlink()
        apply("zellij", self.paths)
        self.assertEqual(config.read_text(), original)

    def test_zellij_reversed_legacy_markers_fail_closed_without_exception(self):
        config = self.paths.config_home / "zellij/config.kdl"
        config.parent.mkdir(parents=True)
        original = (
            "// thpm-zellij-theme-end\n"
            'theme "thpm-current"\n'
            "// thpm-zellij-theme-start\n"
        )
        config.write_text(original)
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            payload = Service(self.paths).set_enabled("zellij", False, refresh=False)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["cleanupIncomplete"])
        self.assertEqual(payload["recoveryCommand"], "thpm disable zellij")
        self.assertTrue(payload["residuals"])
        self.assertEqual(config.read_text(), original)
        self.assertFalse(load(self.paths)["zellij"])
        self.assertIn("legacy THPM block is invalid", str(payload["warnings"]))

    def test_zellij_refreshes_config_for_changed_theme_and_preserves_noop(self):
        source = self.paths.current_theme / "zellij.kdl"
        source.parent.mkdir(parents=True)
        source.write_text('themes { source { fg "white" } }\n')
        config = self.paths.config_home / "zellij/config.kdl"
        apply("zellij", self.paths)
        first_inode = config.stat().st_ino

        first_mtime_second = config.stat().st_mtime_ns // 1_000_000_000
        source.write_text('themes { source { fg "black" } }\n')
        refreshed = apply("zellij", self.paths)
        second_mtime_second = config.stat().st_mtime_ns // 1_000_000_000
        self.assertIn(str(config), refreshed.changed)
        self.assertNotEqual(config.stat().st_ino, first_inode)
        self.assertGreater(second_mtime_second, first_mtime_second)
        self.assertEqual(config.read_text(), 'theme "thpm-current"\n')
        self.assertEqual(refreshed.warnings, [])

        source.write_text('themes { source { fg "red" } }\n')
        second_refresh = apply("zellij", self.paths)
        third_mtime_second = config.stat().st_mtime_ns // 1_000_000_000
        self.assertIn(str(config), second_refresh.changed)
        self.assertGreater(third_mtime_second, second_mtime_second)
        self.assertLessEqual(
            third_mtime_second, time.time_ns() // 1_000_000_000
        )

        while time.time_ns() // 1_000_000_000 <= third_mtime_second:
            time.sleep(0.01)
        config.write_text(config.read_text() + "pane_frames true\n")
        external_mtime_second = config.stat().st_mtime_ns // 1_000_000_000
        self.assertGreater(external_mtime_second, third_mtime_second)

        refreshed_inode = config.stat().st_ino
        result = apply("zellij", self.paths)
        self.assertEqual(result.status, "unchanged")
        self.assertEqual(result.warnings, [])
        self.assertEqual(config.stat().st_ino, refreshed_inode)

    def test_zellij_process_detection_uses_same_user_proc_comm(self):
        proc_root = self.paths.home / "proc"
        process = proc_root / "123"
        process.mkdir(parents=True)
        (process / "comm").write_text("zellij\n")
        self.assertTrue(_zellij_process_running(proc_root))
        (process / "comm").write_text("foot\n")
        self.assertFalse(_zellij_process_running(proc_root))

    def test_zellij_process_detection_ignores_other_user(self):
        proc_root = self.paths.home / "proc-other-user"
        proc_entry = proc_root / "123"
        proc_entry.mkdir(parents=True)
        (proc_entry / "comm").write_text("zellij\n")

        with patch("thpm.service.os.getuid", return_value=os.getuid() + 1):
            self.assertFalse(_zellij_process_running(proc_root))

    def test_zellij_process_detection_skips_disappearing_entries(self):
        proc_root = self.paths.home / "proc-disappearing"
        disappearing = proc_root / "123"
        active = proc_root / "456"
        disappearing.mkdir(parents=True)
        active.mkdir()
        (disappearing / "comm").write_text("zellij\n")
        (active / "comm").write_text("zellij\n")
        original_read_text = Path.read_text

        def flaky_read_text(path, *args, **kwargs):
            if path == disappearing / "comm":
                raise FileNotFoundError(path)
            return original_read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", autospec=True, side_effect=flaky_read_text):
            self.assertTrue(_zellij_process_running(proc_root))

    def test_zellij_disable_reports_restart_for_a_running_session(self):
        source = self.paths.current_theme / "zellij.kdl"
        source.parent.mkdir(parents=True)
        source.write_text('themes { source { fg "white" } }\n')
        enabled = load(self.paths)
        enabled["zellij"] = True
        save(self.paths, enabled)
        apply("zellij", self.paths)

        with patch(
            "thpm.service._zellij_process_running", create=True, return_value=True
        ):
            payload = Service(self.paths).set_enabled(
                "zellij", False, refresh=False
            )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["restartRequired"], ["Zellij"])

    def test_zellij_noop_disable_does_not_report_restart(self):
        with patch("thpm.service._zellij_process_running", return_value=True):
            payload = Service(self.paths).set_enabled(
                "zellij", False, refresh=False
            )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["restartRequired"], [])

    def test_typora_generated_theme_lifecycle_is_safe_and_idempotent(self):
        plugin = next(plugin for plugin in PLUGINS if plugin.id == "typora")
        self.assertEqual(plugin.templates, ("thpm-typora.css.tpl",))
        self.assertEqual(plugin.theme_assets, ("typora.css",))
        self.assertFalse(plugin.default_enabled)

        source = self.paths.current_theme / "thpm-typora.css"
        source.parent.mkdir(parents=True)
        source.write_text(":root { --bg-color: #101820; --text-color: #f0f0e8; }\n")
        target = self.paths.config_home / "Typora/themes/thpm.css"

        first = apply("typora", self.paths)
        self.assertEqual(target.read_bytes(), source.read_bytes())
        self.assertIn(str(target), first.changed)
        before = (
            target.stat().st_ino,
            target.stat().st_mtime_ns,
            target.stat().st_size,
            hashlib.sha256(target.read_bytes()).hexdigest(),
        )

        second = apply("typora", self.paths)
        after = (
            target.stat().st_ino,
            target.stat().st_mtime_ns,
            target.stat().st_size,
            hashlib.sha256(target.read_bytes()).hexdigest(),
        )
        self.assertEqual(before, after)
        self.assertEqual(second.status, "unchanged")

        source.unlink()
        changed, warnings = cleanup_managed_outputs(self.paths, "typora")
        self.assertFalse(target.exists())
        self.assertIn(str(target), changed)
        self.assertEqual(warnings, [])

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("/* prior user theme */\n")
        source.write_text(":root { --bg-color: #101820; }\n")
        apply("typora", self.paths)
        source.unlink()
        changed, warnings = cleanup_managed_outputs(self.paths, "typora")
        self.assertEqual(target.read_text(), "/* prior user theme */\n")
        self.assertIn(str(target), changed)
        self.assertEqual(warnings, [])

        source.write_text(":root { --bg-color: #101820; }\n")
        apply("typora", self.paths)
        target.write_text("/* user changed the managed theme */\n")
        source.unlink()
        changed, warnings = cleanup_managed_outputs(self.paths, "typora")
        self.assertEqual(target.read_text(), "/* user changed the managed theme */\n")
        self.assertEqual(changed, [])
        self.assertIn("preserved user-modified file", str(warnings))

    def test_typora_prefers_authored_theme_over_generated_output(self):
        authored = self.paths.current_theme / "typora.css"
        generated = self.paths.current_theme / "thpm-typora.css"
        authored.parent.mkdir(parents=True)
        authored.write_text("/* authored Typora theme */\n")
        generated.write_text("/* generated Typora theme */\n")

        result = apply("typora", self.paths)

        target = self.paths.config_home / "Typora/themes/thpm.css"
        self.assertEqual(target.read_text(), authored.read_text())
        self.assertIn(str(target), result.changed)

    def test_typora_apply_reports_restart_only_when_changed_and_running(self):
        source = self.paths.current_theme / "thpm-typora.css"
        source.parent.mkdir(parents=True)
        source.write_text(":root { --bg-color: #101820; }\n")

        with patch("thpm.integrations.shutil.which", return_value="/usr/bin/pgrep"), patch(
            "thpm.integrations.subprocess.run",
            return_value=subprocess.CompletedProcess(["pgrep"], 0, "123\n", ""),
        ):
            first = apply("typora", self.paths)
            second = apply("typora", self.paths)

        self.assertEqual(first.restartRequired, ["Typora"])
        self.assertEqual(second.status, "unchanged")
        self.assertEqual(second.restartRequired, [])

    def test_typora_disable_and_uninstall_report_running_app_restart(self):
        source = self.paths.current_theme / "thpm-typora.css"
        source.parent.mkdir(parents=True)
        source.write_text(":root { --bg-color: #101820; }\n")
        service = Service(self.paths)

        with patch("thpm.service._typora_process_running", return_value=True), patch(
            "thpm.integrations._reload", return_value=([], [])
        ):
            service.set_enabled("typora", True, refresh=False)
            apply("typora", self.paths)
            disabled = service.set_enabled("typora", False)
            service.set_enabled("typora", True, refresh=False)
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(":root { --bg-color: #101820; }\n")
            apply("typora", self.paths)
            uninstalled = service.uninstall()

        self.assertEqual(disabled["restartRequired"], ["Typora"])
        self.assertEqual(uninstalled["restartRequired"], ["Typora"])
        self.assertFalse((self.paths.config_home / "Typora/themes/thpm.css").exists())

    def test_typora_noop_disable_does_not_report_restart(self):
        service = Service(self.paths)

        with patch("thpm.service._typora_process_running", return_value=True):
            disabled = service.set_enabled("typora", False)

        self.assertEqual(disabled["restartRequired"], [])
        self.assertEqual(disabled["stateChanged"], False)

    def test_typora_disable_reports_restart_despite_cleanup_error(self):
        source = self.paths.current_theme / "thpm-typora.css"
        source.parent.mkdir(parents=True)
        source.write_text("/* managed Typora theme */\n")
        with patch("thpm.integrations._reload", return_value=([], [])):
            apply("typora", self.paths)

        def cleanup_with_error(paths, plugin_id, *, assume_legacy=False):
            changed, warnings = cleanup_managed_outputs(
                paths, plugin_id, assume_legacy=assume_legacy
            )
            warnings.append("simulated cleanup failure")
            return changed, warnings

        with patch("thpm.service._typora_process_running", return_value=True), patch(
            "thpm.service.cleanup_managed_outputs", side_effect=cleanup_with_error
        ):
            disabled = Service(self.paths).set_enabled("typora", False)

        self.assertTrue(disabled["errors"])
        self.assertEqual(disabled["restartRequired"], ["Typora"])

    def test_typora_noop_uninstall_does_not_report_restart(self):
        with patch("thpm.service._typora_process_running", return_value=True):
            uninstalled = Service(self.paths).uninstall()

        self.assertEqual(uninstalled["restartRequired"], [])

    def test_typora_uninstall_reports_restart_despite_unrelated_cleanup_error(self):
        source = self.paths.current_theme / "thpm-typora.css"
        source.parent.mkdir(parents=True)
        source.write_text("/* managed Typora theme */\n")
        with patch("thpm.integrations._reload", return_value=([], [])):
            apply("typora", self.paths)

        def cleanup_with_unrelated_error(paths, plugin_id, *, assume_legacy=False):
            changed, warnings = cleanup_managed_outputs(
                paths, plugin_id, assume_legacy=assume_legacy
            )
            if plugin_id == "vicinae":
                warnings.append("simulated unrelated cleanup failure")
            return changed, warnings

        with patch("thpm.service._typora_process_running", return_value=True), patch(
            "thpm.service.cleanup_managed_outputs",
            side_effect=cleanup_with_unrelated_error,
        ):
            uninstalled = Service(self.paths).uninstall()

        self.assertTrue(uninstalled["errors"])
        self.assertEqual(uninstalled["restartRequired"], ["Typora"])

    def test_typora_preserved_user_edit_does_not_report_restart(self):
        source = self.paths.current_theme / "thpm-typora.css"
        source.parent.mkdir(parents=True)
        source.write_text("/* managed Typora theme */\n")
        with patch("thpm.integrations._reload", return_value=([], [])):
            apply("typora", self.paths)
        target = self.paths.config_home / "Typora/themes/thpm.css"
        target.write_text("/* user-modified Typora theme */\n")

        with patch("thpm.service._typora_process_running", return_value=True):
            disabled = Service(self.paths).set_enabled("typora", False)

        self.assertEqual(target.read_text(), "/* user-modified Typora theme */\n")
        self.assertEqual(disabled["restartRequired"], [])
        self.assertIn("preserved user-modified file", str(disabled["warnings"]))

    def test_typora_process_probe_failures_do_not_fail_changed_apply(self):
        source = self.paths.current_theme / "thpm-typora.css"
        source.parent.mkdir(parents=True)
        scenarios = (
            (None, None),
            ("/usr/bin/pgrep", subprocess.TimeoutExpired("pgrep", 2)),
            ("/usr/bin/pgrep", subprocess.CompletedProcess(["pgrep"], 1, "", "")),
            ("/usr/bin/pgrep", OSError("pgrep disappeared")),
        )

        for index, (pgrep, outcome) in enumerate(scenarios):
            with self.subTest(index=index):
                source.write_text(f"/* managed Typora theme {index} */\n")
                with patch("thpm.integrations.shutil.which", return_value=pgrep):
                    if isinstance(outcome, BaseException):
                        runner = patch(
                            "thpm.integrations.subprocess.run", side_effect=outcome
                        )
                    else:
                        runner = patch(
                            "thpm.integrations.subprocess.run", return_value=outcome
                        )
                    with runner:
                        result = apply("typora", self.paths)
                self.assertEqual(result.status, "applied")
                self.assertEqual(result.restartRequired, [])

    def test_optional_assets_restore_the_files_they_displaced(self):
        cases = {
            "cliamp": ("cliamp.toml", self.paths.config_home / "cliamp/themes/omarchy.toml"),
        }
        with patch("thpm.integrations._reload", return_value=[]):
            for plugin_id, (asset_name, target) in cases.items():
                with self.subTest(plugin=plugin_id):
                    source = self.paths.current_theme / asset_name
                    source.parent.mkdir(parents=True, exist_ok=True)
                    managed = f"{plugin_id} theme"
                    if plugin_id == "cliamp":
                        managed = f"# thpm:cliamp-use-native\n{managed}"
                    source.write_text(managed)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(f"{plugin_id} user default")
                    apply(plugin_id, self.paths)
                    self.assertEqual(target.read_text(), managed)
                    source.unlink()
                    result = apply(plugin_id, self.paths)
                    self.assertEqual(target.read_text(), f"{plugin_id} user default")
                    self.assertIn(str(target), result.changed)

    def test_reconcile_retires_swaync_and_cleans_historical_output(self):
        installed_theme = self.paths.config_home / "omarchy/themes/old"
        installed_theme.mkdir(parents=True)
        (installed_theme / "colors.css").write_text("legacy swaync theme\n")
        target = self.paths.config_home / "swaync/colors.css"
        target.parent.mkdir(parents=True)
        target.write_text("legacy swaync theme\n")
        self.paths.state_file.parent.mkdir(parents=True)
        self.paths.state_file.write_text(
            "version = 1\n\n[plugins]\nspotify = true\nswaync = true\n"
        )
        self.paths.canonical_palette_migration_marker.parent.mkdir(parents=True)
        self.paths.canonical_palette_migration_marker.write_text(
            "canonical-palette-v1\n"
        )

        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            payload = Service(self.paths).reconcile()

        self.assertFalse(target.exists())
        self.assertNotIn("swaync", self.paths.state_file.read_text())
        self.assertNotIn("swaync", {item["id"] for item in payload["plugins"]})
        self.assertIn(str(target), payload["changed"])

    def test_reconcile_preserves_matching_untracked_swaync_without_saved_state(self):
        installed_theme = self.paths.config_home / "omarchy/themes/old"
        installed_theme.mkdir(parents=True)
        (installed_theme / "colors.css").write_text("user-selected colors\n")
        target = self.paths.config_home / "swaync/colors.css"
        target.parent.mkdir(parents=True)
        target.write_text("user-selected colors\n")
        self.paths.canonical_palette_migration_marker.parent.mkdir(parents=True)
        self.paths.canonical_palette_migration_marker.write_text(
            "canonical-palette-v1\n"
        )

        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            payload = Service(self.paths).reconcile()

        self.assertEqual(target.read_text(), "user-selected colors\n")
        self.assertNotIn(str(target), payload["changed"])

    def test_reconcile_preserves_matching_swaync_saved_as_disabled(self):
        installed_theme = self.paths.config_home / "omarchy/themes/old"
        installed_theme.mkdir(parents=True)
        (installed_theme / "colors.css").write_text("user-selected colors\n")
        target = self.paths.config_home / "swaync/colors.css"
        target.parent.mkdir(parents=True)
        target.write_text("user-selected colors\n")
        self.paths.state_file.parent.mkdir(parents=True)
        self.paths.state_file.write_text(
            "version = 1\n\n[plugins]\nspotify = true\nswaync = false\n"
        )
        self.paths.canonical_palette_migration_marker.parent.mkdir(parents=True)
        self.paths.canonical_palette_migration_marker.write_text(
            "canonical-palette-v1\n"
        )

        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            payload = Service(self.paths).reconcile()

        self.assertEqual(target.read_text(), "user-selected colors\n")
        self.assertNotIn(str(target), payload["changed"])
        self.assertNotIn("swaync", self.paths.state_file.read_text())

    def test_reconcile_retires_swaync_and_restores_displaced_stylesheet(self):
        managed = b"retired SwayNC theme\n"
        prior = b"user SwayNC theme\n"
        target = self.paths.config_home / "swaync/colors.css"
        target.parent.mkdir(parents=True)
        target.write_bytes(managed)
        state = self.paths.managed_asset_state_dir / "swaync.json"
        backup = self.paths.managed_asset_state_dir / "swaync.backup"
        state.parent.mkdir(parents=True)
        backup.write_bytes(prior)
        state.write_text(
            json.dumps(
                {
                    "existed": True,
                    "priorType": "file",
                    "priorSha256": hashlib.sha256(prior).hexdigest(),
                    "priorMode": 0o644,
                    "managedSha256": hashlib.sha256(managed).hexdigest(),
                    "managedMode": 0o644,
                }
            )
        )
        self.paths.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.paths.state_file.write_text(
            "version = 1\n\n[plugins]\nspotify = true\nswaync = true\n"
        )
        self.paths.canonical_palette_migration_marker.parent.mkdir(parents=True)
        self.paths.canonical_palette_migration_marker.write_text(
            "canonical-palette-v1\n"
        )

        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            payload = Service(self.paths).reconcile()

        self.assertEqual(target.read_bytes(), prior)
        self.assertFalse(state.exists())
        self.assertFalse(backup.exists())
        self.assertNotIn("swaync", self.paths.state_file.read_text())
        self.assertIn(str(target), payload["changed"])

    def test_reconcile_cleans_retired_windsurf_output_without_exposing_plugin(self):
        installed_theme = self.paths.config_home / "omarchy/themes/old"
        installed_theme.mkdir(parents=True)
        (installed_theme / "vscode-theme.json").write_text("legacy windsurf theme")
        target = (
            self.paths.home
            / ".windsurf/extensions/local.omarchy-theme/themes/omarchy.json"
        )
        target.parent.mkdir(parents=True)
        target.write_text("legacy windsurf theme")
        self.paths.canonical_palette_migration_marker.parent.mkdir(parents=True)
        self.paths.canonical_palette_migration_marker.write_text(
            "canonical-palette-v1\n"
        )
        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            payload = Service(self.paths).reconcile()
        self.assertFalse(target.exists())
        self.assertIn(str(target), payload["changed"])
        self.assertNotIn("windsurf", {item["id"] for item in payload["plugins"]})

    def test_reconcile_preserves_legacy_typora_output_while_enabled(self):
        managed = b"retired Typora theme\n"
        prior = b"user Typora theme\n"
        target = self.paths.config_home / "Typora/themes/omarchy.css"
        target.parent.mkdir(parents=True)
        target.write_bytes(managed)
        state = self.paths.managed_asset_state_dir / "typora.json"
        backup = self.paths.managed_asset_state_dir / "typora.backup"
        state.parent.mkdir(parents=True)
        backup.write_bytes(prior)
        state.write_text(
            json.dumps(
                {
                    "existed": True,
                    "priorType": "file",
                    "priorSha256": hashlib.sha256(prior).hexdigest(),
                    "priorMode": 0o644,
                    "managedSha256": hashlib.sha256(managed).hexdigest(),
                    "managedMode": 0o644,
                }
            )
        )
        state_before = state.read_bytes()
        backup_before = backup.read_bytes()
        self.paths.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.paths.state_file.write_text(
            "version = 1\n\n[plugins]\nspotify = true\ntypora = true\n"
        )
        self.paths.canonical_palette_migration_marker.parent.mkdir(parents=True)
        self.paths.canonical_palette_migration_marker.write_text(
            "canonical-palette-v1\n"
        )

        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            payload = Service(self.paths).reconcile()

        self.assertEqual(target.read_bytes(), managed)
        self.assertEqual(state.read_bytes(), state_before)
        self.assertEqual(backup.read_bytes(), backup_before)
        self.assertIn("typora = true", self.paths.state_file.read_text())
        self.assertIn("typora", {item["id"] for item in payload["plugins"]})
        self.assertTrue(
            (self.paths.themed_dir / "thpm-typora.css.tpl").is_file()
        )
        self.assertNotIn(str(target), payload["changed"])
        self.assertEqual(payload.get("restartRequired", []), [])

    def test_typora_disable_restores_legacy_managed_output(self):
        managed = b"legacy managed Typora theme\n"
        prior = b"user Typora theme\n"
        target = self.paths.config_home / "Typora/themes/omarchy.css"
        target.parent.mkdir(parents=True)
        target.write_bytes(managed)
        state = self.paths.managed_asset_state_dir / "typora.json"
        backup = self.paths.managed_asset_state_dir / "typora.backup"
        state.parent.mkdir(parents=True)
        backup.write_bytes(prior)
        state.write_text(
            json.dumps(
                {
                    "existed": True,
                    "priorType": "file",
                    "priorSha256": hashlib.sha256(prior).hexdigest(),
                    "priorMode": 0o644,
                    "managedSha256": hashlib.sha256(managed).hexdigest(),
                    "managedMode": 0o644,
                }
            )
        )
        self.paths.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.paths.state_file.write_text(
            "version = 1\n\n[plugins]\nspotify = true\ntypora = true\n"
        )

        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch(
            "thpm.service._typora_process_running", return_value=True
        ):
            payload = Service(self.paths).set_enabled(
                "typora", False, refresh=False
            )

        self.assertEqual(target.read_bytes(), prior)
        self.assertFalse(state.exists())
        self.assertFalse(backup.exists())
        self.assertIn(str(target), payload["changed"])
        self.assertEqual(payload["restartRequired"], ["Typora"])

    def test_typora_uninstall_reports_restart_for_legacy_managed_output(self):
        managed = b"legacy managed Typora theme\n"
        prior = b"user Typora theme\n"
        target = self.paths.config_home / "Typora/themes/omarchy.css"
        target.parent.mkdir(parents=True)
        target.write_bytes(managed)
        state = self.paths.managed_asset_state_dir / "typora.json"
        backup = self.paths.managed_asset_state_dir / "typora.backup"
        state.parent.mkdir(parents=True)
        backup.write_bytes(prior)
        state.write_text(
            json.dumps(
                {
                    "existed": True,
                    "priorType": "file",
                    "priorSha256": hashlib.sha256(prior).hexdigest(),
                    "priorMode": 0o644,
                    "managedSha256": hashlib.sha256(managed).hexdigest(),
                    "managedMode": 0o644,
                }
            )
        )

        with patch("thpm.service._typora_process_running", return_value=True):
            payload = Service(self.paths).uninstall()

        self.assertEqual(target.read_bytes(), prior)
        self.assertIn(str(target), payload["changed"])
        self.assertEqual(payload["restartRequired"], ["Typora"])

    def test_reconcile_retires_vicinae_and_cleans_historical_outputs(self):
        rendered = self.paths.current_theme / "thpm-vicinae.toml"
        rendered.parent.mkdir(parents=True)
        rendered.write_text("legacy generated theme\n")
        current = self.paths.data_home / "vicinae/themes/thpm.toml"
        legacy = self.paths.config_home / "vicinae/themes/thpm.toml"
        for target in (current, legacy):
            target.parent.mkdir(parents=True)
            target.write_bytes(rendered.read_bytes())
        deployed_template = self.paths.themed_dir / "thpm-vicinae.toml.tpl"
        deployed_template.parent.mkdir(parents=True)
        deployed_template.write_text("retired template\n")
        self.paths.state_file.parent.mkdir(parents=True)
        self.paths.state_file.write_text(
            "version = 1\n\n[plugins]\nspotify = true\nvicinae = true\n"
        )
        self.paths.canonical_palette_migration_marker.parent.mkdir(parents=True)
        self.paths.canonical_palette_migration_marker.write_text(
            "canonical-palette-v1\n"
        )

        assets = Path(__file__).parents[1] / "assets"
        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}):
            payload = Service(self.paths).reconcile()

        self.assertFalse(current.exists())
        self.assertFalse(legacy.exists())
        self.assertFalse(rendered.exists())
        self.assertFalse(deployed_template.exists())
        self.assertNotIn("vicinae", self.paths.state_file.read_text())
        self.assertNotIn("vicinae", {item["id"] for item in payload["plugins"]})
        for target in (current, legacy, rendered, deployed_template):
            self.assertIn(str(target), payload["changed"])

    def test_legacy_optional_output_is_removed_only_when_it_matches_a_theme_asset(self):
        installed_theme = self.paths.config_home / "omarchy/themes/old"
        installed_theme.mkdir(parents=True)
        (installed_theme / "colors.css").write_text("old managed colors")
        target = self.paths.config_home / "swaync/colors.css"
        target.parent.mkdir(parents=True)
        target.write_text("old managed colors")
        result_changed, result_warnings = cleanup_optional_assets(
            self.paths, "swaync", assume_legacy=True
        )
        self.assertFalse(target.exists())
        self.assertIn(str(target), result_changed)
        self.assertEqual(result_warnings, [])

        marker = self.paths.managed_asset_state_dir / "swaync.legacy-checked"
        marker.unlink()
        target.write_text("user colors")
        preserved_changed, preserved_warnings = cleanup_optional_assets(
            self.paths, "swaync", assume_legacy=True
        )
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(), "user colors")
        self.assertEqual(preserved_changed, [])
        self.assertEqual(preserved_warnings, [])

    def test_optional_asset_without_previous_file_is_removed_when_absent(self):
        source = self.paths.current_theme / "cliamp.toml"
        source.parent.mkdir(parents=True)
        source.write_text("# thpm:cliamp-use-native\ntheme")
        target = self.paths.config_home / "cliamp/themes/omarchy.toml"
        apply("cliamp", self.paths)
        source.unlink()
        result = apply("cliamp", self.paths)
        self.assertFalse(target.exists())
        self.assertIn(str(target), result.changed)

    def test_optional_asset_interrupted_update_keeps_original_backup(self):
        source = self.paths.current_theme / "cliamp.toml"
        source.parent.mkdir(parents=True)
        source.write_text("# thpm:cliamp-use-native\ntheme a")
        target = self.paths.config_home / "cliamp/themes/omarchy.toml"
        target.parent.mkdir(parents=True)
        target.write_text("user default")
        apply("cliamp", self.paths)
        source.write_text("# thpm:cliamp-use-native\ntheme b")
        with patch(
            "thpm.integrations.atomic_copy", side_effect=RuntimeError("interrupted")
        ), self.assertRaisesRegex(RuntimeError, "interrupted"):
            apply("cliamp", self.paths)
        source.unlink()
        apply("cliamp", self.paths)
        self.assertEqual(target.read_text(), "user default")

    def test_optional_asset_equal_bytes_normalizes_mode_and_cleans_up(self):
        source = self.paths.current_theme / "cliamp.toml"
        source.parent.mkdir(parents=True)
        source.write_text("# thpm:cliamp-use-native\nsame")
        target = self.paths.config_home / "cliamp/themes/omarchy.toml"
        target.parent.mkdir(parents=True)
        target.write_text("# thpm:cliamp-use-native\nsame")
        target.chmod(0o600)
        apply("cliamp", self.paths)
        self.assertEqual(target.stat().st_mode & 0o777, 0o644)
        source.unlink()
        apply("cliamp", self.paths)
        self.assertFalse(target.exists())

    def test_optional_asset_missing_backup_fails_closed(self):
        source = self.paths.current_theme / "cliamp.toml"
        source.parent.mkdir(parents=True)
        source.write_text("# thpm:cliamp-use-native\ntheme")
        target = self.paths.config_home / "cliamp/themes/omarchy.toml"
        target.parent.mkdir(parents=True)
        target.write_text("user default")
        apply("cliamp", self.paths)
        (self.paths.managed_asset_state_dir / "cliamp.backup").unlink()
        source.unlink()
        result = apply("cliamp", self.paths)
        self.assertEqual(target.read_text(), "# thpm:cliamp-use-native\ntheme")
        self.assertIn("backup is missing", result.warnings[0])

    def test_optional_asset_corrupt_backup_and_state_schema_fail_closed(self):
        source = self.paths.current_theme / "cliamp.toml"
        source.parent.mkdir(parents=True)
        source.write_text("# thpm:cliamp-use-native\ntheme")
        target = self.paths.config_home / "cliamp/themes/omarchy.toml"
        target.parent.mkdir(parents=True)
        target.write_text("user default")
        apply("cliamp", self.paths)
        backup = self.paths.managed_asset_state_dir / "cliamp.backup"
        backup.write_text("corrupted")
        source.unlink()
        corrupted = apply("cliamp", self.paths)
        self.assertEqual(target.read_text(), "# thpm:cliamp-use-native\ntheme")
        self.assertIn("backup is missing or invalid", corrupted.warnings[0])

        state = self.paths.managed_asset_state_dir / "cliamp.json"
        state.write_text(json.dumps({"existed": True, "priorType": "bad"}))
        invalid = apply("cliamp", self.paths)
        self.assertEqual(target.read_text(), "# thpm:cliamp-use-native\ntheme")
        self.assertIn("state is invalid", invalid.warnings[0])

    def test_optional_asset_restores_previous_symlink(self):
        source = self.paths.current_theme / "cliamp.toml"
        source.parent.mkdir(parents=True)
        source.write_text("# thpm:cliamp-use-native\ntheme")
        original = self.paths.home / "my-cliamp.toml"
        original.write_text("user default")
        target = self.paths.config_home / "cliamp/themes/omarchy.toml"
        target.parent.mkdir(parents=True)
        target.symlink_to(original)
        apply("cliamp", self.paths)
        self.assertFalse(target.is_symlink())
        source.unlink()
        apply("cliamp", self.paths)
        self.assertTrue(target.is_symlink())
        self.assertEqual(target.readlink(), original)

    def test_optional_asset_cleanup_preserves_a_user_modified_target(self):
        source = self.paths.current_theme / "cliamp.toml"
        source.parent.mkdir(parents=True)
        source.write_text("# thpm:cliamp-use-native\ntheme")
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

    def test_optional_asset_cleanup_does_not_require_the_application(self):
        target = self.paths.config_home / "cliamp/themes/omarchy.toml"
        state = self.paths.managed_asset_state_dir / "cliamp.json"
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
            result = apply_enabled(self.paths, {"cliamp": True})
        cliamp = next(item for item in result["results"] if item["id"] == "cliamp")
        self.assertEqual(cliamp["status"], "applied")
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
        self.assertIn("block is invalid", malformed_block.warnings[0])

    def test_spotify_readiness_reports_one_time_setup_requirements(self):
        ready, missing, _warnings = inspect_readiness(
            "spotify", self.paths, lambda _command: "/usr/bin/spicetify"
        )
        self.assertFalse(ready)
        self.assertIn("spicetify backup apply", " ".join(missing))

        config = self.paths.config_home / "spicetify/config-xpui.ini"
        prefs = self.paths.config_home / "spotify/prefs"
        prefs.parent.mkdir(parents=True)
        prefs.write_text('app.last-launched-version="1.2.3"\n')
        config.parent.mkdir(parents=True)
        config.write_text(
            "[Setting]\ncurrent_theme = omarchy\ncolor_scheme = Base\n"
            f"prefs_path = {prefs}\n"
            "[Backup]\nversion = 1.2.3\n"
        )
        stylesheet = self.paths.config_home / "spicetify/Themes/omarchy/user.css"
        ready, missing, warnings = inspect_readiness(
            "spotify", self.paths, lambda _command: "/usr/bin/spicetify"
        )
        self.assertTrue(ready)
        self.assertEqual(missing, [])
        self.assertIn("will initialize", " ".join(warnings))

        stylesheet.parent.mkdir(parents=True)
        stylesheet.write_text(":root {}\n")
        ready, missing, warnings = inspect_readiness(
            "spotify", self.paths, lambda _command: "/usr/bin/spicetify"
        )
        self.assertTrue(ready)
        self.assertEqual(missing, [])
        self.assertEqual(warnings, [])

    def test_spotify_readiness_treats_theme_selection_as_repairable(self):
        config = self.paths.config_home / "spicetify/config-xpui.ini"
        prefs = self.paths.config_home / "spotify/prefs"
        prefs.parent.mkdir(parents=True)
        prefs.write_text('app.last-launched-version="1.2.3"\n')
        config.parent.mkdir(parents=True)
        config.write_text(
            "[Setting]\ncurrent_theme = text\ncolor_scheme = Text\n"
            f"prefs_path = {prefs}\n"
            "[Backup]\nversion = 1.2.3\n"
        )

        ready, missing, warnings = inspect_readiness(
            "spotify", self.paths, lambda _command: "/usr/bin/spicetify"
        )

        self.assertTrue(ready)
        self.assertEqual(missing, [])
        self.assertIn("will select", " ".join(warnings))

    def test_spotify_apply_selects_managed_theme(self):
        generated = self.paths.current_theme / "thpm-spicetify.ini"
        generated.parent.mkdir(parents=True)
        generated.write_text("[Base]\nmain = 000000\n")
        config = self.paths.config_home / "spicetify/config-xpui.ini"
        config.parent.mkdir(parents=True)
        config.write_text(
            "[Setting]\ncurrent_theme = text\ncolor_scheme = Text\n"
        )
        assets = Path(__file__).parents[1] / "assets"

        def select_theme(*_args, **_kwargs):
            self.assertTrue(
                (self.paths.config_home / "spicetify/Themes/omarchy/user.css").is_file()
            )
            self.assertTrue(
                (self.paths.config_home / "spicetify/Themes/omarchy/color.ini").is_file()
            )
            return subprocess.CompletedProcess([], 0, "", "")

        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch(
            "thpm.integrations.subprocess.run", side_effect=select_theme
        ) as run_command, patch("thpm.integrations._reload", return_value=[]):
            result = apply("spotify", self.paths)

        run_command.assert_called_once_with(
            [
                "spicetify",
                "config",
                "current_theme",
                "omarchy",
                "color_scheme",
                "Base",
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
        self.assertIn(str(config), result.changed)
        self.assertIn(
            "spicetify config current_theme omarchy color_scheme Base",
            result.actions,
        )

    def test_spotify_selection_failure_reports_files_installed_before_failure(self):
        generated = self.paths.current_theme / "thpm-spicetify.ini"
        generated.parent.mkdir(parents=True)
        generated.write_text("[Base]\nmain = 000000\n")
        config = self.paths.config_home / "spicetify/config-xpui.ini"
        config.parent.mkdir(parents=True)
        config.write_text("[Setting]\ncurrent_theme = text\ncolor_scheme = Text\n")
        stylesheet = self.paths.config_home / "spicetify/Themes/omarchy/user.css"
        stylesheet.parent.mkdir(parents=True)
        stylesheet.write_text("/* existing theme */\n")
        failed = subprocess.CompletedProcess([], 1, "", "selection failed")

        with patch("thpm.integrations.subprocess.run", return_value=failed), self.assertRaisesRegex(
            ApplyFailure, "selection failed"
        ) as raised:
            apply("spotify", self.paths)

        target = self.paths.config_home / "spicetify/Themes/omarchy/color.ini"
        self.assertTrue(target.is_file())
        self.assertIn(str(target), raised.exception.changed)
        self.assertEqual(raised.exception.actions, [])

    def test_spotify_refresh_failure_preserves_successful_selection_action(self):
        generated = self.paths.current_theme / "thpm-spicetify.ini"
        generated.parent.mkdir(parents=True)
        generated.write_text("[Base]\nmain = 000000\n")
        config = self.paths.config_home / "spicetify/config-xpui.ini"
        config.parent.mkdir(parents=True)
        config.write_text("[Setting]\ncurrent_theme = text\ncolor_scheme = Text\n")
        stylesheet = self.paths.config_home / "spicetify/Themes/omarchy/user.css"
        stylesheet.parent.mkdir(parents=True)
        stylesheet.write_text("/* existing theme */\n")
        selected = subprocess.CompletedProcess([], 0, "", "")

        with patch(
            "thpm.integrations.subprocess.run", return_value=selected
        ), patch(
            "thpm.integrations._reload", side_effect=RuntimeError("refresh failed")
        ), self.assertRaisesRegex(ApplyFailure, "refresh failed") as raised:
            apply("spotify", self.paths)

        self.assertIn(str(config), raised.exception.changed)
        self.assertEqual(
            raised.exception.actions,
            ["spicetify config current_theme omarchy color_scheme Base"],
        )

    def test_spotify_apply_initializes_missing_companion_stylesheet(self):
        generated = self.paths.current_theme / "thpm-spicetify.ini"
        generated.parent.mkdir(parents=True)
        generated.write_text("[Base]\nmain = 000000\n")
        assets = Path(__file__).parents[1] / "assets"

        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch(
            "thpm.integrations._reload", return_value=[]
        ):
            result = apply("spotify", self.paths)

        stylesheet = self.paths.config_home / "spicetify/Themes/omarchy/user.css"
        self.assertEqual(
            stylesheet.read_bytes(),
            (assets / "spicetify/omarchy-user.css").read_bytes(),
        )
        self.assertIn(str(stylesheet), result.changed)
        self.assertEqual(stylesheet.stat().st_mode & 0o777, 0o644)

    def test_spotify_apply_preserves_existing_companion_stylesheet(self):
        generated = self.paths.current_theme / "thpm-spicetify.ini"
        generated.parent.mkdir(parents=True)
        generated.write_text("[Base]\nmain = 000000\n")
        stylesheet = self.paths.config_home / "spicetify/Themes/omarchy/user.css"
        stylesheet.parent.mkdir(parents=True)
        stylesheet.write_text("/* user customization */\n")
        assets = Path(__file__).parents[1] / "assets"

        with patch.dict(os.environ, {"THPM_ASSET_DIR": str(assets)}), patch(
            "thpm.integrations._reload", return_value=[]
        ):
            result = apply("spotify", self.paths)

        self.assertEqual(stylesheet.read_text(), "/* user customization */\n")
        self.assertNotIn(str(stylesheet), result.changed)

    def test_spotify_readiness_rejects_an_unsafe_stylesheet_target(self):
        config = self.paths.config_home / "spicetify/config-xpui.ini"
        prefs = self.paths.config_home / "spotify/prefs"
        prefs.parent.mkdir(parents=True)
        prefs.write_text('app.last-launched-version="1.2.3"\n')
        config.parent.mkdir(parents=True)
        config.write_text(
            "[Setting]\ncurrent_theme = omarchy\n"
            f"prefs_path = {prefs}\n"
            "[Backup]\nversion = 1.2.3\n"
        )
        stylesheet = self.paths.config_home / "spicetify/Themes/omarchy/user.css"
        stylesheet.parent.mkdir(parents=True)
        stylesheet.symlink_to(self.paths.home / "victim")

        ready, missing, _warnings = inspect_readiness(
            "spotify", self.paths, lambda _command: "/usr/bin/spicetify"
        )

        self.assertFalse(ready)
        self.assertIn("safe regular", " ".join(missing))

    def test_spotify_readiness_rejects_a_stale_backup(self):
        config = self.paths.config_home / "spicetify/config-xpui.ini"
        prefs = self.paths.config_home / "spotify/prefs"
        prefs.parent.mkdir(parents=True)
        prefs.write_text('app.last-launched-version="1.2.92.147.g5b8f9367"\n')
        config.parent.mkdir(parents=True)
        config.write_text(
            "[Setting]\ncurrent_theme = omarchy\n"
            f"prefs_path = {prefs}\n"
            "[Backup]\nversion = 1.2.84.476.ga1ff6607\n"
        )
        stylesheet = self.paths.config_home / "spicetify/Themes/omarchy/user.css"
        stylesheet.parent.mkdir(parents=True)
        stylesheet.write_text(":root {}\n")

        ready, missing, _warnings = inspect_readiness(
            "spotify", self.paths, lambda _command: "/usr/bin/spicetify"
        )

        self.assertFalse(ready)
        self.assertIn("matching Spotify 1.2.92.147.g5b8f9367", " ".join(missing))
        self.assertIn("current backup is 1.2.84.476.ga1ff6607", " ".join(missing))

        generated = self.paths.current_theme / "thpm-spicetify.ini"
        generated.parent.mkdir(parents=True)
        generated.write_text("[Base]\nmain = 000000\n")
        with patch("thpm.integrations.shutil.which", return_value="/usr/bin/spicetify"), patch(
            "thpm.integrations._reload", side_effect=AssertionError("must not reload")
        ):
            payload = apply_enabled(self.paths, {"spotify": True})
        self.assertEqual(payload["results"][0]["status"], "skipped")
        self.assertEqual(payload["errors"], [])

    def test_retired_vicinae_cleanup_restores_legacy_and_removes_current_output(self):
        source = self.paths.current_theme / "thpm-vicinae.toml"
        source.parent.mkdir(parents=True)
        source.write_text("managed Vicinae theme\n")
        legacy = self.paths.config_home / "vicinae/themes/thpm.toml"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(source.read_bytes())
        current = self.paths.data_home / "vicinae/themes/thpm.toml"
        current.parent.mkdir(parents=True)
        current.write_bytes(source.read_bytes())
        prior = b"user legacy theme\n"
        state = self.paths.managed_asset_state_dir / "generated-vicinae.json"
        backup = self.paths.managed_asset_state_dir / "generated-vicinae.backup"
        state.parent.mkdir(parents=True)
        backup.write_bytes(prior)
        state.write_text(
            json.dumps(
                {
                    "existed": True,
                    "priorType": "file",
                    "priorSha256": hashlib.sha256(prior).hexdigest(),
                    "priorMode": 0o644,
                    "managedSha256": hashlib.sha256(legacy.read_bytes()).hexdigest(),
                    "managedMode": 0o644,
                }
            )
        )

        changed, warnings = cleanup_managed_outputs(
            self.paths, "vicinae", assume_legacy=True
        )

        self.assertEqual(legacy.read_bytes(), prior)
        self.assertFalse(current.exists())
        self.assertFalse(source.exists())
        self.assertEqual(warnings, [])
        self.assertFalse(state.exists())
        for target in (legacy, current, source):
            self.assertIn(str(target), changed)

    def test_moved_spotify_output_reapply_and_cleanup_preserve_current_backup(self):
        source = self.paths.current_theme / "thpm-spicetify.ini"
        source.parent.mkdir(parents=True)
        source.write_text("generated theme\n")
        target = self.paths.config_home / "spicetify/Themes/omarchy/color.ini"
        target.parent.mkdir(parents=True)
        target.write_text("user current theme\n")
        (target.parent / "user.css").write_text("/* existing theme */\n")

        with patch("thpm.integrations._reload", return_value=[]):
            first = apply("spotify", self.paths)
            second = apply("spotify", self.paths)
        changed, warnings = cleanup_managed_outputs(self.paths, "spotify")

        self.assertEqual(first.status, "applied")
        self.assertEqual(second.status, "unchanged")
        self.assertEqual(target.read_text(), "user current theme\n")
        self.assertIn(str(target), changed)
        self.assertEqual(warnings, [])
        self.assertFalse(
            (
                self.paths.managed_asset_state_dir / "generated-spotify-v2.json"
            ).exists()
        )

    def test_spotify_reload_restarts_a_running_client_after_refresh(self):
        completed = subprocess.CompletedProcess([], 0, "", "")
        running = subprocess.CompletedProcess([], 0, "123\n", "")
        with patch(
            "thpm.integrations.shutil.which", return_value="/usr/bin/tool"
        ), patch(
            "thpm.integrations.subprocess.run",
            side_effect=[completed, running, completed],
        ) as run:
            actions, restart_required = _reload("spotify")

        self.assertEqual(actions, ["spicetify refresh", "spicetify restart"])
        self.assertEqual(restart_required, [])
        self.assertEqual(
            run.call_args_list,
            [
                call(
                    ["spicetify", "refresh"],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=5,
                ),
                call(
                    ["pgrep", "-x", "spotify"],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=2,
                ),
                call(
                    ["spicetify", "restart"],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=5,
                ),
            ],
        )

    def test_spotify_reload_does_not_launch_a_closed_client(self):
        completed = subprocess.CompletedProcess([], 0, "", "")
        stopped = subprocess.CompletedProcess([], 1, "", "")
        with patch(
            "thpm.integrations.shutil.which", return_value="/usr/bin/tool"
        ), patch(
            "thpm.integrations.subprocess.run", side_effect=[completed, stopped]
        ) as run:
            actions, restart_required = _reload("spotify")

        self.assertEqual(actions, ["spicetify refresh"])
        self.assertEqual(restart_required, [])
        self.assertEqual(len(run.call_args_list), 2)

    def test_spotify_notify_policy_refreshes_without_restarting(self):
        completed = subprocess.CompletedProcess([], 0, "", "")
        running = subprocess.CompletedProcess([], 0, "123\n", "")
        with patch(
            "thpm.integrations.shutil.which", return_value="/usr/bin/tool"
        ), patch(
            "thpm.integrations.subprocess.run", side_effect=[completed, running]
        ) as run:
            actions, restart_required = _reload(
                "spotify", automatic_restarts=False
            )

        self.assertEqual(actions, ["spicetify refresh"])
        self.assertEqual(restart_required, ["Spotify"])
        self.assertEqual(len(run.call_args_list), 2)

    def test_spotify_restart_failure_preserves_refresh_and_pending_restart(self):
        refreshed = subprocess.CompletedProcess([], 0, "", "")
        running = subprocess.CompletedProcess([], 0, "123\n", "")
        failed = subprocess.CompletedProcess([], 1, "", "restart failed")
        with patch(
            "thpm.integrations.shutil.which", return_value="/usr/bin/tool"
        ), patch(
            "thpm.integrations.subprocess.run",
            side_effect=[refreshed, running, failed],
        ), self.assertRaisesRegex(ApplyFailure, "restart failed") as raised:
            _reload("spotify")

        self.assertEqual(raised.exception.actions, ["spicetify refresh"])
        self.assertEqual(raised.exception.restart_required, ["Spotify"])

    def test_spotify_restart_failure_reaches_aggregate_hook_result(self):
        generated = self.paths.current_theme / "thpm-spicetify.ini"
        generated.parent.mkdir(parents=True)
        generated.write_text("[base]\n")
        stylesheet = self.paths.config_home / "spicetify/Themes/omarchy/user.css"
        stylesheet.parent.mkdir(parents=True)
        stylesheet.write_text("/* existing theme */\n")
        refreshed = subprocess.CompletedProcess([], 0, "", "")
        running = subprocess.CompletedProcess([], 0, "123\n", "")
        failed = subprocess.CompletedProcess([], 1, "", "restart failed")
        with patch(
            "thpm.integrations.inspect_readiness", return_value=(True, [], [])
        ), patch(
            "thpm.integrations.shutil.which", return_value="/usr/bin/tool"
        ), patch(
            "thpm.integrations.subprocess.run",
            side_effect=[refreshed, running, failed],
        ):
            payload = apply_enabled(self.paths, {"spotify": True})

        self.assertEqual(payload["results"][0]["status"], "failed")
        self.assertEqual(payload["actions"], ["spicetify refresh"])
        self.assertEqual(payload["restartRequired"], ["Spotify"])

    def test_explicit_reapply_forces_reload_when_spotify_colors_are_unchanged(self):
        generated = self.paths.current_theme / "thpm-spicetify.ini"
        generated.parent.mkdir(parents=True)
        generated.write_text("[base]\n")
        stylesheet = self.paths.config_home / "spicetify/Themes/omarchy/user.css"
        stylesheet.parent.mkdir(parents=True)
        stylesheet.write_text("/* existing theme */\n")
        with patch(
            "thpm.integrations._reload",
            return_value=(["spicetify refresh", "spicetify restart"], []),
        ) as reload_app:
            first = apply("spotify", self.paths)
            forced = apply("spotify", self.paths, force_reload=True)

        self.assertEqual(first.status, "applied")
        self.assertEqual(forced.status, "applied")
        self.assertEqual(
            forced.actions, ["spicetify refresh", "spicetify restart"]
        )
        self.assertEqual(reload_app.call_count, 2)

    def test_unchanged_integrations_do_not_invoke_reload_commands(self):
        generated = self.paths.current_theme / "thpm-spicetify.ini"
        generated.parent.mkdir(parents=True)
        generated.write_text("[base]\n")
        stylesheet = self.paths.config_home / "spicetify/Themes/omarchy/user.css"
        stylesheet.parent.mkdir(parents=True)
        stylesheet.write_text("/* existing theme */\n")
        for plugin_id in ("spotify",):
            with self.subTest(plugin_id=plugin_id), patch(
                "thpm.integrations._reload",
                return_value=[f"{plugin_id} reload"],
            ) as reload_app, patch(
                "thpm.integrations.shutil.which", return_value="/usr/bin/tool"
            ):
                first = apply(plugin_id, self.paths)
                second = apply(plugin_id, self.paths)

            self.assertEqual(first.status, "applied")
            self.assertEqual(second.status, "unchanged")
            self.assertEqual(second.actions, [])
            reload_app.assert_called_once_with(
                plugin_id, automatic_restarts=True
            )

    def test_steam_helper_is_bounded_and_quiet(self):
        script = self.paths.home / ".local/share/steam-adwaita/install.py"
        script.parent.mkdir(parents=True)
        script.touch()
        with patch("thpm.integrations.shutil.which", return_value=None), patch(
            "thpm.integrations.subprocess.run"
        ) as run:
            run.return_value.returncode = 0
            result = apply("steam", self.paths)
        self.assertEqual(result.status, "applied")
        self.assertEqual(result.restartRequired, [])
        run.assert_called_once_with(
            [str(script), "--color-theme", "omarchy"],
            cwd=script.parent,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

    def test_steam_restart_notice_depends_on_running_process(self):
        script = self.paths.home / ".local/share/steam-adwaita/install.py"
        script.parent.mkdir(parents=True)
        script.touch()
        installed = subprocess.CompletedProcess([], 0, "", "")

        for returncode, expected in ((0, ["Steam"]), (1, [])):
            with self.subTest(returncode=returncode), patch(
                "thpm.integrations.shutil.which", return_value="/usr/bin/pgrep"
            ), patch(
                "thpm.integrations.subprocess.run",
                side_effect=[
                    installed,
                    subprocess.CompletedProcess([], returncode, "", ""),
                ],
            ) as run:
                result = apply("steam", self.paths)

            self.assertEqual(result.restartRequired, expected)
            self.assertEqual(
                run.call_args_list,
                [
                    call(
                        [str(script), "--color-theme", "omarchy"],
                        cwd=script.parent,
                        text=True,
                        capture_output=True,
                        check=False,
                        timeout=30,
                    ),
                    call(
                        ["pgrep", "-x", "steam"],
                        text=True,
                        capture_output=True,
                        check=False,
                        timeout=2,
                    ),
                ],
            )

    def test_gtk_compat_generates_css_from_palette_without_theme_asset(self):
        self.write_palette()

        result = apply("gtk-css-compat", self.paths)

        self.assertEqual(result.status, "applied")
        self.assertIn("generated from colors.toml", result.message)
        for version in ("gtk-3.0", "gtk-4.0"):
            main = self.paths.config_home / version / "gtk.css"
            managed = main.with_name("thpm-theme.css")
            self.assertIn('@import url("thpm-theme.css")', main.read_text())
            css = managed.read_text()
            self.assertIn("@define-color window_bg_color #111111;", css)
            self.assertIn("@define-color window_fg_color #dddddd;", css)
            self.assertIn("@define-color accent_bg_color #4477cc;", css)
            self.assertIn("@define-color accent_fg_color #ffffff;", css)

        second = apply("gtk-css-compat", self.paths)
        self.assertEqual(second.status, "unchanged")
        self.assertEqual(second.changed, [])

    def test_gtk_compat_preserves_user_css_and_removes_only_managed_content(self):
        source = self.paths.current_theme / "gtk.css"
        source.parent.mkdir(parents=True)
        source.write_text("@define-color accent #abcdef;\n")
        gtk3 = self.paths.config_home / "gtk-3.0/gtk.css"
        gtk3.parent.mkdir(parents=True)
        gtk3.write_text("button { padding: 4px; }\n")
        first = apply("gtk-css-compat", self.paths)
        self.assertEqual(first.status, "applied")
        self.assertEqual(first.restartRequired, ["running GTK applications"])
        self.assertIn('import url("thpm-theme.css")', gtk3.read_text())
        self.assertIn("button { padding: 4px; }", gtk3.read_text())
        self.assertEqual((gtk3.parent / "thpm-theme.css").read_bytes(), source.read_bytes())
        second = apply("gtk-css-compat", self.paths)
        self.assertEqual(second.status, "unchanged")
        self.assertEqual(second.restartRequired, [])
        source.unlink()
        cleanup = apply("gtk-css-compat", self.paths)
        self.assertEqual(cleanup.status, "applied")
        self.assertEqual(
            cleanup.restartRequired, ["running GTK applications"]
        )
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
        self.assertEqual(result.restartRequired, ["Firefox"])
        unchanged = apply("firefox", self.paths)
        self.assertEqual(unchanged.restartRequired, [])

    def test_zen_reports_restart_only_after_browser_css_changes(self):
        generated = self.paths.current_theme / "thpm-zen.css"
        generated.parent.mkdir(parents=True)
        generated.write_text("/* generated */\n")
        base = self.paths.home / ".zen"
        base.mkdir(parents=True)
        (base / "profiles.ini").write_text(
            "[Install1]\nDefault=profile.default\n"
        )
        user_chrome = base / "profile.default/chrome/userChrome.css"
        user_chrome.parent.mkdir(parents=True)
        user_chrome.write_text(
            "/* THPM Zen hook start */\n"
            '@import url("./thpm-zen-colors.css");\n'
            '@import url("./thpm-zen-userChrome.css");\n'
            "/* THPM Zen hook end */\n"
            "/* user styles */\n"
        )

        changed = apply("zen", self.paths)
        unchanged = apply("zen", self.paths)

        self.assertEqual(changed.restartRequired, ["Zen Browser"])
        self.assertEqual(unchanged.restartRequired, [])
        self.assertIn('@import url("thpm-zen.css");', user_chrome.read_text())
        self.assertNotIn("THPM Zen hook", user_chrome.read_text())
        self.assertIn("/* user styles */", user_chrome.read_text())

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
        cava_config = self.paths.config_home / "cava/config"
        cava_config.parent.mkdir(parents=True)
        cava_config.write_text("[color]\ntheme = 'thpm'\n")
        superfile = apply("superfile", self.paths)
        with patch(
            "thpm.integrations.shutil.which", return_value="/usr/bin/cava"
        ), patch(
            "thpm.integrations.installed_cava_version", return_value=(0, 10, 6)
        ), patch("thpm.integrations._reload", return_value=[]):
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

    def test_nwg_dock_reports_restart_requirement_only_after_a_change(self):
        generated = self.paths.current_theme / "thpm-nwg-dock.css"
        generated.parent.mkdir(parents=True)
        generated.write_text("/* dock */")
        result = apply("nwg-dock", self.paths)
        unchanged = apply("nwg-dock", self.paths)
        self.assertEqual(result.status, "applied")
        self.assertEqual(result.restartRequired, ["nwg-dock-hyprland"])
        self.assertEqual(result.warnings, [])
        self.assertEqual(unchanged.status, "unchanged")
        self.assertEqual(unchanged.restartRequired, [])
        self.assertEqual(unchanged.warnings, [])

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
        stylesheet = self.paths.config_home / "spicetify/Themes/omarchy/user.css"
        stylesheet.parent.mkdir(parents=True)
        stylesheet.write_text("/* existing theme */\n")
        with patch("thpm.integrations.inspect_readiness", return_value=(True, [], [])), patch(
            "thpm.integrations._reload", side_effect=RuntimeError("reload failed")
        ):
            payload = apply_enabled(self.paths, {"spotify": True})
        target = self.paths.config_home / "spicetify/Themes/omarchy/color.ini"
        self.assertEqual(payload["results"][0]["status"], "failed")
        self.assertIn(str(target), payload["results"][0]["changed"])
        self.assertEqual(target.read_text(), "[base]\n")

    def test_apply_enabled_aggregates_and_deduplicates_restart_requirements(self):
        first = ApplyResult(
            "gtk-css-compat",
            "applied",
            changed=["/tmp/gtk"],
            restartRequired=["running GTK applications"],
        )
        second = ApplyResult(
            "nwg-dock",
            "applied",
            changed=["/tmp/dock"],
            restartRequired=["running GTK applications", "nwg-dock-hyprland"],
        )
        with patch(
            "thpm.integrations.inspect_readiness", return_value=(True, [], [])
        ), patch("thpm.integrations.apply", side_effect=[first, second]):
            payload = apply_enabled(
                self.paths,
                {"gtk-css-compat": True, "nwg-dock": True},
                automatic_restarts=False,
            )

        self.assertEqual(
            payload["restartRequired"],
            ["running GTK applications", "nwg-dock-hyprland"],
        )

    def test_apply_enabled_isolates_failures_and_exposes_statuses(self):
        generated = self.paths.current_theme / "thpm-fish.fish"
        generated.parent.mkdir(parents=True)
        generated.write_text("set -g fish_color_normal normal\n")
        events: list[dict[str, object]] = []
        with patch("thpm.integrations.inspect_readiness", return_value=(True, [], [])), patch(
            "thpm.integrations.apply", side_effect=[apply("fish", self.paths), RuntimeError("broken")]
        ):
            payload = apply_enabled(
                self.paths, {"fish": True, "fzf": True}, events=events.append
            )
        self.assertEqual([result["status"] for result in payload["results"]], ["applied", "failed"])
        self.assertEqual(payload["counts"]["failed"], 1)
        self.assertEqual(payload["errors"][0]["plugin"], "fzf")
        self.assertEqual(
            [event["type"] for event in events],
            [
                "integrations_started",
                "integration_started",
                "integration_finished",
                "integration_started",
                "integration_finished",
            ],
        )
        self.assertEqual(events[0]["total"], 2)
        self.assertEqual(events[2]["status"], "applied")
        self.assertEqual(events[4]["status"], "failed")

    def test_apply_enabled_isolates_readiness_failures(self):
        def readiness(plugin_id, _paths):
            if plugin_id == "fish":
                raise RuntimeError("readiness broke")
            return True, [], []

        with patch("thpm.integrations.inspect_readiness", side_effect=readiness), patch(
            "thpm.integrations.apply",
            return_value=ApplyResult("fzf", "unchanged"),
        ) as apply_plugin:
            payload = apply_enabled(self.paths, {"fish": True, "fzf": True})

        self.assertEqual(
            [result["status"] for result in payload["results"]],
            ["failed", "unchanged"],
        )
        self.assertEqual(payload["errors"][0]["plugin"], "fish")
        apply_plugin.assert_called_once()

    def test_apply_enabled_fails_conflicting_discord_variants_and_continues(self):
        with patch(
            "thpm.integrations.inspect_readiness", return_value=(True, [], [])
        ), patch(
            "thpm.integrations.apply",
            return_value=ApplyResult("qt6ct", "unchanged"),
        ) as apply_plugin:
            payload = apply_enabled(
                self.paths,
                {"discord": True, "discord-system24": True, "qt6ct": True},
            )

        self.assertEqual(
            [result["status"] for result in payload["results"]],
            ["failed", "failed", "unchanged"],
        )
        self.assertEqual(
            [error["plugin"] for error in payload["errors"]],
            ["discord", "discord-system24"],
        )
        apply_plugin.assert_called_once()

    def test_typora_docs_describe_reintroduced_active_integration(self):
        root = Path(__file__).parents[1]
        support = (root / "docs/integration-support.md").read_text()
        plugins = (root / "docs/plugins.md").read_text()

        self.assertNotIn("| Typora | Retired |", support)
        self.assertNotIn("Typora support is retired", plugins)
        self.assertIn("Typora is an Experimental", plugins)
        self.assertIn("historical", plugins)
        self.assertIn("omarchy.css", plugins)

    def test_typora_template_keeps_print_output_monochrome(self):
        template = (Path(__file__).parents[1] / "assets/templates/thpm-typora.css.tpl").read_text()
        self.assertIn("@media print", template)
        for rule in (
            "color: #000 !important;",
            "background: #fff !important;",
            "background: transparent !important;",
            "text-shadow: none !important;",
            "box-shadow: none !important;\n    border-color: #777 !important;",
        ):
            self.assertIn(rule, template)
        self.assertIn("text-decoration: underline !important;", template)

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

    def test_zen_template_themes_modern_browser_chrome(self):
        template = (
            Path(__file__).parents[1] / "assets/templates/thpm-zen.css.tpl"
        ).read_text()

        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            self.assertIn(key, CANONICAL_COLORS)
            return CANONICAL_COLORS[key]

        rendered = re.sub(r"\{\{ ([a-z_]+) \}\}", replace, template)
        self.assertNotIn("{{", rendered)
        for declaration in (
            "--zen-colors-primary: var(--thpm-bg) !important;",
            "--zen-colors-secondary: var(--thpm-surface) !important;",
            "--zen-colors-tertiary: var(--thpm-surface-raised) !important;",
            "--lwt-accent-color: var(--thpm-bg) !important;",
            "--toolbar-bgcolor: var(--thpm-bg) !important;",
            "--toolbar-field-background-color: var(--thpm-surface) !important;",
            "--arrowpanel-background: var(--thpm-surface) !important;",
        ):
            self.assertIn(declaration, rendered)
        self.assertIn(
            "#zen-sidebar-top-buttons,\n"
            "#zen-sidebar-foot-buttons,\n"
            "#zen-appcontent-wrapper {",
            rendered,
        )

    def test_heroic_template_defines_heroic_css_variables(self):
        template = (Path(__file__).parents[1] / "assets/templates/thpm-heroic.css.tpl").read_text()

        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            self.assertIn(key, CANONICAL_COLORS)
            return CANONICAL_COLORS[key]

        rendered = re.sub(r"\{\{ ([a-z_]+) \}\}", replace, template)

        self.assertIn("body.thpm {", rendered)
        for variable in (
            "--background",
            "--background-darker",
            "--background-lighter",
            "--body-background",
            "--navbar-background",
            "--input-background",
            "--modal-background",
            "--text-default",
            "--text-secondary",
            "--accent",
            "--primary",
            "--primary-button",
            "--secondary",
            "--success",
            "--danger",
            "--action-icon",
            "--divider",
        ):
            self.assertRegex(rendered, re.compile(rf"^[ \t]*{re.escape(variable)}:", re.MULTILINE))
        self.assertIn("body {", rendered)
        self.assertIn("background: var(--body-background)", rendered)

class SourceScriptTests(Sandbox):
    def run_uninstaller(self, root: Path) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update({
            "HOME": str(root / "home"),
            "XDG_BIN_HOME": str(root / "bin"),
            "XDG_DATA_HOME": str(root / "data"),
            "THPM_RUNTIME_DIR": str(root / "runtime"),
        })
        return subprocess.run(
            ["bash", str(Path(__file__).parents[1] / "uninstall.sh")],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )

    @staticmethod
    def executable(path: Path, marker: Path, *, exit_code: int = 0) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "#!/usr/bin/env bash\n"
            f"printf '%s\\n' \"$*\" > {str(marker)!r}\n"
            f"exit {exit_code}\n"
        )
        path.chmod(0o755)

    def test_uninstaller_does_not_invoke_unrelated_launchers(self):
        for kind in ("file", "symlink"):
            with self.subTest(kind=kind):
                root = self.paths.home / kind
                launcher = root / "bin/thpm"
                marker = root / "invoked"
                if kind == "file":
                    self.executable(launcher, marker)
                else:
                    unrelated = root / "unrelated/thpm"
                    self.executable(unrelated, marker)
                    launcher.parent.mkdir(parents=True)
                    launcher.symlink_to(unrelated)

                completed = self.run_uninstaller(root)

                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertFalse(marker.exists())
                self.assertTrue(launcher.exists())

    def test_uninstaller_invokes_and_removes_owned_launcher(self):
        for kind in ("absolute", "relative"):
            with self.subTest(kind=kind):
                root = self.paths.home / kind
                runtime_launcher = root / "runtime/bin/thpm"
                launcher = root / "bin/thpm"
                marker = root / "invoked"
                self.executable(runtime_launcher, marker)
                launcher.parent.mkdir(parents=True)
                target = runtime_launcher
                if kind == "relative":
                    target = Path(os.path.relpath(runtime_launcher, launcher.parent))
                launcher.symlink_to(target)

                completed = self.run_uninstaller(root)

                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(marker.read_text(), "uninstall\n")
                self.assertFalse(launcher.exists())
                self.assertFalse((root / "runtime").exists())

    def test_uninstaller_retains_source_runtime_when_cleanup_fails(self):
        root = self.paths.home / "failed-cleanup"
        runtime_launcher = root / "runtime/bin/thpm"
        launcher = root / "bin/thpm"
        marker = root / "invoked"
        self.executable(runtime_launcher, marker, exit_code=7)
        launcher.parent.mkdir(parents=True)
        launcher.symlink_to(runtime_launcher)

        completed = self.run_uninstaller(root)

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(marker.read_text(), "uninstall\n")
        self.assertTrue(launcher.exists())
        self.assertTrue(runtime_launcher.exists())
        self.assertIn("runtime retained", completed.stderr)


class AuditAndReportTests(Sandbox):
    def audit_entry(self, **updates):
        entry = {
            "journalSchemaVersion": 1,
            "timestamp": "2026-08-06T12:00:00Z",
            "runId": "run-1",
            "thpmVersion": "1.0.0rc19",
            "operation": "hook-run",
            "plugin": "cava",
            "status": "applied",
            "reasonCode": "integration.applied",
            "durationMs": 4,
            "changed": [str(self.paths.home / ".config/cava/themes/thpm")],
            "actions": ["cava.reload.sigusr1"],
            "warnings": [],
            "restartRequired": [],
            "failureDetail": "",
        }
        entry.update(updates)
        return entry

    def test_journal_append_permissions_and_path_normalization(self):
        append_entries(self.paths, [self.audit_entry()])
        self.assertEqual(self.paths.operation_log.stat().st_mode & 0o777, 0o600)
        saved = json.loads(self.paths.operation_log.read_text())
        self.assertEqual(saved["changed"], ["~/.config/cava/themes/thpm"])
        self.assertEqual(recent_entries(self.paths, plugin="cava")[0]["plugin"], "cava")
        self.assertEqual(recent_entries(self.paths, plugin="fish"), [])

    def test_journal_rotation_and_locking_seam(self):
        entry = self.audit_entry(warnings=["x" * 180])
        with patch("thpm.audit.fcntl.flock") as lock:
            append_entries(self.paths, [entry], max_bytes=80, rotations=2)
            append_entries(self.paths, [entry], max_bytes=80, rotations=2)
            recent_entries(self.paths)
        self.assertTrue(self.paths.operation_log.with_name("operations.jsonl.1").is_file())
        self.assertTrue(any(call.args[1] == fcntl.LOCK_EX for call in lock.call_args_list))
        self.assertTrue(any(call.args[1] == fcntl.LOCK_SH for call in lock.call_args_list))
        self.assertTrue(any(call.args[1] == fcntl.LOCK_UN for call in lock.call_args_list))

    def test_journal_rejects_symlinked_lock_active_and_rotated_files(self):
        victim = self.paths.home / "victim"
        victim.write_text("keep\n")
        victim.chmod(0o644)
        self.paths.operation_log.parent.mkdir(parents=True)

        for hostile in (
            self.paths.audit_lock_file,
            self.paths.operation_log,
            self.paths.operation_log.with_name("operations.jsonl.1"),
        ):
            for candidate in (
                self.paths.audit_lock_file,
                self.paths.operation_log,
                self.paths.operation_log.with_name("operations.jsonl.1"),
            ):
                candidate.unlink(missing_ok=True)
            hostile.symlink_to(victim)
            with self.subTest(hostile=hostile), self.assertRaises(OSError):
                append_entries(self.paths, [self.audit_entry()])
            self.assertEqual(victim.read_text(), "keep\n")
            self.assertEqual(victim.stat().st_mode & 0o777, 0o644)

        self.paths.audit_lock_file.unlink(missing_ok=True)
        self.paths.operation_log.with_name("operations.jsonl.1").unlink(missing_ok=True)
        self.paths.operation_log.with_name("operations.jsonl.1").symlink_to(victim)
        self.assertEqual(recent_entries(self.paths), [])
        self.assertEqual(victim.read_text(), "keep\n")

    def test_journal_oversized_batch_stays_bounded_valid_and_private(self):
        entries = [self.audit_entry(runId=f"run-{index}", warnings=["x" * 500]) for index in range(20)]
        append_entries(self.paths, entries, max_bytes=240, rotations=3)
        journal_files = [
            self.paths.operation_log,
            *(self.paths.operation_log.with_name(f"operations.jsonl.{index}") for index in range(1, 4)),
        ]
        for path in journal_files:
            if not path.exists():
                continue
            with self.subTest(path=path):
                self.assertLessEqual(path.stat().st_size, 240)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                for line in path.read_text().splitlines():
                    self.assertIsInstance(json.loads(line), dict)

    def test_recent_entries_skips_corrupt_schema_utf8_and_symlinks(self):
        self.paths.operation_log.parent.mkdir(parents=True)
        self.paths.operation_log.write_bytes(b"\xff\xfe")
        self.assertEqual(recent_entries(self.paths), [])
        self.paths.operation_log.write_text(
            '{"journalSchemaVersion":"bad","plugin":"cava"}\nnot-json\n'
        )
        self.assertEqual(recent_entries(self.paths), [])
        self.paths.operation_log.unlink()
        victim = self.paths.home / "private-journal"
        victim.write_text(json.dumps(self.audit_entry()) + "\n")
        self.paths.operation_log.symlink_to(victim)
        self.assertEqual(recent_entries(self.paths), [])

    def test_journal_truncates_and_redacts_sensitive_values(self):
        payload = {
            "operation": "hook-run",
            "ok": False,
            "results": [
                {
                    "id": "cava",
                    "status": "failed",
                    "message": "password=hunter2 " + "x" * 900,
                    "changed": [str(self.paths.home / "file")],
                    "actions": ["https://example.test/reload?token=secret#fragment"],
                    "warnings": [{"apiToken": "secret"}],
                    "restartRequired": [],
                    "errors": [{"message": "api_key=abc " + "y" * 900}],
                }
            ],
        }
        entry = entries_from_payload(
            self.paths,
            payload,
            run_id="fixed",
            now=lambda: datetime(2026, 8, 6, 12, tzinfo=UTC),
        )[0]
        encoded = json.dumps(entry)
        self.assertNotIn("hunter2", encoded)
        self.assertNotIn("token=secret", encoded)
        self.assertNotIn("fragment", encoded)
        self.assertNotIn("api_key=abc", encoded)
        self.assertIn("truncated", encoded)

    def test_audit_failure_never_escapes(self):
        with patch("thpm.audit.append_entries", side_effect=OSError("disk full")):
            self.assertFalse(record_payload(self.paths, {"operation": "hook-run", "ok": True}))

    def test_redaction_covers_headers_userinfo_and_embedded_home_paths(self):
        raw = (
            "failed at "
            f"{self.paths.home}/private: Authorization: Bearer TOPSECRET; "
            "Bearer BARESECRET; "
            "https://user:URLSECRET@example.test/path?token=QUERY#FRAGMENT"
        )
        cleaned = sanitize(raw, self.paths.home)
        self.assertIn("~/private", cleaned)
        for secret in (
            "TOPSECRET",
            "BARESECRET",
            "URLSECRET",
            "QUERY",
            "FRAGMENT",
            str(self.paths.home),
        ):
            self.assertNotIn(secret, cleaned)
        self.assertIn("Authorization: [redacted]", cleaned)
        self.assertIn("https://example.test/path", cleaned)

    def test_multi_plugin_failures_keep_matching_failure_details(self):
        payload = {
            "operation": "hook-run",
            "ok": False,
            "results": [
                {"id": "cava", "status": "failed"},
                {"id": "fish", "status": "failed"},
            ],
            "errors": [
                {"plugin": "cava", "message": "CAVA DETAIL"},
                {"plugin": "fish", "message": "FISH DETAIL"},
            ],
        }
        entries = entries_from_payload(self.paths, payload)
        self.assertEqual(entries[0]["failureDetail"], "CAVA DETAIL")
        self.assertEqual(entries[1]["failureDetail"], "FISH DETAIL")

    def test_support_report_is_deterministic_filtered_private_and_bounded(self):
        self.write_palette()
        (self.paths.current_theme_name).parent.mkdir(parents=True, exist_ok=True)
        self.paths.current_theme_name.write_text("everforest\n")
        config = self.paths.config_home / "cava/config"
        config.parent.mkdir(parents=True)
        config.write_text("[color]\ntheme='thpm'\npassword=never-include-this\n")
        append_entries(self.paths, [self.audit_entry(), self.audit_entry(plugin="fish")])
        doctor = {
            "ok": True,
            "summary": "healthy",
            "checks": [{"id": "cava.selector", "status": "pass", "summary": "selected"}],
            "diagnostics": {
                "cava": {
                    "processes": [{"pid": 123, "configPath": str(config)}],
                    "apiToken": "must-redact",
                }
            },
        }
        with patch("thpm.report.cava_version", return_value=(0, 10, 7)):
            report = build_report(
                self.paths,
                plugin="cava",
                plugin_view={"id": "cava", "enabled": True},
                doctor=doctor,
                now=lambda: datetime(2026, 8, 6, 12, tzinfo=UTC),
                id_factory=lambda: "report-fixed",
                install_origin={"origin": "thpm", "repository": "https://example.test/repo?secret=yes"},
            )
        encoded = json.dumps(report)
        self.assertEqual(report["reportSchemaVersion"], 1)
        self.assertEqual(report["generatedAt"], "2026-08-06T12:00:00Z")
        self.assertEqual(report["reportId"], "report-fixed")
        self.assertEqual(report["scope"], "cava")
        self.assertEqual(len(report["recentOperations"]), 1)
        self.assertLessEqual(len(encoded.encode()), MAX_REPORT_BYTES)
        self.assertNotIn("never-include-this", encoded)
        self.assertNotIn("must-redact", encoded)
        self.assertNotIn("secret=yes", encoded)
        self.assertNotIn(platform.node(), encoded)
        self.assertIn("~/config/cava/config", encoded)
        self.assertIn("configuration and theme file contents", encoded)

    def test_report_pretty_size_is_trimmed_before_write(self):
        doctor = {
            "ok": False,
            "summary": "large",
            "checks": [
                {
                    "id": f"check-{index}",
                    "status": "error",
                    "summary": "x" * 500,
                    "evidence": {f"field-{item}": "y" * 500 for item in range(12)},
                }
                for index in range(32)
            ],
            "diagnostics": {f"item-{index}": "z" * 500 for index in range(32)},
        }
        with patch("thpm.report.MAX_REPORT_BYTES", 3500):
            report = build_report(
                self.paths,
                plugin="cava",
                plugin_view={"id": "cava", "detail": "p" * 500},
                doctor=doctor,
            )
            output = write_report(self.paths, report)
            payload = output.read_bytes()
        self.assertLessEqual(len(payload), 3500)
        self.assertTrue(report["privacy"]["truncated"])
        self.assertEqual(json.loads(payload)["reportSchemaVersion"], 1)

    def test_support_report_output_is_mode_0600(self):
        report = {
            "reportSchemaVersion": 1,
            "generatedAt": "2026-08-06T12:00:00Z",
            "scope": "cava",
        }
        output = write_report(self.paths, report)
        self.assertTrue(output.is_file())
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(output.read_text())["scope"], "cava")

    def test_service_report_embeds_schema_and_honors_output(self):
        output = self.paths.home / "share/report.json"
        built = {"reportSchemaVersion": 1, "scope": "cava"}
        with patch.object(Service, "doctor", return_value={"plugins": [], "ok": True}), patch(
            "thpm.service.build_report", return_value=built
        ):
            payload = Service(self.paths).support_report("cava", output=output)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["report"], built)
        self.assertEqual(payload["reportPath"], str(output))
        self.assertTrue(output.is_file())

    def test_report_human_rendering_shows_path_and_share_instruction(self):
        stream = io.StringIO()
        render(
            {
                "operation": "report",
                "ok": True,
                "summary": "support report saved",
                "reportPath": "/tmp/report.json",
                "errors": [],
            },
            console=Console(file=stream, force_terminal=False, width=100),
        )
        output = stream.getvalue()
        self.assertIn("/tmp/report.json", output)
        self.assertIn("Share this JSON file", output)

    def test_report_cli_json_is_one_valid_envelope(self):
        response = {
            "schemaVersion": 1,
            "ok": True,
            "operation": "report",
            "summary": "saved",
            "reportPath": "/tmp/report.json",
            "report": {"reportSchemaVersion": 1},
            "errors": [],
        }
        with patch("thpm.cli.Paths.discover", return_value=self.paths), patch.object(
            Service, "support_report", return_value=response
        ), patch("sys.stdout", new_callable=io.StringIO) as stdout:
            exit_code = main(["report", "cava", "--json"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["report"]["reportSchemaVersion"], 1)

    def test_hook_records_authoritative_results_without_affecting_exit(self):
        result = {
            "results": [],
            "counts": {"applied": 0, "unchanged": 0, "skipped": 0, "failed": 0},
            "changed": [],
            "actions": [],
            "restartRequired": [],
            "errors": [],
            "warnings": [],
        }
        with patch("thpm.service.apply_enabled", return_value=result), patch(
            "thpm.service.record_payload", return_value=False
        ) as record:
            payload = Service(self.paths).hook_run("theme-set", ["everforest"])
        self.assertTrue(payload["ok"])
        record.assert_called_once()

    def test_cava_repair_outcomes_are_journaled(self):
        diagnostics = {
            "checks": [
                {
                    "id": "cava.version",
                    "status": "error",
                    "summary": "Cava unavailable",
                }
            ]
        }
        with patch("thpm.service.shutil.which", return_value=None), patch(
            "thpm.service.diagnose_cava", return_value=diagnostics
        ), patch("thpm.service.record_payload", return_value=True) as record:
            payload = Service(self.paths)._repair_cava(enable=True)
        self.assertFalse(payload["ok"])
        self.assertGreaterEqual(payload["durationMs"], 0)
        record.assert_called_once()


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

    def test_release_metadata_verifier_accepts_current_tree(self):
        root = Path(__file__).parents[1]
        completed = subprocess.run(
            [sys.executable, str(root / "scripts/verify-release.py"), "metadata"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn((root / "VERSION").read_text().strip(), completed.stdout)

    def test_release_artifact_verifier_checks_tree_and_checksum(self):
        root = Path(__file__).parents[1]
        version = (root / "VERSION").read_text().strip()
        archive = self.paths.home / f"thpm-{version}.tar.gz"
        checksum = archive.with_name(f"{archive.name}.sha256")
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "archive",
                "--format=tar.gz",
                f"--prefix=thpm-{version}/",
                f"--output={archive}",
                "HEAD",
            ],
            check=True,
        )
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        checksum.write_text(f"{digest}  {archive.name}\n")
        command = [
            sys.executable,
            str(root / "scripts/verify-release.py"),
            "artifact",
            str(archive),
            str(checksum),
            "--ref",
            "HEAD",
        ]
        completed = subprocess.run(command, cwd=root, text=True, capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        checksum.write_text(f"{'0' * 64}  {archive.name}\n")
        failed = subprocess.run(command, cwd=root, text=True, capture_output=True)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("archive SHA-256", failed.stderr)

        original = archive.with_name("original.tar.gz")
        archive.replace(original)
        with tarfile.open(original, "r:gz") as source, tarfile.open(
            archive, "w:gz"
        ) as changed:
            for member in source.getmembers():
                if member.name.endswith("/scripts/release-assets.sh"):
                    member.mode = 0o644
                stream = source.extractfile(member) if member.isfile() else None
                changed.addfile(member, stream)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        checksum.write_text(f"{digest}  {archive.name}\n")
        wrong_mode = subprocess.run(command, cwd=root, text=True, capture_output=True)
        self.assertNotEqual(wrong_mode.returncode, 0)
        self.assertIn("archive mode differs", wrong_mode.stderr)

        with tarfile.open(original, "r:gz") as source, tarfile.open(
            archive, "w:gz"
        ) as changed:
            for member in source.getmembers():
                stream = source.extractfile(member) if member.isfile() else None
                changed.addfile(member, stream)
            fifo = tarfile.TarInfo(f"thpm-{version}/unexpected-fifo")
            fifo.type = tarfile.FIFOTYPE
            changed.addfile(fifo)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        checksum.write_text(f"{digest}  {archive.name}\n")
        special = subprocess.run(command, cwd=root, text=True, capture_output=True)
        self.assertNotEqual(special.returncode, 0)
        self.assertIn("unsupported entry type", special.stderr)

    def test_release_metadata_rejects_substituted_vcs_source(self):
        root = Path(__file__).parents[1]
        clone = self.paths.home / "release-repo"
        subprocess.run(
            ["git", "clone", "--quiet", "--no-hardlinks", str(root), str(clone)],
            check=True,
        )
        shutil.copy2(root / "scripts/verify-release.py", clone / "scripts/verify-release.py")
        package = clone / "packaging/aur/thpm-git/PKGBUILD"
        package.write_text(
            package.read_text()
            + "\nsource+=('git+https://example.invalid/attacker/thpm.git')\n"
            + "sha256sums+=('SKIP')\n"
        )
        completed = subprocess.run(
            [sys.executable, str(clone / "scripts/verify-release.py"), "metadata"],
            cwd=clone,
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("source must have one assignment", completed.stderr)

    def test_release_asset_builder_runs_metadata_and_artifact_gates(self):
        script = (Path(__file__).parents[1] / "scripts/release-assets.sh").read_text()
        self.assertIn("verify-release.py\" metadata --require-clean --require-tag", script)
        self.assertIn("verify-release.py\" artifact", script)
        self.assertIn("--ref HEAD", script)

    def test_release_installer_hands_verified_digest_to_pretag_pkgbuild(self):
        root = Path(__file__).parents[1]
        version = (root / "VERSION").read_text().strip()
        fake_bin = self.paths.home / "bin"
        fake_bin.mkdir()
        fake_curl = fake_bin / "curl"
        fake_curl.write_text(
            "#!/usr/bin/python3\n"
            "import os, shutil, sys\n"
            "output = sys.argv[sys.argv.index('--output') + 1]\n"
            "source = os.environ['CHECKSUM'] if sys.argv[-1].endswith('.sha256') else os.environ['ARCHIVE']\n"
            "shutil.copy2(source, output)\n"
        )
        fake_makepkg = fake_bin / "makepkg"
        fake_makepkg.write_text(
            "#!/usr/bin/env bash\n"
            "grep -Fx \"sha256sums=('$EXPECTED_HASH')\" PKGBUILD >/dev/null || exit 91\n"
            "touch \"$MAKEPKG_MARKER\"\n"
            "exit 37\n"
        )
        fake_sudo = fake_bin / "sudo"
        fake_sudo.write_text("#!/usr/bin/env bash\nexit 99\n")
        for executable in (fake_curl, fake_makepkg, fake_sudo):
            executable.chmod(0o755)

        cases = (
            ("zero-placeholder", "0" * 64, 37, None),
            ("legacy-skip", "SKIP", 37, None),
            (
                "mismatched-digest",
                "1" * 64,
                1,
                "Release PKGBUILD checksum does not match the verified archive",
            ),
            (
                "malformed",
                "not-a-digest",
                1,
                "Release PKGBUILD checksum is not canonical",
            ),
        )
        for label, package_hash, expected_code, expected_error in cases:
            with self.subTest(label=label):
                fixture = self.paths.home / label
                package_dir = fixture / f"thpm-{version}/packaging/aur/thpm"
                package_dir.mkdir(parents=True)
                (package_dir / "PKGBUILD").write_text(
                    f"pkgname=thpm\npkgver={version}\n"
                    f"source=(\"$pkgname-$pkgver.tar.gz\")\n"
                    f"sha256sums=('{package_hash}')\n"
                )
                (package_dir / "thpm.install").write_text("post_install() { :; }\n")
                archive = self.paths.home / f"{label}.tar.gz"
                with tarfile.open(archive, "w:gz") as bundle:
                    bundle.add(fixture / f"thpm-{version}", arcname=f"thpm-{version}")
                digest = hashlib.sha256(archive.read_bytes()).hexdigest()
                checksum = self.paths.home / f"{label}.sha256"
                checksum.write_text(f"{digest}  thpm-{version}.tar.gz\n")
                marker = self.paths.home / f"makepkg-{label}"
                env = {
                    **os.environ,
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "ARCHIVE": str(archive),
                    "CHECKSUM": str(checksum),
                    "EXPECTED_HASH": digest,
                    "MAKEPKG_MARKER": str(marker),
                }
                completed = subprocess.run(
                    ["bash", str(root / "scripts/install-arch-release.sh"), version],
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, expected_code, completed.stderr)
                self.assertEqual(marker.exists(), expected_error is None)
                if expected_error:
                    self.assertIn(expected_error, completed.stderr)
                else:
                    self.assertIn(
                        f"Verified release source SHA-256: {digest}", completed.stdout
                    )

    def test_arch_ci_builds_exact_checkout_during_pretag_phase(self):
        workflow = (Path(__file__).parents[1] / ".github/workflows/ci.yml").read_text()
        validate = workflow.index("Validate AUR metadata")
        prepare = workflow.index("Prepare exact checkout source for pre-tag and VCS builds")
        build = workflow.index("Build package", prepare)
        self.assertLess(validate, prepare)
        self.assertLess(prepare, build)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn('git -c safe.directory="$GITHUB_WORKSPACE" -c tar.umask=0002 archive', workflow)
        self.assertIn('git -c safe.directory="$GITHUB_WORKSPACE" push', workflow)
        self.assertIn("0000000000000000000000000000000000000000000000000000000000000000", workflow)
        self.assertIn("git init --bare /tmp/thpm-ci-source.git", workflow)
        self.assertIn("thpm::git+file:///tmp/thpm-ci-source.git", workflow)

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
        self.assertIn('source_lock="$repo_dir/requirements-source.lock"', script)
        self.assertIn("--require-hashes", script)
        self.assertIn("--only-binary=:all:", script)
        self.assertNotIn("textual>=8.2.8,<9", script)
        self.assertIn('mv "$previous" "$runtime_dir"', script)
        committed_refresh = '"$runtime_dir/bin/thpm" reconcile --refresh'
        disable_rollback = "trap - ERR INT TERM"
        self.assertGreater(script.index(committed_refresh), script.index(disable_rollback))
        self.assertEqual((Path(__file__).parents[1] / "VERSION").read_text().strip(), "1.0.0rc24")

    def test_source_dependency_lock_is_complete_and_hashed(self):
        lock = Path(__file__).parents[1] / "requirements-source.lock"
        content = lock.read_text()
        requirements = [
            line.split("==", 1)[0]
            for line in content.splitlines()
            if line and not line.startswith(("#", " "))
        ]
        self.assertEqual(
            requirements,
            [
                "linkify-it-py",
                "markdown-it-py",
                "mdit-py-plugins",
                "mdurl",
                "platformdirs",
                "pygments",
                "rich",
                "textual",
                "typing-extensions",
                "uc-micro-py",
            ],
        )
        self.assertEqual(len(re.findall(r"--hash=sha256:[0-9a-f]{64}", content)), 10)
        self.assertEqual(len(set(re.findall(r"sha256:([0-9a-f]{64})", content))), 10)

    def test_staged_runtime_uses_lock_and_smoke_tests_textual(self):
        source = __import__("inspect").getsource(updater._stage_runtime)
        update_source = __import__("inspect").getsource(updater.apply)
        self.assertIn('"requirements-source.lock"', source)
        self.assertIn('"--require-hashes"', source)
        self.assertIn('"--only-binary=:all:"', source)
        self.assertNotIn('"textual>=8.2.8,<9"', source)
        self.assertIn("from thpm.tui import ThpmTui", source)
        self.assertIn('"--defer-upgrade-refresh"', update_source)
        self.assertIn('"refreshRequired"', update_source)
        self.assertIn('"thpm reconcile --refresh"', update_source)

    def test_staged_runtime_reports_complete_template_ownership(self):
        runtime = self.paths.home / "runtime.next"
        completed = subprocess.CompletedProcess(
            [],
            0,
            json.dumps(["thpm-current.tpl", "thpm-obsolete-only.tpl"]),
            "",
        )
        with patch("thpm.update.subprocess.run", return_value=completed) as run:
            owned = updater._runtime_owned_templates(runtime)

        self.assertEqual(
            owned, {"thpm-current.tpl", "thpm-obsolete-only.tpl"}
        )
        self.assertIn("from thpm.templates import owned_names", run.call_args.args[0][2])

    def test_staged_runtime_refuses_missing_or_symlinked_dependency_lock(self):
        source = self.paths.home / "source"
        source.mkdir()
        runtime = self.paths.home / "runtime"
        with patch("thpm.update.subprocess.run") as run:
            with self.assertRaisesRegex(RuntimeError, "dependency lock"):
                updater._stage_runtime(source, runtime)
            run.assert_not_called()
        target = self.paths.home / "external.lock"
        target.write_text("textual==8.2.8")
        (source / "requirements-source.lock").symlink_to(target)
        with patch("thpm.update.subprocess.run") as run:
            with self.assertRaisesRegex(RuntimeError, "dependency lock"):
                updater._stage_runtime(source, runtime)
            run.assert_not_called()

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

    def test_staged_ownership_failure_removes_staged_runtime(self):
        runtime = self.paths.home / "runtime"
        (runtime / "bin").mkdir(parents=True)
        fake_python = runtime / "bin/python"
        fake_python.write_text("old runtime")
        source = self.paths.home / "source-tree"
        source.mkdir()
        (source / "VERSION").write_text("1.0.1")
        update = {
            "status": "available",
            "origin": "source",
            "currentVersion": "1.0.0rc1",
            "availableVersion": "1.0.1",
            "archiveUrl": "archive",
            "checksumUrl": "checksum",
        }
        archive_bytes = b"archive"
        digest = __import__("hashlib").sha256(archive_bytes).hexdigest()

        def download(url, destination):
            destination.write_bytes(
                (digest + "  thpm.tar.gz\n").encode()
                if url == "checksum"
                else archive_bytes
            )

        def stage(_source, destination):
            (destination / "bin").mkdir(parents=True)
            (destination / "bin/python").write_text("staged")

        with patch("thpm.update.check", return_value=update), patch(
            "thpm.update._download", side_effect=download
        ), patch("thpm.update._safe_extract", return_value=source), patch(
            "thpm.update._stage_runtime", side_effect=stage
        ), patch(
            "thpm.update._runtime_owned_templates",
            side_effect=RuntimeError("ownership failed"),
        ), patch("thpm.update.sys.executable", str(fake_python)):
            with self.assertRaisesRegex(RuntimeError, "ownership failed"):
                updater.apply(self.paths)

        self.assertEqual(fake_python.read_text(), "old runtime")
        self.assertEqual(list(self.paths.home.glob("runtime.next-*")), [])

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
             patch("thpm.update._runtime_owned_templates", return_value=set()), \
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
        ), patch(
            "thpm.update._runtime_owned_templates", return_value=set()
        ), patch("thpm.update.sys.executable", str(fake_python)), patch(
            "thpm.update.subprocess.run", return_value=completed
        ) as run:
            result = updater.apply(self.paths)
        self.assertEqual(result["status"], "updated")
        self.assertFalse(result["refreshRequired"])
        self.assertIsNone(result["refreshCommand"])
        self.assertFalse(result["uiRefreshRequired"])
        self.assertIsNone(result["uiRefreshCommand"])
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
        existing = self.paths.themed_dir / "thpm-fish.fish.tpl"
        foreign = self.paths.themed_dir / "foreign.tpl"
        existing.write_text("old")
        foreign.write_text("keep")
        backup_root = self.paths.home / "backup"
        backups = updater._backup_integrations(
            self.paths,
            backup_root,
            additional_owned_templates={"thpm-added.tpl"},
        )
        existing.write_text("new")
        (self.paths.themed_dir / "thpm-added.tpl").write_text("added")
        self.paths.post_update_hook_file.parent.mkdir(parents=True)
        self.paths.post_update_hook_file.write_text("new runtime hook")
        updater._restore_integrations(backups)
        self.assertEqual(existing.read_text(), "old")
        self.assertEqual(foreign.read_text(), "keep")
        self.assertFalse((self.paths.themed_dir / "thpm-added.tpl").exists())
        self.assertFalse(self.paths.post_update_hook_file.exists())

    def test_update_rollback_restores_managed_directory_symlinks(self):
        target = self.paths.themed_dir
        target.parent.mkdir(parents=True)
        external = self.paths.home / "managed-templates"
        external.mkdir()
        (external / "thpm-fish.fish.tpl").write_text("keep")
        chained = target.parent / "current-templates"
        chained.symlink_to(external)
        link_targets = {
            "absolute": str(external),
            "relative": os.path.relpath(external, target.parent),
            "chain": chained.name,
            "dangling": "missing-managed-templates",
        }

        for kind, link_target in link_targets.items():
            with self.subTest(kind=kind):
                target.unlink(missing_ok=True)
                target.symlink_to(link_target)
                backups = updater._backup_integrations(
                    self.paths,
                    self.paths.home / f"backup-{kind}",
                    additional_owned_templates={"thpm-new.tpl"},
                )
                if kind == "dangling":
                    target.unlink()
                    target.mkdir()
                    (target / "thpm-new.tpl").write_text("new runtime")
                else:
                    (target / "thpm-fish.fish.tpl").unlink()
                    (target / "thpm-new.tpl").write_text("new runtime")

                with patch(
                    "thpm.update.shutil.rmtree", wraps=shutil.rmtree
                ) as remove_tree:
                    updater._restore_integrations(backups)

                self.assertNotIn(call(external), remove_tree.call_args_list)
                self.assertTrue(target.is_symlink())
                self.assertEqual(os.readlink(target), link_target)
                self.assertEqual(
                    (external / "thpm-fish.fish.tpl").read_text(), "keep"
                )
                self.assertFalse((external / "thpm-new.tpl").exists())

    def test_update_rollback_accepts_symlink_to_its_own_parent(self):
        target = self.paths.themed_dir
        target.parent.mkdir(parents=True)
        target.symlink_to(".")
        backups = updater._backup_integrations(
            self.paths,
            self.paths.home / "backup-parent-link",
            additional_owned_templates={"thpm-new.tpl"},
        )
        (target / "thpm-new.tpl").write_text("new runtime")
        unrelated = target / "concurrent-user-file"
        unrelated.write_text("preserve")
        prefixed_but_unowned = target / "thpm-user-file.tpl"
        prefixed_but_unowned.write_text("also preserve")

        updater._restore_integrations(backups)

        self.assertTrue(target.is_symlink())
        self.assertEqual(os.readlink(target), ".")
        self.assertFalse((target.parent / "thpm-new.tpl").exists())
        self.assertEqual(unrelated.read_text(), "preserve")
        self.assertEqual(prefixed_but_unowned.read_text(), "also preserve")

    def test_update_rollback_does_not_rewrite_file_template_referents(self):
        external = self.paths.home / "not-a-template-directory"
        external.write_text("old content")
        hard_link = self.paths.home / "hard-linked-template-file"
        os.link(external, hard_link)
        self.paths.themed_dir.parent.mkdir(parents=True)
        link_target = os.path.relpath(external, self.paths.themed_dir.parent)
        self.paths.themed_dir.symlink_to(link_target)
        backups = updater._backup_integrations(
            self.paths, self.paths.home / "backup-file-template"
        )
        external.write_text("concurrent user change")
        inode = external.stat().st_ino

        updater._restore_integrations(backups)

        self.assertTrue(self.paths.themed_dir.is_symlink())
        self.assertEqual(os.readlink(self.paths.themed_dir), link_target)
        self.assertEqual(external.read_text(), "concurrent user change")
        self.assertEqual(hard_link.read_text(), "concurrent user change")
        self.assertEqual(external.stat().st_ino, inode)

    def test_update_rollback_does_not_rewrite_untouched_symlink_referents(self):
        external = self.paths.home / "dotfiles/90-thpm"
        external.parent.mkdir(parents=True)
        external.write_text("old hook")
        self.paths.hook_file.parent.mkdir(parents=True)
        link_target = os.path.relpath(external, self.paths.hook_file.parent)
        self.paths.hook_file.symlink_to(link_target)
        backups = updater._backup_integrations(
            self.paths, self.paths.home / "backup-hook"
        )
        self.paths.hook_file.unlink()
        self.paths.hook_file.write_text("new runtime hook")
        external.write_text("concurrent user change")

        updater._restore_integrations(backups)

        self.assertTrue(self.paths.hook_file.is_symlink())
        self.assertEqual(os.readlink(self.paths.hook_file), link_target)
        self.assertEqual(external.read_text(), "concurrent user change")

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
        self.assertIn("update committed", payload["summary"])
        self.assertIn("refresh failed", payload["errors"][0]["message"])

    def test_update_control_panel_failure_is_reported_as_committed_partial_failure(self):
        result = {
            "status": "updated",
            "origin": "thpm",
            "refreshRequired": False,
            "uiRefreshRequired": True,
            "uiRefreshCommand": "thpm ui install",
            "uiRefreshError": "control panel failed",
        }
        with patch("thpm.service.apply_update", return_value=result):
            payload = Service(self.paths).update_apply()
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["committed"])
        self.assertIn("control panel refresh failed", payload["summary"])
        self.assertIn("run thpm ui install", payload["summary"])
        self.assertEqual(payload["errors"], [{"message": "control panel failed"}])

    def test_json_style_aur_apply_requires_a_terminal_without_launching_processes(self):
        result = {
            "status": "available",
            "origin": "thpm",
            "currentVersion": "1.0.0rc1",
            "availableVersion": "1.0.1-1",
        }
        with patch("thpm.update.check", return_value=result), patch(
            "thpm.update.subprocess.run"
        ) as run:
            applied = updater.apply(self.paths, mode="deny")
        self.assertEqual(applied["status"], "requires-interactive")
        self.assertEqual(applied["command"], "thpm update")
        run.assert_not_called()

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
        ) as run:
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
                call(
                    ["/usr/bin/thpm", "ui", "install"],
                    check=True,
                    timeout=updater.COMMAND_TIMEOUT_SECONDS,
                ),
            ],
        )
        self.assertFalse(applied["refreshRequired"])
        self.assertFalse(applied["uiRefreshRequired"])
        self.assertTrue(applied["restartShell"])
        self.assertEqual(
            progress.events,
            [
                ("Upgrading AUR package", "thpm"),
                ("Synchronizing integrations", None),
                ("Refreshing control panel", None),
            ],
        )
        self.assertEqual(progress.totals, [3])

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
            side_effect=[
                None,
                subprocess.CalledProcessError(1, "reconcile"),
                None,
            ],
        ) as run:
            applied = updater.apply(self.paths)
        self.assertEqual(applied["status"], "updated")
        self.assertTrue(applied["packageCommitted"])
        self.assertTrue(applied["refreshRequired"])
        self.assertEqual(applied["refreshCommand"], "thpm reconcile --refresh")
        self.assertIn("reconcile", applied["refreshError"])
        self.assertFalse(applied["uiRefreshRequired"])
        self.assertEqual(
            run.call_args_list[-1].args[0], ["/usr/bin/thpm", "ui", "install"]
        )

    def test_aur_control_panel_failure_reports_committed_package_and_handoff(self):
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
            side_effect=[
                None,
                None,
                subprocess.CalledProcessError(1, "ui install"),
            ],
        ):
            applied = updater.apply(self.paths)
        self.assertEqual(applied["status"], "updated")
        self.assertTrue(applied["packageCommitted"])
        self.assertFalse(applied["refreshRequired"])
        self.assertTrue(applied["uiRefreshRequired"])
        self.assertEqual(applied["uiRefreshCommand"], "thpm ui install")
        self.assertIn("ui install", applied["uiRefreshError"])

    def test_aur_apply_hands_tui_and_gui_to_a_separate_terminal(self):
        result = {"status": "available", "origin": "thpm", "currentVersion": "1.0.0rc1", "availableVersion": "1.0.1-1"}
        commands = {
            "thpm": "/usr/bin/thpm",
            "omarchy-launch-floating-terminal-with-presentation": "/usr/bin/omarchy-launch-floating-terminal-with-presentation",
        }

        writers = []

        def finish_handoff(command, **_kwargs):
            shell_words = __import__("shlex").split(command[1])
            assignment = next(
                word for word in shell_words if word.startswith("THPM_UPDATE_RESULT_FILE=")
            )
            result_file = Path(assignment.split("=", 1)[1])
            self.assertTrue(result_file.is_file())
            self.assertEqual(result_file.stat().st_mode & 0o777, 0o600)

            def write_result():
                time.sleep(0.05)
                result_file.write_text(
                    json.dumps(
                        {
                            "ok": True,
                            "summary": "THPM updated",
                            "result": {
                                **result,
                                "status": "updated",
                                "uiRefreshRequired": False,
                                "refreshRequired": False,
                            },
                        }
                    )
                )

            writer = threading.Thread(target=write_result)
            writer.start()
            writers.append(writer)
            return subprocess.CompletedProcess(command, 0)

        with patch("thpm.update.check", return_value=result), patch(
            "thpm.update.shutil.which", side_effect=commands.get
        ), patch("thpm.update.sys.stdin.isatty", return_value=True), patch(
            "thpm.update.subprocess.run", side_effect=finish_handoff
        ) as launch:
            applied = updater.apply(self.paths, mode="handoff")
        self.assertEqual(applied["status"], "updated")
        self.assertTrue(applied["terminalHandoff"])
        self.assertFalse(applied["uiRefreshRequired"])
        launched = launch.call_args.args[0]
        self.assertEqual(
            launched[0],
            "/usr/bin/omarchy-launch-floating-terminal-with-presentation",
        )
        self.assertIn("THPM_UPDATE_RESULT_FILE=", launched[1])
        self.assertIn("/usr/bin/thpm update apply --inline", launched[1])
        for writer in writers:
            writer.join()

    def test_terminal_handoff_times_out_when_worker_never_returns_result(self):
        result = {
            "status": "available",
            "origin": "thpm",
            "currentVersion": "1.0.0rc1",
            "availableVersion": "1.0.1-1",
        }
        commands = {
            "thpm": "/usr/bin/thpm",
            "omarchy-launch-floating-terminal-with-presentation": "/usr/bin/terminal",
        }
        with patch("thpm.update.check", return_value=result), patch(
            "thpm.update.shutil.which", side_effect=commands.get
        ), patch(
            "thpm.update.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0),
        ), patch(
            "thpm.update.time.monotonic", side_effect=[0, 10_000]
        ):
            applied = updater.apply(self.paths, mode="handoff")
        self.assertEqual(applied["status"], "error")
        self.assertIn("timed out", applied["error"])
        reserved = list(self.paths.runtime_dir.glob("thpm-update-result-*"))
        self.assertEqual(len(reserved), 1)
        self.assertEqual(reserved[0].stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
