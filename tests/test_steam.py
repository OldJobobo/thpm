from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
import unittest
from unittest.mock import patch

from test_thpm import COLORS, Sandbox
from thpm import steam
from thpm.integrations import ApplyFailure, apply, cleanup_managed_outputs, _asset_state_paths, _target_key
from thpm.palette import _strict
from thpm.service import Service
from thpm.state import load, save

# A bounded installer fixture with the same output/import contract as
# steam-adwaita. Real external-installer checks are recorded separately.
INSTALLER = '''#!/usr/bin/env python3
import sys, shutil
from pathlib import Path
root = Path(sys.argv[sys.argv.index('--target') + 1])
ui = root / 'steamui'
shutil.copytree('adwaita', ui / 'adwaita', dirs_exist_ok=True)
(ui / 'libraryroot.custom.css').write_text('@import url("https://steamloopback.host/adwaita/adwaita.css");\\n@import url("https://steamloopback.host/adwaita/colorthemes/omarchy/omarchy.css");\\n')
library = ui / 'css/library.css'
if not library.read_text().startswith('/*patched*/'):
    shutil.copyfile(library, ui / 'css/library.original.css')
    library.write_text('/*patched*/\\n@import url("https://steamloopback.host/css/library.original.css");\\n@import url("https://steamloopback.host/libraryroot.custom.css");\\n')
'''


