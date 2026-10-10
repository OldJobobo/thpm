from __future__ import annotations

import base64
import shutil
import subprocess
import unittest
from unittest.mock import patch

from test_thpm import COLORS, Sandbox
from thpm import hermes_desktop
from thpm.integrations import apply, cleanup_managed_outputs, inspect_readiness
from thpm.palette import _strict
from thpm.service import Service
from thpm.state import load, save


class LocalHermesDesktopTests(Sandbox):
    def setUp(self):
        super().setUp()
        self.write_palette()
        self.bundle = self.paths.home / '.hermes/hermes-agent/apps/desktop/release/linux-unpacked/resources/app.asar.unpacked/dist'
        (self.bundle / 'assets').mkdir(parents=True)
        (self.bundle / 'electron-main.mjs').write_text('hermes:fs:desktopPluginsRoot')
        (self.bundle / 'assets/renderer.js').write_text('hermes-desktop-user-themes-v1 @hermes/plugin-sdk')
        self.palette_patch = patch('thpm.integrations.load_palette', side_effect=_strict)
        self.palette_patch.start()
        self.addCleanup(self.palette_patch.stop)

    def test_palette_slots_and_terminal_follow_semantic_colors(self):
        palette = dict(COLORS, accent='#abcdef', mode='light')
        data = hermes_desktop.theme(palette)
        self.assertEqual(data['name'], 'thpm-local-omarchy')
        self.assertEqual(data['colors'], data['darkColors'])
        self.assertEqual(data['terminal'], data['darkTerminal'])
        self.assertEqual(data['colors']['background'], COLORS['bg'])
        self.assertEqual(data['colors']['primary'], '#abcdef')
        self.assertEqual(data['terminal']['brightCyan'], COLORS['bright_cyan'])

    def test_apply_switch_noop_and_no_external_commands(self):
        with patch('thpm.integrations.subprocess.run') as run:
            first = apply('hermes-desktop-local', self.paths)
            target = hermes_desktop.target(self.paths)
            stamp = target.stat().st_mtime_ns
            second = apply('hermes-desktop-local', self.paths)
            run.assert_not_called()
        self.assertEqual(first.status, 'applied')
        self.assertEqual(second.status, 'unchanged')
        self.assertEqual(target.stat().st_mtime_ns, stamp)
        self.assertIn('select it', first.message)
        self.assertEqual(first.restartRequired, [])
        palette = self.paths.current_theme / 'colors.toml'
        palette.write_text(palette.read_text().replace('#111111', '#fefefe'))
        self.assertEqual(apply('hermes-desktop-local', self.paths).status, 'applied')
        self.assertIn('"background":"#fefefe"', target.read_text())

    def test_unsupported_renderer_is_skipped_and_readiness_is_truthful(self):
        (self.bundle / 'assets/renderer.js').unlink()
        available, missing, _warnings = inspect_readiness('hermes-desktop-local', self.paths)
        self.assertFalse(available)
        self.assertIn('renderer lacks', missing[0])
        result = apply('hermes-desktop-local', self.paths)
        self.assertEqual(result.status, 'skipped')
        self.assertFalse(hermes_desktop.target(self.paths).exists())

    def test_named_local_profile_and_redirected_parent_are_refused(self):
        profile = self.paths.config_home / 'Hermes/active-profile.json'
        profile.parent.mkdir(parents=True)
        profile.write_text('{"profile":"named"}')
        self.assertFalse(hermes_desktop.readiness(self.paths)[0])
        profile.write_text('{"profile":"default"}')
        # A CLI-agent profile must not be confused with Desktop's local root.
        (self.paths.home / '.hermes/active_profile').write_text('another-cli-profile')
        self.assertTrue(hermes_desktop.readiness(self.paths)[0])
        root = self.paths.home / '.hermes/desktop-plugins'
        root.symlink_to(self.paths.home, target_is_directory=True)
        self.assertIn('redirected', hermes_desktop.readiness(self.paths)[1])

    def test_invalid_palette_does_not_displace_a_plugin(self):
        target = hermes_desktop.target(self.paths)
        target.parent.mkdir(parents=True)
        target.write_text('user plugin')
        (self.paths.current_theme / 'colors.toml').write_text('mode="dark"')
        with self.assertRaises(ValueError):
            apply('hermes-desktop-local', self.paths)
        self.assertEqual(target.read_text(), 'user plugin')

    def test_guarded_restoration_preserves_displaced_modes_and_later_edits(self):
        target = hermes_desktop.target(self.paths)
        target.parent.mkdir(parents=True)
        target.write_text('user plugin')
        target.chmod(0o600)
        apply('hermes-desktop-local', self.paths)
        self.assertFalse(cleanup_managed_outputs(self.paths, 'hermes-desktop-local')[1])
        self.assertEqual(target.read_text(), 'user plugin')
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        apply('hermes-desktop-local', self.paths)
        target.write_text('later user edit')
        self.assertIn('preserved user-modified', cleanup_managed_outputs(self.paths, 'hermes-desktop-local')[1][0])
        self.assertEqual(target.read_text(), 'later user edit')

    def test_disable_and_uninstall_leave_connection_skin_and_selection_files_untouched(self):
        for operation in ('disable', 'uninstall'):
            with self.subTest(operation=operation):
                protected = [self.paths.config_home / 'Hermes/connection.json', self.paths.config_home / 'Hermes/Preferences', self.paths.home / '.hermes/config.yaml', self.paths.home / '.hermes/skins/omarchy.yaml']
                for path in protected:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('protected user state')
                state = load(self.paths)
                state['hermes-desktop-local'] = True
                save(self.paths, state)
                apply('hermes-desktop-local', self.paths)
                if operation == 'disable':
                    result = Service(self.paths).set_enabled('hermes-desktop-local', False, refresh=False)
                else:
                    with patch('thpm.ui.run'):
                        result = Service(self.paths).uninstall()
                self.assertTrue(result['ok'], result)
                self.assertFalse(hermes_desktop.target(self.paths).exists())
                for path in protected:
                    self.assertEqual(path.read_text(), 'protected user state')

    @unittest.skipUnless(shutil.which('node'), 'Node is needed for the real ESM plugin contract test')
    def test_generated_esm_registers_theme_and_observes_without_selecting_or_rpc(self):
        plugin = hermes_desktop.render(COLORS)
        uri = 'data:text/javascript;base64,' + base64.b64encode(plugin.encode()).decode()
        harness = '''
let observed, disposed, registered;
const diagnostics = {};
globalThis.document = {documentElement:{dataset:{hermesTheme:'another-user-theme'}}};
globalThis.getComputedStyle = () => ({getPropertyValue:key => key==='--theme-background-seed' ? '#111111' : '#dddddd'});
globalThis.MutationObserver = class {constructor(callback){this.callback=callback;} observe(_root,opts){observed=opts;} disconnect(){disposed=true;}};
const plugin = (await import(process.argv[1])).default;
let cleanup;
plugin.register({register:data=>{registered=data;},onDispose:fn=>{cleanup=fn;},storage:{set:(key,value)=>{diagnostics[key]=value;}}});
await new Promise(resolve=>setTimeout(resolve,250));
cleanup();
if(registered.area!=='themes' || registered.data.colors.background!=='#111111' || !disposed || observed.attributeFilter[0]!=='data-hermes-theme') process.exit(2);
if(document.documentElement.dataset.hermesTheme!=='another-user-theme' || diagnostics.consumption.selected!==false || !diagnostics.registration.fingerprint) process.exit(3);
console.log('verified supported contribution registration, observation and disposal');
'''
        completed = subprocess.run(['node', '--input-type=module', '-e', harness, uri], capture_output=True, text=True, check=True, timeout=5)
        self.assertIn('"selected":false', completed.stdout)
        self.assertIn('verified supported contribution', completed.stdout)
        self.assertNotIn('requestTheme(', plugin)
        self.assertNotIn('localStorage', plugin)
        self.assertNotIn('host.request', plugin)


if __name__ == '__main__':
    unittest.main()
