import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tests.skill_scripts import android_emulator as emulator


class AndroidPreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def preparer(self):
        self.assertTrue(hasattr(emulator, 'SdkProvisioner'), 'ensure 尚未接入 SDK/AVD 自动准备')
        return emulator.SdkProvisioner(self.root / 'sdk', self.root / 'state', timeout=10)

    def executable(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/bin/sh\nexit 0\n')
        path.chmod(0o755)

    def test_missing_explicit_sdk_is_kept_as_install_destination(self):
        self.assertEqual(emulator.resolve_sdk(str(self.root / 'new'), allow_missing=True), self.root / 'new')

    def test_ready_runtime_needs_no_download_or_java(self):
        p = self.preparer()
        for rel in ('platform-tools/adb', 'emulator/emulator'):
            self.executable(p.sdk / rel)
        with patch.object(p, 'ensure_command_tools') as tools:
            p.ensure_runtime()
        tools.assert_not_called()

    def test_missing_runtime_installs_only_missing_package(self):
        p = self.preparer()
        self.executable(p.sdk / 'platform-tools/adb')
        def install(packages):
            self.assertEqual(packages, ['emulator'])
            self.executable(p.sdk / 'emulator/emulator')
        with patch.object(p, 'install', side_effect=install) as call:
            p.ensure_runtime()
        self.assertEqual(call.call_count, 1)

    def test_image_architecture_and_creation_without_force(self):
        p = self.preparer()
        image = p.sdk / 'system-images/android-35/google_apis/arm64-v8a/system.img'
        def install(packages):
            self.assertEqual(packages, ['system-images;android-35;google_apis;arm64-v8a'])
            image.parent.mkdir(parents=True)
            image.write_text('image')
        commands = []
        def run(args, **kwargs):
            commands.append((list(map(str, args)), kwargs))
            config = Path(args[args.index('--path') + 1]) / 'config.ini'
            config.parent.mkdir(parents=True)
            config.write_text('image.sysdir.1=system-images/android-35/google_apis/arm64-v8a/\nhw.device.name=pixel_6\n')
            (p.avd_home / 'Test.ini').write_text(f'path={config.parent}\n')
            return subprocess.CompletedProcess(args, 0, '', '')
        with patch.object(p, 'install', side_effect=install), patch.object(p, 'ensure_command_tools', return_value=p.sdk / 'cmdline-tools/19.0/bin'), patch.object(p, 'run', side_effect=run), patch('android_sdk.platform.machine', return_value='arm64'), patch.dict('os.environ', {'ANDROID_AVD_HOME': str(self.root / 'avds')}):
            result = p.ensure_avd('Test', 35, 'pixel_6')
        self.assertEqual(result, 'Test')
        self.assertNotIn('--force', commands[0][0])
        self.assertNotIn('-f', commands[0][0])
        self.assertEqual(commands[0][1]['input_text'], 'no\n')

    def test_existing_avd_wrong_api_is_not_overwritten(self):
        p = self.preparer()
        with patch.dict('os.environ', {'ANDROID_AVD_HOME': str(self.root / 'avds')}):
            config = p.avd_home / 'Test.avd/config.ini'
            config.parent.mkdir(parents=True)
            config.write_text('image.sysdir.1=system-images/android-23/google_apis/arm64-v8a/\nhw.device.name=pixel_6\n')
            (p.avd_home / 'Test.ini').write_text(f'path={config.parent}\n')
            with patch.object(p, 'install') as install:
                with self.assertRaisesRegex(RuntimeError, '不匹配|不覆盖'):
                    p.ensure_avd('Test', 35, 'pixel_6')
            install.assert_not_called()
            self.assertIn('android-23', config.read_text())

    def test_sdkmanager_exit_zero_but_license_not_accepted_is_failure(self):
        p = self.preparer()
        with patch.object(p, 'ensure_command_tools', return_value=p.sdk / 'cmdline-tools/19.0/bin'), patch.object(p, 'run', return_value=subprocess.CompletedProcess([], 0, 'License not accepted. Skipping packages.', '')):
            with self.assertRaisesRegex(RuntimeError, '许可'):
                p.install(['emulator'])

    def test_install_is_skipped_if_package_is_complete(self):
        p = self.preparer()
        self.executable(p.sdk / 'emulator/emulator')
        with patch.object(p, 'ensure_command_tools') as tool:
            p.install(['emulator'])
        tool.assert_not_called()

    def test_incomplete_image_is_not_treated_as_installed(self):
        p = self.preparer()
        package = 'system-images;android-35;google_apis;arm64-v8a'
        folder = p.sdk.joinpath(*package.split(';'))
        folder.mkdir(parents=True)
        (folder / 'system.img').write_text('partial image')
        self.assertFalse(p.package_ready(package))

    def test_existing_avd_with_missing_image_downloads_its_original_package(self):
        p = self.preparer()
        self.assertTrue(hasattr(p, 'ensure_avd_image'))
        with patch.object(p, 'avd_config', return_value={'image.sysdir.1': 'system-images/android-34/google_apis/x86_64/'}), patch.object(p, 'install') as install:
            p.ensure_avd_image('Existing')
        install.assert_called_once_with(['system-images;android-34;google_apis;x86_64'])

    def test_decimal_api_image_path_is_supported(self):
        p = self.preparer()
        with patch.object(p, 'avd_config', return_value={'image.sysdir.1': 'system-images/android-37.1/google_apis_playstore_ps16k/arm64-v8a/'}), patch.object(p, 'install') as install:
            p.ensure_avd_image('Existing')
        install.assert_called_once_with(['system-images;android-37.1;google_apis_playstore_ps16k;arm64-v8a'])

    def test_screen_mismatch_never_changes_existing_avd(self):
        p = self.preparer()
        with patch.dict('os.environ', {'ANDROID_AVD_HOME': str(self.root / 'avds')}):
            config = p.avd_home / 'Phone.avd/config.ini'
            config.parent.mkdir(parents=True)
            original = 'image.sysdir.1=system-images/android-35/google_apis/arm64-v8a/\nhw.device.name=pixel_6\nhw.lcd.width=1080\nhw.lcd.height=2400\nhw.lcd.density=420\n'
            config.write_text(original)
            with self.assertRaisesRegex(RuntimeError, '屏幕.*不匹配'):
                p.ensure_avd('Phone', 35, 'pixel_6', screen={'width_px': 750, 'height_px': 1624, 'density_dpi': 320})
            self.assertEqual(config.read_text(), original)

    def test_interrupted_owned_avd_is_cleaned_before_retry(self):
        p = self.preparer()
        owned = p.state_dir / 'avds/Test.avd'
        owned.mkdir(parents=True)
        (owned / 'partial').touch()
        pending = p.state_dir / 'creating-Test.json'
        pending.write_text(json.dumps({'name': 'Test', 'path': str(owned)}))
        with patch.dict('os.environ', {'ANDROID_AVD_HOME': str(self.root / 'avds')}):
            p.avd_home.mkdir()
            index = p.avd_home / 'Test.ini'
            index.write_text(f'path={owned}\n')
            with patch.object(p, 'install', side_effect=RuntimeError('network unavailable')):
                with self.assertRaisesRegex(RuntimeError, 'network unavailable'):
                    p.ensure_avd('Test', 35, 'pixel_6')
            self.assertFalse(owned.exists())
            self.assertFalse(index.exists())
            self.assertFalse(pending.exists())

    def test_bootstrap_checks_checksum_and_preserves_executable_bits(self):
        p = self.preparer()
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as z:
            for name in ('sdkmanager', 'avdmanager'):
                z.writestr(f'cmdline-tools/bin/{name}', '#!/bin/sh\nexit 0\n')
        archive = data.getvalue()
        def download(url, destination):
            destination.write_bytes(archive)
        with patch('android_sdk.TOOLS_SHA1', hashlib.sha1(archive).hexdigest()), patch.object(p, 'download', side_effect=download):
            path = p.bootstrap_tools()
        self.assertTrue((path / 'sdkmanager').stat().st_mode & 0o111)
        with patch.object(p, 'download') as download:
            self.assertEqual(p.bootstrap_tools(), path)
        download.assert_not_called()

    def test_bad_checksum_does_not_publish_install(self):
        p = self.preparer()
        with patch.object(p, 'download', side_effect=lambda url, dest: dest.write_bytes(b'bad')):
            with self.assertRaisesRegex(RuntimeError, '校验'):
                p.bootstrap_tools()
        self.assertFalse((p.sdk / 'cmdline-tools/19.0').exists())

    def test_prepare_timeout_retains_log_and_terminates_process_group(self):
        p = self.preparer()
        with patch('android_sdk.subprocess.Popen') as popen, patch('android_sdk.os.killpg') as kill:
            proc = popen.return_value
            proc.pid = 54321
            proc.communicate.side_effect = [subprocess.TimeoutExpired('sdkmanager', 1), ('', '')]
            with self.assertRaisesRegex(RuntimeError, '超时'):
                p.run(['fake-sdkmanager'])
        kill.assert_called_once()
        self.assertTrue(p.log_path.exists())
        self.assertTrue(popen.call_args.kwargs['start_new_session'])


class SdkProcessIntegrationTests(unittest.TestCase):
    setUp = AndroidPreparationTests.setUp
    preparer = AndroidPreparationTests.preparer
    executable = AndroidPreparationTests.executable
    def test_real_child_commands_prepare_and_reuse_isolated_sdk(self):
        p = self.preparer()
        tools = p.sdk / 'cmdline-tools/19.0/bin'
        tools.mkdir(parents=True)
        java_home = self.root / 'jdk'
        self.executable(java_home / 'bin/java')
        installer = tools / 'sdkmanager'
        installer.write_text(f"#!{sys.executable}\n" + r"""
import os, pathlib, sys
sdk = pathlib.Path(os.environ['ANDROID_SDK_ROOT'])
with (sdk / 'installs.log').open('a') as log: log.write(repr(sys.argv) + '\n')
for package in sys.argv[1:]:
    if package == 'platform-tools': path = sdk / 'platform-tools/adb'
    elif package == 'emulator': path = sdk / 'emulator/emulator'
    elif package.startswith('system-images;'): path = sdk.joinpath(*package.split(';')) / 'system.img'
    else: continue
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/sh\nexit 0\n')
    path.chmod(0o755)
    if package.startswith('system-images;'): (path.parent / 'package.xml').write_text('<installed/>')
""")
        creator = tools / 'avdmanager'
        creator.write_text(f"#!{sys.executable}\n" + r"""
import os, pathlib, sys
assert sys.stdin.read() == 'no\n'
name = sys.argv[sys.argv.index('--name') + 1]
package = sys.argv[sys.argv.index('--package') + 1]
device = sys.argv[sys.argv.index('--device') + 1]
home = pathlib.Path(os.environ['ANDROID_AVD_HOME'])
path = pathlib.Path(sys.argv[sys.argv.index('--path') + 1])
path.mkdir()
(path / 'config.ini').write_text('image.sysdir.1=' + package.replace(';','/') + '/\nhw.device.name=' + device + '\nabi.type=arm64-v8a\n')
(home / (name + '.ini')).write_text('path=' + str(path) + '\n')
""")
        installer.chmod(0o755)
        creator.chmod(0o755)
        with patch.dict('os.environ', {'JAVA_HOME': str(java_home), 'ANDROID_AVD_HOME': str(self.root / 'avds')}), patch('android_sdk.platform.machine', return_value='arm64'):
            p = self.preparer()
            p.ensure_runtime()
            screen = {'width_px': 750, 'height_px': 1624, 'density_dpi': 320}
            p.ensure_avd('Isolated', 35, 'pixel_6', screen=screen)
            self.assertTrue(p.describe('Isolated')['created'])
            config = p.avd_config('Isolated')
            self.assertEqual(config['hw.lcd.width'], '750')
            self.assertEqual(config['hw.lcd.height'], '1624')
            self.assertEqual(config['hw.lcd.density'], '320')
            self.assertEqual(config['skin.name'], '750x1624')
            history = (p.sdk / 'installs.log').read_text()
            p2 = self.preparer()
            p2.ensure_runtime()
            self.assertEqual(p2.ensure_avd('Isolated', 35, 'pixel_6', screen=screen), 'Isolated')
            self.assertFalse(p2.created)
            self.assertEqual(history, (p.sdk / 'installs.log').read_text())
        self.assertIn('sdkmanager', p.log_path.read_text())