class SteamTests(Sandbox):
    def setUp(self):
        super().setUp()
        self.write_palette()
        self.script = self.paths.home / '.local/share/steam-adwaita/install.py'
        self.script.parent.mkdir(parents=True)
        self.script.write_text(INSTALLER)
        self.script.chmod(0o755)
        self.source = steam.source_path(self.paths)
        self.source.parent.mkdir(parents=True)
        self.source.write_text('old source palette\n')
        (self.script.parent / 'adwaita/adwaita.css').write_text(':root { --adw-window-bg-rgb: 0,0,0; }\n')
        self.root = self.paths.home / '.local/share/Steam'
        self.library = self.root / steam.LIBRARY_PATH
        self.library.parent.mkdir(parents=True)
        self.library.write_text('original Steam CSS\n')
        self.library.chmod(0o600)
        self.palette_patch = patch('thpm.integrations.load_palette', side_effect=_strict)
        self.which_patch = patch('thpm.integrations.shutil.which', return_value=None)
        self.palette_patch.start()
        self.which_patch.start()
        self.addCleanup(self.palette_patch.stop)
        self.addCleanup(self.which_patch.stop)

    def test_two_palettes_source_installed_and_loader_chain(self):
        first = apply('steam', self.paths)
        self.assertEqual(first.status, 'applied')
        self.assertEqual(first.restartRequired, [])
        steam.validate(self.root, steam.render(COLORS))
        self.assertIn('--adw-window-bg-rgb: 17,17,17', self.source.read_text())
        palette = self.paths.current_theme / 'colors.toml'
        palette.write_text(palette.read_text().replace('#111111', '#e0f0ff').replace('#4477cc', '#aa2200'))
        second = apply('steam', self.paths)
        self.assertEqual(second.status, 'applied')
        self.assertEqual(self.source.read_bytes(), (self.root / steam.CSS_PATH).read_bytes())
        self.assertIn('--adw-window-bg-rgb: 224,240,255', self.source.read_text())
        self.assertIn('--adw-accent-bg-rgb: 170,34,0', self.source.read_text())

    def test_noop_does_not_install_probe_or_rewrite_and_force_reapplies(self):
        apply('steam', self.paths)
        before = {p: p.stat().st_mtime_ns for p in steam.read_manifest(self.paths)}
        with patch('thpm.integrations.subprocess.run') as run:
            result = apply('steam', self.paths)
            run.assert_not_called()
        self.assertEqual(result.status, 'unchanged')
        self.assertEqual(result.restartRequired, [])
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in before})
        result = apply('steam', self.paths, force_reload=True)
        self.assertEqual(result.status, 'applied')
        self.assertTrue(result.actions)
        self.assertEqual(result.changed, [])

    def test_success_exit_is_not_proof_of_palette_or_consumption(self):
        for replacement, expected in (
            ('#!/usr/bin/env python3\n', 'validation failed'),
            (INSTALLER + "(ui / 'adwaita/colorthemes/omarchy/omarchy.css').write_text('stale')\n", 'active palette'),
            (INSTALLER + "(ui / 'libraryroot.custom.css').write_text('unwired')\n", 'does not import'),
            (INSTALLER + "library.write_text('unpatched')\n", 'does not consume'),
        ):
            with self.subTest(expected=expected):
                self.script.write_text(replacement)
                with self.assertRaisesRegex(ApplyFailure, expected):
                    apply('steam', self.paths)
                self.assertEqual(self.library.read_text(), 'original Steam CSS\n')
                self.assertFalse((self.root / steam.CSS_PATH).exists())

    def test_failure_and_timeout_are_truthful_and_recoverable(self):
        self.script.write_text("#!/usr/bin/env python3\nimport sys\nsys.exit('installer broke')\n")
        with self.assertRaisesRegex(ApplyFailure, 'installer broke') as failure:
            apply('steam', self.paths)
        self.assertEqual(failure.exception.changed, [str(self.source)])
        self.assertEqual(failure.exception.actions, [])
        self.assertEqual(self.library.read_text(), 'original Steam CSS\n')
        with patch('thpm.integrations.subprocess.run', side_effect=subprocess.TimeoutExpired('installer', 30)):
            with self.assertRaisesRegex(ApplyFailure, 'timed out'):
                apply('steam', self.paths)
        changed, warnings = cleanup_managed_outputs(self.paths, 'steam')
        self.assertFalse(warnings)
        self.assertIn(str(self.source), changed)
        self.assertEqual(self.source.read_text(), 'old source palette\n')

    def test_installer_is_bounded_quiet_and_targets_only_staging(self):
        original_run = subprocess.run
        with patch('thpm.integrations.subprocess.run', wraps=original_run) as run:
            apply('steam', self.paths)
        args, kwargs = run.call_args
        self.assertEqual(args[0][:3], [str(self.script), '--color-theme', 'omarchy'])
        self.assertEqual(args[0][3], '--target')
        self.assertNotEqual(args[0][4], str(self.root))
        self.assertEqual(kwargs, dict(cwd=self.script.parent, text=True, capture_output=True, check=False, timeout=30))

    def test_restart_notice_running_closed_and_probe_failure_never_kills(self):
        original_run = subprocess.run
        for code, expected in ((0, ['Steam']), (1, []), (2, ['Steam']), (None, ['Steam'])):
            def run(command, **kwargs):
                if command[0] == 'pgrep':
                    if code is None:
                        raise subprocess.TimeoutExpired(command, 2)
                    return subprocess.CompletedProcess(command, code, '', '')
                self.assertEqual(command[0], str(self.script))
                return original_run(command, **kwargs)
            with self.subTest(code=code), patch('thpm.integrations.shutil.which', return_value='/usr/bin/pgrep'), patch('thpm.integrations.subprocess.run', side_effect=run):
                result = apply('steam', self.paths, force_reload=True, automatic_restarts=True)
                self.assertEqual(result.restartRequired, expected)

    def test_displaced_tree_files_and_modes_restored_user_edits_preserved(self):
        css = self.root / steam.CSS_PATH
        css.parent.mkdir(parents=True)
        css.write_text('user palette\n')
        css.chmod(0o600)
        loader = self.root / steam.LOADER_PATH
        loader.write_text('user-selected loader\n')
        apply('steam', self.paths)
        (self.root / 'steamui/adwaita/adwaita.css').write_text('later user base edit\n')
        self.source.write_text('later source edit\n')
        changed, warnings = cleanup_managed_outputs(self.paths, 'steam')
        self.assertIn(str(css), changed)
        self.assertEqual(css.read_text(), 'user palette\n')
        self.assertEqual(css.stat().st_mode & 0o777, 0o600)
        self.assertEqual(loader.read_text(), 'user-selected loader\n')
        self.assertEqual(self.library.read_text(), 'original Steam CSS\n')
        self.assertEqual(self.library.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.source.read_text(), 'later source edit\n')
        self.assertEqual((self.root / 'steamui/adwaita/adwaita.css').read_text(), 'later user base edit\n')
        self.assertEqual(len(warnings), 2)
        self.assertFalse(steam.manifest_path(self.paths).exists())

    def test_user_edit_taken_over_on_next_apply_is_restored(self):
        apply('steam', self.paths)
        css = self.root / steam.CSS_PATH
        css.write_text('user edit between hooks\n')
        apply('steam', self.paths)
        cleanup_managed_outputs(self.paths, 'steam')
        self.assertEqual(css.read_text(), 'user edit between hooks\n')

    def test_missing_app_helper_invalid_palette_and_redirected_outputs(self):
        self.script.unlink()
        self.assertEqual(apply('steam', self.paths).status, 'skipped')
        self.script.write_text(INSTALLER)
        self.script.chmod(0o755)
        self.library.unlink()
        self.assertEqual(apply('steam', self.paths).status, 'skipped')
        self.library.write_text('original Steam CSS\n')
        (self.paths.current_theme / 'colors.toml').write_text('mode="dark"\n')
        with self.assertRaises(ValueError):
            apply('steam', self.paths)
        self.assertEqual(self.source.read_text(), 'old source palette\n')

    def test_corrupt_manifest_or_backup_retains_recovery(self):
        apply('steam', self.paths)
        state, backup = _asset_state_paths(self.paths, _target_key('steam', self.source))
        backup.write_text('corrupt')
        changed, warnings = cleanup_managed_outputs(self.paths, 'steam')
        self.assertTrue(warnings)
        self.assertTrue(state.exists())
        self.assertTrue(steam.manifest_path(self.paths).exists())
        backup.write_text('old source palette\n')
        self.assertFalse(cleanup_managed_outputs(self.paths, 'steam')[1])
        manifest = steam.manifest_path(self.paths)
        manifest.write_text(json.dumps([str(self.paths.home / '../outside')]))
        self.assertIn('invalid restoration manifest', cleanup_managed_outputs(self.paths, 'steam')[1][0])
        self.assertTrue(manifest.exists())

    def test_disable_and_uninstall_use_guarded_steam_cleanup(self):
        for operation in ('disable', 'uninstall'):
            with self.subTest(operation=operation):
                state = load(self.paths)
                state['steam'] = True
                save(self.paths, state)
                apply('steam', self.paths)
                css = self.root / steam.CSS_PATH
                css.write_text('user modified installed stylesheet\n')
                if operation == 'disable':
                    result = Service(self.paths).set_enabled('steam', False, refresh=False)
                else:
                    with patch('thpm.ui.run'):
                        result = Service(self.paths).uninstall()
                self.assertTrue(result['ok'], result)
                self.assertEqual(css.read_text(), 'user modified installed stylesheet\n')
                self.assertEqual(self.source.read_text(), 'old source palette\n')
                self.assertEqual(self.library.read_text(), 'original Steam CSS\n')

    def test_partial_publish_failure_reports_changed_files_and_recovers(self):
        from thpm.integrations import _install_optional_asset

        def install(paths, key, source, target, **kwargs):
            if target == self.root / steam.LOADER_PATH:
                raise OSError('publish failed')
            return _install_optional_asset(paths, key, source, target, **kwargs)

        with patch('thpm.integrations._install_optional_asset', side_effect=install):
            with self.assertRaisesRegex(ApplyFailure, 'publish failed') as failure:
                apply('steam', self.paths)
        self.assertIn(str(self.root / steam.CSS_PATH), failure.exception.changed)
        self.assertEqual(failure.exception.restart_required, ['Steam'])
        self.assertFalse(cleanup_managed_outputs(self.paths, 'steam')[1])
        self.assertEqual(self.library.read_text(), 'original Steam CSS\n')
        self.assertEqual(self.source.read_text(), 'old source palette\n')
        self.assertFalse((self.root / steam.CSS_PATH).exists())

    def test_unknown_legacy_outputs_are_not_deleted_without_ownership(self):
        css = self.root / steam.CSS_PATH
        css.parent.mkdir(parents=True)
        css.write_text('untracked legacy palette\n')
        self.assertEqual(cleanup_managed_outputs(self.paths, 'steam', assume_legacy=True), ([], []))
        self.assertEqual(css.read_text(), 'untracked legacy palette\n')

    def test_symlink_file_is_restored_and_redirected_directory_is_refused(self):
        css = self.root / steam.CSS_PATH
        css.parent.mkdir(parents=True)
        user_file = self.paths.home / 'user-palette.css'
        user_file.write_text('user palette\n')
        css.symlink_to(user_file)
        apply('steam', self.paths)
        self.assertFalse(css.is_symlink())
        cleanup_managed_outputs(self.paths, 'steam')
        self.assertTrue(css.is_symlink())
        self.assertEqual(user_file.read_text(), 'user palette\n')
        css.unlink()
        css.parent.rmdir()
        css.parent.symlink_to(self.paths.home, target_is_directory=True)
        with self.assertRaisesRegex(ApplyFailure, 'redirected output parent'):
            apply('steam', self.paths)
        self.assertEqual(user_file.read_text(), 'user palette\n')

    @unittest.skipUnless(os.environ.get('THPM_TEST_STEAM_ADWAITA'), 'set THPM_TEST_STEAM_ADWAITA to a reviewed steam-adwaita checkout')
    def test_real_steam_adwaita_installer_in_isolated_home(self):
        reviewed = Path(os.environ['THPM_TEST_STEAM_ADWAITA']).resolve()
        shutil.rmtree(self.script.parent)
        shutil.copytree(reviewed, self.script.parent, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        # Restore a recognizable pre-THPM baseline independent of that checkout.
        self.source.parent.mkdir(parents=True, exist_ok=True)
        self.source.write_text('old source palette\n')
        original = '/* isolated Steam library fixture */\n' + (' ' * 10000)
        self.library.write_text(original)
        for background, accent, mode in (('#121212', '#0055ff', 'dark'), ('#ffeedd', '#aa2200', 'light')):
            palette = dict(COLORS, bg=background, accent=accent, mode=mode)
            (self.paths.current_theme / 'colors.toml').write_text('\n'.join(f'{k} = "{v}"' for k, v in palette.items()) + '\n')
            result = apply('steam', self.paths)
            self.assertEqual(result.status, 'applied')
            steam.validate(self.root, steam.render(palette))
            self.assertEqual(self.source.read_bytes(), (self.root / steam.CSS_PATH).read_bytes())
            self.assertEqual(apply('steam', self.paths).status, 'unchanged')
        self.assertEqual(apply('steam', self.paths, force_reload=True).status, 'applied')
        self.assertFalse(cleanup_managed_outputs(self.paths, 'steam')[1])
        self.assertEqual(self.library.read_text(), original)
        self.assertEqual(self.source.read_text(), 'old source palette\n')
        self.assertFalse((self.root / steam.CSS_PATH).exists())

    def test_commented_import_is_not_consumption(self):
        self.script.write_text(INSTALLER + "(ui / 'libraryroot.custom.css').write_text('/*' + (ui / 'libraryroot.custom.css').read_text() + '*/')\n")
        with self.assertRaisesRegex(ApplyFailure, 'does not import'):
            apply('steam', self.paths)

    def test_identical_untracked_content_is_restored_not_deleted(self):
        self.source.write_text(steam.render(COLORS))
        apply('steam', self.paths)
        cleanup_managed_outputs(self.paths, 'steam')
        self.assertEqual(self.source.read_text(), steam.render(COLORS))

    def test_disable_incomplete_keeps_recovery_and_retry_succeeds(self):
        state = load(self.paths)
        state['steam'] = True
        save(self.paths, state)
        apply('steam', self.paths)
        _, backup = _asset_state_paths(self.paths, _target_key('steam', self.source))
        backup.write_text('corrupt')
        result = Service(self.paths).set_enabled('steam', False, refresh=False)
        self.assertFalse(result['ok'])
        self.assertTrue(result['cleanupIncomplete'])
        self.assertTrue(steam.manifest_path(self.paths).exists())
        backup.write_text('old source palette\n')
        self.assertTrue(Service(self.paths).set_enabled('steam', False, refresh=False)['ok'])

    def test_multiple_installs_and_duplicate_symlink_are_supported(self):
        link = self.paths.home / '.steam/steam'
        link.parent.mkdir(parents=True)
        link.symlink_to(self.root, target_is_directory=True)
        flatpak = self.paths.home / '.var/app/com.valvesoftware.Steam/.steam/steam'
        library = flatpak / steam.LIBRARY_PATH
        library.parent.mkdir(parents=True)
        library.write_text('flatpak original\n')
        result = apply('steam', self.paths)
        self.assertEqual(len(result.actions), 2)
        steam.validate(flatpak, self.source.read_text())
        cleanup_managed_outputs(self.paths, 'steam')
        self.assertEqual(library.read_text(), 'flatpak original\n')


if __name__ == '__main__':
    unittest.main()
