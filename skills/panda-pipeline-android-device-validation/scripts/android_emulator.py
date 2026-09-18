#!/usr/bin/env python3
"""Select an Android device, or start an emulator via macOS launchd.

Only the ensure caller waits (with a deadline). launchd owns caffeinate and the
emulator, including their log streams. Missing SDK packages and AVDs are prepared
automatically before starting the emulator.
"""

import argparse
import errno
import hashlib
import json
import os
import platform
import plistlib
import shutil
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from android_screen import screen_report, screen_target
from android_sdk import PreparationError, SdkProvisioner


class EmulatorError(RuntimeError):
    pass


def resolve_sdk(explicit=None, allow_missing=False):
    candidates = [explicit, os.environ.get('ANDROID_HOME'), os.environ.get('ANDROID_SDK_ROOT')]
    adb = shutil.which('adb')
    if adb:
        candidates.append(str(Path(adb).resolve().parent.parent))
    candidates.append(str(Path.home() / 'Library/Android/sdk'))
    for value in candidates:
        if not value:
            continue
        root = Path(value).expanduser().resolve()
        if allow_missing and (explicit or value in (os.environ.get('ANDROID_HOME'), os.environ.get('ANDROID_SDK_ROOT'))):
            return root
        if all(os.access(root / tool, os.X_OK) for tool in ('platform-tools/adb', 'emulator/emulator')):
            return root
        if allow_missing and os.access(root / 'platform-tools/adb', os.X_OK):
            return root
        if explicit:
            break
    if allow_missing:
        return (Path.home() / 'Library/Android/sdk').resolve()
    raise EmulatorError('未找到含 adb 和 emulator 的 SDK；用 --sdk 指定 SDK。')


@contextmanager
def device_lock(directory, timeout):
    # Import after host detection so unsupported hosts can emit a useful error.
    import fcntl

    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    deadline = time.monotonic() + timeout
    with (directory / 'device.lock').open('a') as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise EmulatorError('等待模拟器启动锁超时；另一个调用正在准备设备。')
                time.sleep(min(0.2, remaining))
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def free_port():
    for port in range(5554, 5683, 2):
        with socket.socket() as console, socket.socket() as adb:
            try:
                console.bind(('127.0.0.1', port))
                adb.bind(('127.0.0.1', port + 1))
                return port
            except OSError as error:
                if error.errno != errno.EADDRINUSE:
                    raise EmulatorError(f'无法检测本机模拟器端口：{error}') from error
    raise EmulatorError('没有可用的模拟器端口（5554–5682）。')


