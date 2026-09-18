import io
import json
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


from tests.skill_scripts import android_emulator


class AndroidEmulatorTests(unittest.TestCase):
    def setUp(self):
        self.module = android_emulator
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.manager = self.module.EmulatorManager(Path('/sdk'), Path(self.tmp.name), timeout=3)
        self.commands = []
        self.devices = []
        self.booted = True
        self.job = ''
        self.avds = ['Phone']
        runtime = patch.object(self.module.SdkProvisioner, 'ensure_runtime')
        runtime.start()
        self.addCleanup(runtime.stop)
        self.fake = patch.object(self.manager, 'run', side_effect=self.run_command)
        self.fake.start()
        self.addCleanup(self.fake.stop)
        ports = patch.object(self.module, 'free_port', return_value=5554)
        ports.start()
        self.addCleanup(ports.stop)

    def run_command(self, args, check=True):
        args = list(map(str, args))
        self.commands.append(args)
        output, code = '', 0
        if args[1:] == ['devices']:
            output = 'List of devices attached\n' + '\n'.join(f'{s}\t{state}' for s, state, _ in self.devices)
        elif args[-3:] == ['emu', 'avd', 'name']:
            output = next(n for s, _, n in self.devices if s == args[2]) + '\nOK\n'
        elif args[-3:] == ['shell', 'getprop', 'sys.boot_completed']:
            output = '1\n' if self.booted else '0\n'
        elif args[-3:] == ['shell', 'wm', 'size']:
            output = 'Physical size: 1080x2400\nOverride size: 750x1624\n'
        elif args[-3:] == ['shell', 'wm', 'density']:
            output = 'Physical density: 420\nOverride density: 320\n'
        elif args[-4:] == ['settings', 'get', 'system', 'font_scale']:
            output = '1.0\n'
        elif args[-3:] == ['shell', 'getprop', 'ro.build.version.sdk']:
            output = '33\n'
        elif args[-1] == '-list-avds':
            output = '\n'.join(self.avds)
        elif 'print' in args:
            output, code = self.job, 0 if self.job else 113
        elif 'bootstrap' in args:
            self.job = 'state = running\npid = 1234'
            self.devices = [('emulator-5554', 'device', 'Phone')]
        elif 'bootout' in args:
            self.job = ''
        return subprocess.CompletedProcess(args, code, output, '')

    def test_reuses_ready_emulator_without_launching_or_stopping_it(self):
        self.devices = [('emulator-5560', 'device', 'Phone')]
        result = self.manager.ensure('Phone')
        self.assertEqual(result['serial'], 'emulator-5560')
        self.assertEqual(result['source'], 'reused')
        self.assertFalse(any('bootstrap' in c or 'bootout' in c for c in self.commands))
        self.assertEqual(result['avd'], 'Phone')
        self.assertEqual(result['adb_args'], ['/sdk/platform-tools/adb', '-s', 'emulator-5560'])
        self.assertEqual(result['status'], 'ready')
        self.assertIn('created', result)

    def test_absent_avd_is_created_then_started(self):
        self.avds = []
        with patch.object(self.module.SdkProvisioner, 'ensure_avd', return_value='Phone') as create:
            result = self.manager.ensure('Phone', api=35, device='pixel_6')
        create.assert_called_once_with('Phone', 35, 'pixel_6')
        self.assertEqual(result['serial'], 'emulator-5554')
        self.assertEqual(result['source'], 'started')

    def test_physical_device_reused_without_emulator_install_or_console(self):
        self.devices = [('USB123', 'device', None)]
        with patch.object(self.module.SdkProvisioner, 'ensure_runtime') as runtime:
            result = self.manager.ensure(width=750, height=1624, density=320)
        runtime.assert_called_once_with(adb_only=True)
        self.assertEqual(result['device_type'], 'physical')
        self.assertIsNone(result['avd'])
        self.assertEqual(result['api'], 33)
        self.assertEqual(result['screen']['logical_width_dp'], 375)
        self.assertEqual(result['screen']['logical_height_dp'], 812)
        self.assertTrue(result['screen']['matches_target'])
        self.assertEqual(result['screen']['font_scale'], 1.0)
        self.assertFalse(any('emu' in c or 'bootstrap' in c for c in self.commands))

    def test_explicit_serial_wins_over_other_connected_devices(self):
        self.devices = [('USB123', 'device', None), ('emulator-5554', 'device', 'Phone')]
        result = self.manager.ensure(serial='USB123')
        self.assertEqual(result['adb_args'][-1], 'USB123')

    def test_phone_offline_unauthorized_or_missing_immediately_falls_back(self):
        for state in ('offline', 'unauthorized', 'missing'):
            with self.subTest(state=state):
                self.devices = [('emulator-5554', 'device', 'Phone')]
                if state != 'missing':
                    self.devices.append(('USB123', state, None))
                result = self.manager.ensure(serial='USB123')
                self.assertEqual(result['serial'], 'emulator-5554')
                self.assertIn('USB123', result['selection']['fallback_reason'])
        self.assertFalse(any('bootstrap' in c for c in self.commands))

    def test_only_unavailable_phone_starts_emulator_without_waiting_for_phone(self):
        self.devices = [('USB123', 'unauthorized', None)]
        result = self.manager.ensure()
        self.assertEqual(result['serial'], 'emulator-5554')
        self.assertEqual(result['source'], 'started')
        self.assertIn('unauthorized', result['selection']['fallback_reason'])

    def test_default_prefers_phone_over_online_emulators(self):
        self.devices = [('emulator-5554', 'device', 'Phone'),
                        ('USB123', 'device', None), ('emulator-5556', 'device', 'Other')]
        result = self.manager.ensure()
        self.assertEqual(result['serial'], 'USB123')
        self.assertEqual(result['device_type'], 'physical')
        self.assertFalse(any('bootstrap' in c or 'bootout' in c for c in self.commands))

    def test_reconnected_phone_selected_on_next_ensure(self):
        self.devices = [('USB123', 'offline', None), ('emulator-5554', 'device', 'Phone')]
        first = self.manager.ensure()
        self.assertEqual(first['serial'], 'emulator-5554')
        self.devices[0] = ('USB123', 'device', None)
        second = self.manager.ensure()
        self.assertEqual(second['serial'], 'USB123')
        self.assertIsNone(second['selection']['fallback_reason'])

    def test_explicit_emulator_selection_overrides_phone_priority(self):
        self.devices = [('USB123', 'device', None), ('emulator-5554', 'device', 'Phone')]
        for selector in ({'serial': 'emulator-5554'}, {'avd': 'Phone'}):
            with self.subTest(selector=selector):
                self.assertEqual(self.manager.ensure(**selector)['serial'], 'emulator-5554')

    def test_multiple_phones_or_only_multiple_emulators_require_selection(self):
        for rows in (
            [('USB123', 'device', None), ('USB456', 'device', None),
             ('emulator-5554', 'device', 'Phone')],
            [('emulator-5554', 'device', 'Phone'), ('emulator-5556', 'device', 'Other')],
        ):
            with self.subTest(rows=rows):
                self.devices = rows
                with self.assertRaisesRegex(self.module.EmulatorError, '--serial'):
                    self.manager.ensure()

    def test_missing_selected_phone_falls_back_to_other_phone_before_emulator(self):
        self.devices = [('USB456', 'device', None), ('emulator-5554', 'device', 'Phone')]
        result = self.manager.ensure(serial='USB123')
        self.assertEqual(result['serial'], 'USB456')
        self.assertIn('USB123', result['selection']['fallback_reason'])

    def test_screen_mismatch_reuses_device_and_reports_difference(self):
        self.devices = [('USB123', 'device', None)]
        result = self.manager.ensure(width=1080, height=2400, density=420)
        self.assertEqual(result['serial'], 'USB123')
        self.assertFalse(result['screen']['matches_target'])
        self.assertTrue(result['screen']['differences'])
        self.assertFalse(any(c[-2:] == ['wm', 'reset'] or 'bootstrap' in c for c in self.commands))

    def test_api_mismatch_does_not_silently_launch_another_device(self):
        self.devices = [('USB123', 'device', None)]
        with self.assertRaisesRegex(self.module.EmulatorError, 'API'):
            self.manager.ensure(api=35)
        self.assertFalse(any('bootstrap' in c for c in self.commands))

    def test_partial_screen_arguments_rejected_before_preparation(self):
        with patch.object(self.module.SdkProvisioner, 'ensure_runtime') as runtime:
            with self.assertRaisesRegex(ValueError, 'width.*height.*density'):
                self.manager.ensure(width=750)
        runtime.assert_not_called()

    def test_stopped_avd_mismatch_is_not_started_or_modified(self):
        with patch.object(self.module.SdkProvisioner, 'avd_config', return_value={
                'hw.lcd.width': '1080', 'hw.lcd.height': '2400', 'hw.lcd.density': '420'}):
            with self.assertRaisesRegex(self.module.EmulatorError, '不匹配'):
                self.manager.ensure('Phone', width=750, height=1624, density=320)
        self.assertFalse(any('bootstrap' in c for c in self.commands))

    def test_preparation_failure_returns_one_json_and_no_usable_serial(self):
        out = io.StringIO()
        with patch.object(self.module, 'resolve_sdk', return_value=Path('/sdk')), \
                patch.object(self.module.Path, 'home', return_value=Path(self.tmp.name)), \
                patch.object(self.module.platform, 'system', return_value='Darwin'), \
                patch.object(self.module.SdkProvisioner, 'ensure_runtime', side_effect=self.module.PreparationError('SDK 许可未接受')), \
                patch('sys.stdout', out):
            code = self.module.main(['ensure', '--avd', 'Phone'])
        result = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(result['status'], 'error')
        self.assertIsNone(result['serial'])
        self.assertEqual(result['avd'], 'Phone')
        self.assertEqual(result['stage'], 'prepare_runtime')

    def test_new_job_owns_emulator_sleep_assertion_and_output(self):
        result = self.manager.ensure('Phone')
        self.assertEqual(result['source'], 'started')
        plist_path = Path(next(c[-1] for c in self.commands if 'bootstrap' in c))
        config = plistlib.loads(plist_path.read_bytes())
        self.assertEqual(config['ProgramArguments'][:3], ['/usr/bin/caffeinate', '-i', '/sdk/emulator/emulator'])
        self.assertEqual(config['StandardInPath'], '/dev/null')
        self.assertTrue(Path(config['StandardOutPath']).is_absolute())
        self.assertEqual(config['StandardOutPath'], config['StandardErrorPath'])
        self.assertFalse(config.get('KeepAlive', False))
        self.assertNotIn('bootout', [c[1] for c in self.commands])

    def test_booting_existing_device_times_out_without_duplicate(self):
        self.devices = [('emulator-5554', 'device', 'Phone')]
        self.booted = False
        self.manager.timeout = 0.02
        with self.assertRaisesRegex(self.module.EmulatorError, '超时'):
            self.manager.ensure('Phone')
        self.assertFalse(any('bootstrap' in c for c in self.commands))

    def test_running_managed_job_waits_instead_of_restarting(self):
        self.job = 'state = running\npid = 1234'
        self.manager.timeout = 0.02
        with self.assertRaisesRegex(self.module.EmulatorError, '超时'):
            self.manager.ensure('Phone')
        self.assertFalse(any('bootstrap' in c or 'bootout' in c for c in self.commands))

    def test_exited_job_can_be_started_again(self):
        self.job = 'state = exited\nlast exit code = 1'
        self.assertEqual(self.manager.ensure('Phone')['source'], 'started')
        actions = [c[1] for c in self.commands]
        self.assertLess(actions.index('bootout'), actions.index('bootstrap'))

    def test_multiple_avds_require_selection(self):
        self.avds = ['Phone', 'Tablet']
        with self.assertRaisesRegex(self.module.EmulatorError, '--avd'):
            self.manager.ensure(None)
        self.assertFalse(any('bootstrap' in c for c in self.commands))

    def test_offline_device_does_not_trigger_duplicate_launch(self):
        self.devices = [('emulator-5554', 'offline', '')]
        with self.assertRaisesRegex(self.module.EmulatorError, 'offline'):
            self.manager.ensure('Phone')
        self.assertFalse(any('bootstrap' in c for c in self.commands))

    def test_stop_only_unloads_the_managed_job(self):
        self.job = 'state = running\npid = 1234'
        self.manager.stop('Phone')
        self.assertTrue(any('bootout' in c for c in self.commands))
        self.assertFalse(any('kill' in c or 'pkill' in c for c in self.commands))

    def test_command_execution_has_deadline_and_no_inherited_streams(self):
        self.fake.stop()
        with patch.object(self.module.subprocess, 'run', side_effect=subprocess.TimeoutExpired('adb', 1)) as run:
            with self.assertRaisesRegex(self.module.EmulatorError, '超时'):
                self.manager.run(['/sdk/platform-tools/adb', 'devices'])
            self.assertLessEqual(run.call_args.kwargs['timeout'], 3)
            self.assertEqual(run.call_args.kwargs['stdin'], subprocess.DEVNULL)
            self.assertTrue(run.call_args.kwargs['capture_output'])

    def test_lock_is_exclusive_and_released(self):
        with self.module.device_lock(Path(self.tmp.name), 1):
            with self.assertRaisesRegex(self.module.EmulatorError, '超时'):
                with self.module.device_lock(Path(self.tmp.name), 0.01):
                    self.fail('duplicate lock acquired')
        with self.module.device_lock(Path(self.tmp.name), 0.01):
            pass

    def test_non_mac_fails_before_sdk_or_service_operations(self):
        with patch.object(self.module.platform, 'system', return_value='Linux'), \
                patch.object(self.module, 'resolve_sdk') as sdk, \
                patch('sys.stdout'):
            self.assertEqual(self.module.main(['ensure']), 1)
            sdk.assert_not_called()


if __name__ == '__main__':
    unittest.main()