class EmulatorManager:
    def __init__(self, sdk, state_dir, timeout=180):
        self.sdk = Path(sdk)
        self.state_dir = Path(state_dir)
        self.adb = self.sdk / 'platform-tools/adb'
        self.emulator = self.sdk / 'emulator/emulator'
        self.domain = f'gui/{os.getuid()}'
        self.deadline = time.monotonic() + timeout
        self.log_path = None
        self.label = None
        self.timeout = timeout
        self.preparation = None
        self.stage = 'initialization'
        self.avd = None
        self.selection = {}

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise EmulatorError('等待模拟器就绪超时；保留正在启动的实例，下次调用继续检测，不重复启动。')
        return remaining

    def run(self, args, check=True):
        try:
            result = subprocess.run(
                [str(arg) for arg in args], stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=min(10, self.remaining()), check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise EmulatorError(f'命令超时：{args[0]}') from error
        except OSError as error:
            raise EmulatorError(f'命令启动失败：{args[0]}：{error}') from error
        if check and result.returncode:
            detail = (result.stderr or result.stdout).strip()[-1200:]
            raise EmulatorError(f'命令失败（{result.returncode}）：{args[0]}：{detail}')
        return result

    def devices(self, selected_serial=None):
        rows = []
        for line in self.run([self.adb, 'devices']).stdout.splitlines():
            parts = line.split()
            if len(parts) < 2 or line.startswith(('List of devices', '*')):
                continue
            serial, state = parts[:2]
            if selected_serial and selected_serial != serial:
                continue
            if state != 'device':
                rows.append((serial, state, None))
                continue
            name = None
            if serial.startswith('emulator-'):
                lines = self.run([self.adb, '-s', serial, 'emu', 'avd', 'name']).stdout.splitlines()
                name = next((line.strip() for line in lines if line.strip() and line.strip() != 'OK'), None)
            rows.append((serial, state, name))
        return rows

    def select_device(self, rows, avd, selected_serial=None):
        if selected_serial:
            match = next((state for serial, state, _ in rows if serial == selected_serial), None)
            if match != 'device':
                raise EmulatorError(f'指定设备 {selected_serial} 不可用：{match or "未连接"}；不切换其他设备。')
            return selected_serial
        matches = [serial for serial, state, name in rows if state == 'device' and (not avd or name == avd)]
        if not avd:
            phones = [serial for serial in matches if not serial.startswith('emulator-')]
            if phones:
                matches = phones
        if len(matches) > 1:
            raise EmulatorError(f'存在多个可用设备 {matches}；用 --serial 或 --avd 明确选择。')
        return matches[0] if matches else None

    def configure_job(self, avd):
        identity = '\n'.join([str(self.sdk), os.environ.get('ANDROID_AVD_HOME', ''),
                              os.environ.get('ANDROID_USER_HOME', ''), avd])
        key = hashlib.sha256(identity.encode()).hexdigest()[:16]
        self.label = f'com.pandapipeline.android-emulator.{key}'
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.log_path = self.state_dir / f'{key}.log'
        return self.state_dir / f'{key}.plist'

    def job_status(self):
        result = self.run(['/bin/launchctl', 'print', f'{self.domain}/{self.label}'], check=False)
        return result.stdout if result.returncode == 0 else ''

    def start(self, avd, plist_path):
        environment = {'HOME': str(Path.home()), 'ANDROID_HOME': str(self.sdk),
                       'ANDROID_SDK_ROOT': str(self.sdk), 'PATH': '/usr/bin:/bin:/usr/sbin:/sbin'}
        for key in ('ANDROID_AVD_HOME', 'ANDROID_USER_HOME', 'ANDROID_EMULATOR_HOME'):
            if os.environ.get(key):
                environment[key] = str(Path(os.environ[key]).expanduser().resolve())
        config = {
            'Label': self.label,
            'ProgramArguments': ['/usr/bin/caffeinate', '-i', str(self.emulator), '-avd', avd,
                                 '-port', str(free_port()), '-no-snapshot-load', '-no-boot-anim'],
            'EnvironmentVariables': environment,
            'WorkingDirectory': str(self.state_dir),
            'StandardInPath': '/dev/null',
            'StandardOutPath': str(self.log_path),
            'StandardErrorPath': str(self.log_path),
            'RunAtLoad': True,
            # No KeepAlive loop: a failed emulator is retried by the next ensure.
            'KeepAlive': False,
        }
        self.log_path.touch(mode=0o600, exist_ok=True)
        plist_path.write_bytes(plistlib.dumps(config))
        plist_path.chmod(0o600)
        self.run(['/bin/launchctl', 'bootstrap', self.domain, plist_path])

    def device_receipt(self, serial, avd, source, target, managed=False):
        adb_args = [self.adb, '-s', serial]
        def read(*args):
            result = self.run([*adb_args, 'shell', *args], check=False)
            return result.stdout if result.returncode == 0 else ''
        api_text = read('getprop', 'ro.build.version.sdk').strip()
        metadata = self.preparation.describe(avd) if avd else {}
        return {**metadata,
                'status': 'ready', 'serial': serial, 'avd': avd, 'source': source,
                'stage': 'ready', 'sdk': str(self.sdk), 'api': int(api_text) if api_text.isdigit() else None,
                'device_type': 'emulator' if serial.startswith('emulator-') else 'physical',
                'device_profile': metadata.get('device_profile'),
                'created': self.preparation.created,
                'adb_path': str(self.adb), 'adb_args': [str(arg) for arg in adb_args],
                'screen': screen_report(read('wm', 'size'), read('wm', 'density'),
                                        read('settings', 'get', 'system', 'font_scale'), target),
                'selection': self.selection,
                'managed': managed, 'sleep_protection': 'caffeinate' if managed else 'external',
                'log_path': str(self.log_path) if managed else None}

    def ensure(self, avd=None, api=None, device=None, prepare_timeout=1800,
               serial=None, width=None, height=None, density=None):
        target = screen_target(width, height, density)
        if serial and avd:
            raise ValueError('--serial 与 --avd 不可同时指定')
        self.stage = 'preparation'
        self.preparation = SdkProvisioner(self.sdk, self.state_dir, prepare_timeout)
        self.preparation.ensure_runtime(adb_only=True)
        self.stage = 'device_selection'
        # Preparation and boot have separate deadlines: downloading does not consume boot time.
        self.deadline = time.monotonic() + self.timeout
        self.selection = {'requested_serial': serial, 'fallback_reason': None}
        rows = self.devices(serial)
        if serial and not serial.startswith('emulator-'):
            state = next((state for sid, state, _ in rows if sid == serial), 'disconnected')
            if state != 'device':
                self.selection['fallback_reason'] = f'{serial}: {state}；不等待真机，切换可用设备或模拟器'
                serial = None
                rows = self.devices()
        unavailable_phones = [(sid, state) for sid, state, _ in rows
                              if not sid.startswith('emulator-') and state != 'device']
        if unavailable_phones and not self.selection['fallback_reason']:
            self.selection['fallback_reason'] = f'真机不可用 {unavailable_phones}；不等待真机'
        serial = self.select_device(rows, avd, serial)
        if serial and not avd:
            avd = next(name for device, _, name in rows if device == serial)
        if serial:
            if api is not None:
                actual = self.run([self.adb, '-s', serial, 'shell', 'getprop', 'ro.build.version.sdk']).stdout.strip()
                if actual != str(api):
                    raise EmulatorError(f'设备 {serial} API={actual or "未知"} 与要求 {api} 不匹配；不自动切换。')
            if device and avd and not self.preparation.matches(avd, device=device):
                raise EmulatorError(f'AVD {avd} 与设备 profile {device} 不匹配；不自动切换。')
            if not serial.startswith('emulator-'):
                return self.device_receipt(serial, None, 'reused', target)
        if not serial:
            unknown = [(device, state) for device, state, _ in rows
                       if state != 'device' and device.startswith('emulator-')]
            if unknown:
                raise EmulatorError(f'已有设备状态不可确认 {unknown}；本次不重复启动，不关闭外部实例。')
            self.preparation.ensure_runtime()
            avds = [line.strip() for line in self.run([self.emulator, '-list-avds']).stdout.splitlines() if line.strip()]
            if api is not None or device is not None:
                if avd and self.preparation.avd_config(avd) and not self.preparation.matches(avd, api, device):
                    raise EmulatorError(f'AVD {avd} 与指定 API/设备要求不匹配；不覆盖已有配置。')
                avds = [name for name in avds if self.preparation.matches(name, api, device)]
            if not avd:
                if len(avds) > 1:
                    raise EmulatorError(f'请用 --avd 选择适用 AVD；当前可用：{avds}。')
                avd = avds[0] if avds else None
            if avd not in avds or (self.state_dir / f'creating-{avd}.json').exists():
                self.stage = 'preparation'
                avd = self.preparation.ensure_avd(avd, api, device, **({'screen': target} if target else {}))
            if target:
                config = self.preparation.avd_config(avd)
                expected = {'hw.lcd.width': width, 'hw.lcd.height': height, 'hw.lcd.density': density}
                diff = {key: {'actual': config.get(key), 'expected': value}
                        for key, value in expected.items() if config.get(key) != str(value)}
                if diff:
                    raise EmulatorError(f'AVD {avd} 屏幕不匹配：{diff}；未启动或覆盖，请明确选择其他基线或新 AVD 名称。')
        if not avd:
            raise EmulatorError('无法识别现有模拟器的 AVD 名称，不创建替代实例。')
        self.avd = avd
        if not serial:
            self.stage = 'preparation'
            self.preparation.ensure_avd_image(avd)
        self.stage = 'boot'
        self.deadline = time.monotonic() + self.timeout
        plist_path = self.configure_job(avd)
        source = 'reused'
        status = self.job_status()
        if not serial and 'state = running' not in status:
            if status:
                self.run(['/bin/launchctl', 'bootout', f'{self.domain}/{self.label}'])
            self.start(avd, plist_path)
            source = 'started'
        while True:
            self.remaining()
            serial = self.select_device(self.devices(), avd)
            if serial:
                boot = self.run([self.adb, '-s', serial, 'shell', 'getprop', 'sys.boot_completed']).stdout.strip()
                if boot == '1':
                    managed = False
                    if plist_path.exists() and 'state = running' in self.job_status():
                        args = plistlib.loads(plist_path.read_bytes())['ProgramArguments']
                        managed = serial == f'emulator-{args[args.index("-port") + 1]}'
                    return self.device_receipt(serial, avd, source, target, managed)
            elif source == 'started' and 'state = exited' in self.job_status():
                raise EmulatorError('模拟器启动后退出；查看独立日志，下次 ensure 可重新启动。')
            time.sleep(min(1, self.remaining()))

    def stop(self, avd):
        self.configure_job(avd)
        if self.job_status():
            self.run(['/bin/launchctl', 'bootout', f'{self.domain}/{self.label}'])
        return {'status': 'stopped', 'avd': avd, 'label': self.label,
                'scope': '仅本脚本管理的服务；外部模拟器不受影响'}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='屏幕单位：px = dp × dpi / 160。\n'
               '例如目标逻辑尺寸 375×812 dp，选择 320 dpi：\n'
               '  python3 scripts/android_emulator.py ensure --width 750 --height 1624 --density 320\n'
               '误传 --width 375 --height 812 --density 320 请求的是 187.5×406 dp。\n'
               '参考图导出 1×/2× 仅影响图片像素，不决定设备 px/dpi；长滚动图不等于设备屏高。\n'
               '已连接设备只报告规格差异，不修改；matches_target 不代表 UI 还原结论。')
    parser.add_argument('action', choices=('ensure', 'stop'))
    parser.add_argument('--avd', help='AVD 名称；不存在则创建，stop 必填，多候选时需明确选择')
    parser.add_argument('--serial', help='选择 ADB 设备 ID；真机离线/未授权/拔出时立即降级到其他可用设备或模拟器')
    parser.add_argument('--width', type=int, help='目标设备像素宽 px（不是 dp 或参考图宽）；与 height/density 一起传入，新 AVD 使用此值')
    parser.add_argument('--height', type=int, help='目标设备像素高 px（不是 dp 或长滚动图高）')
    parser.add_argument('--density', type=int, help='目标设备屏幕密度 dpi（不是图片导出倍率）；已连接设备只报告差异，不修改')
    parser.add_argument('--api', type=int, help='项目要求的 Android API；新建时未指定默认 35')
    parser.add_argument('--device', help='设备 profile ID；新建时未指定默认 pixel_6')
    parser.add_argument('--prepare-timeout', type=int, default=1800, help='准备/下载期限，1–7200 秒，默认 1800')
    parser.add_argument('--sdk', help='Android SDK 绝对路径；默认从环境/PATH/标准位置发现')
    parser.add_argument('--timeout', type=int, default=180, help='启动就绪期限，1–600 秒（默认 180），不含准备下载')
    args = parser.parse_args(argv)
    manager = None
    try:
        if platform.system() != 'Darwin':
            raise EmulatorError(f'首版只支持 macOS launchd；当前宿主 {platform.system()}，未启动任何设备。')
        if not 1 <= args.timeout <= 600:
            raise EmulatorError('--timeout 必须为 1–600 秒')
        if not 1 <= args.prepare_timeout <= 7200:
            raise EmulatorError('--prepare-timeout 必须为 1–7200 秒')
        if args.api is not None and not 1 <= args.api <= 999:
            raise EmulatorError('--api 必须为正整数 API level')
        if args.action == 'stop' and not args.avd:
            raise EmulatorError('stop 必须指定 --avd，只停止脚本管理的该实例。')
        screen_target(args.width, args.height, args.density)
        if args.serial and args.avd:
            raise EmulatorError('--serial 与 --avd 不可同时指定')
        if args.action == 'stop' and (args.serial or args.width is not None or args.api is not None or args.device):
            raise EmulatorError('stop 仅接受 --avd 选择脚本管理的模拟器')
        sdk = resolve_sdk(args.sdk, allow_missing=args.action == 'ensure')
        state = Path.home() / 'Library/Application Support/panda-pipeline/android-emulator'
        manager = EmulatorManager(sdk, state, args.timeout)
        with device_lock(state, args.prepare_timeout if args.action == 'ensure' else manager.remaining()):
            result = manager.ensure(args.avd, args.api, args.device, args.prepare_timeout,
                                    serial=args.serial, width=args.width, height=args.height,
                                    density=args.density) if args.action == 'ensure' else manager.stop(args.avd)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (EmulatorError, PreparationError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        preparation = manager.preparation if manager else None
        print(json.dumps({'status': 'error', 'error': str(error),
                          'stage': preparation.stage if preparation and manager.stage == 'preparation' else manager.stage if manager else 'initialization',
                          'avd': (manager.avd if manager else None) or (preparation.avd if preparation else None) or args.avd,
                          'serial': None, 'sdk': str(manager.sdk) if manager else args.sdk,
                          'selection': manager.selection if manager else {'requested_serial': args.serial},
                          'preparation_log_path': str(preparation.log_path) if preparation and preparation.log_path.exists() else None,
                          'log_path': str(manager.log_path) if manager and manager.log_path else None},
                         ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
