"""Bounded, repeatable macOS SDK and AVD preparation for android_emulator."""

import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

# Pinned official macOS command-line tools 19.0; checksum from repository2-1.xml.
TOOLS_URL = 'https://dl.google.com/android/repository/commandlinetools-mac-13114758_latest.zip'
TOOLS_SHA1 = 'c3e06a1959762e89167d1cbaa988605f6f7c1d24'
TOOLS_VERSION = '19.0'


class PreparationError(RuntimeError):
    pass


def properties(path):
    if not path.is_file():
        return {}
    return dict(line.split('=', 1) for line in path.read_text().splitlines()
                if '=' in line and not line.lstrip().startswith('#'))


class SdkProvisioner:
    def __init__(self, sdk, state_dir, timeout=1800):
        self.sdk = Path(sdk)
        self.state_dir = Path(state_dir)
        self.deadline = time.monotonic() + timeout
        self.log_path = self.state_dir / 'preparation.log'
        self.stage = 'prepare_runtime'
        self.created = False
        self.avd = None
        self.env = os.environ.copy()
        self.env.update(ANDROID_HOME=str(self.sdk), ANDROID_SDK_ROOT=str(self.sdk))

    def remaining(self):
        value = self.deadline - time.monotonic()
        if value <= 0:
            raise PreparationError(f'{self.stage} 超时；保留已安装资源，下次 ensure 继续检查。')
        return value

    def log(self, text):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.log_path.open('a', encoding='utf-8') as stream:
            stream.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} [{self.stage}] {text}\n')

    def run(self, args, input_text=None, limit=600):
        self.log(' '.join(map(str, args)))
        timeout = min(limit, self.remaining())
        offset = self.log_path.stat().st_size
        with self.log_path.open('a', encoding='utf-8') as output:
            process = subprocess.Popen(list(map(str, args)), stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                                       stdout=output, stderr=output, text=True, env=self.env, start_new_session=True)
            try:
                process.communicate(input=input_text, timeout=timeout)
            except BaseException as error:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate()
                if isinstance(error, subprocess.TimeoutExpired):
                    raise PreparationError(f'{self.stage} 命令超时；见 {self.log_path}，下次 ensure 继续。') from error
                raise
        with self.log_path.open('rb') as stream:
            stream.seek(max(offset, self.log_path.stat().st_size - 4000))
            detail = stream.read().decode('utf-8', errors='replace')
        if process.returncode:
            raise PreparationError(f'{self.stage} 命令失败（{process.returncode}），见 {self.log_path}：{detail[-1200:]}')
        return subprocess.CompletedProcess(args, process.returncode, detail, '')

    def download(self, url, destination):
        self.log(f'download {url}')
        with urllib.request.urlopen(url, timeout=min(30, self.remaining())) as response, destination.open('wb') as output:
            while True:
                self.remaining()
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                output.write(chunk)

    def bootstrap_tools(self):
        self.stage = 'download_command_tools'
        target = self.sdk / 'cmdline-tools' / TOOLS_VERSION
        if all(os.access(target / 'bin' / name, os.X_OK) for name in ('sdkmanager', 'avdmanager')):
            return target / 'bin'
        if target.exists():
            raise PreparationError(f'命令行工具目录不完整，不覆盖已有目录：{target}')
        target.parent.mkdir(parents=True, exist_ok=True)
        # Only publish a complete verified extraction; failed downloads cannot be reused as tools.
        with tempfile.TemporaryDirectory(prefix='.panda-tools-', dir=target.parent) as directory:
            directory = Path(directory)
            archive = directory / 'tools.zip'
            self.download(TOOLS_URL, archive)
            checksum = hashlib.sha1()
            with archive.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    self.remaining()
                    checksum.update(chunk)
            if checksum.hexdigest() != TOOLS_SHA1:
                raise PreparationError('命令行工具下载校验失败；未安装，下次重新下载。')
            if not zipfile.is_zipfile(archive):
                raise PreparationError('命令行工具下载不是有效 ZIP；未安装。')
            unpacked = directory / 'unpacked'
            with zipfile.ZipFile(archive) as bundle:
                for member in bundle.infolist():
                    self.remaining()
                    path = Path(member.filename)
                    if path.is_absolute() or '..' in path.parts or (member.external_attr >> 16) & 0o170000 == 0o120000:
                        raise PreparationError('命令行工具压缩包包含非法路径或链接')
                    bundle.extract(member, unpacked)
                tools = unpacked / 'cmdline-tools'
                for name in ('sdkmanager', 'avdmanager'):
                    if not (tools / 'bin' / name).is_file():
                        raise PreparationError('命令行工具压缩包不完整')
                for path in (tools / 'bin').iterdir():
                    if path.is_file():
                        path.chmod(0o755)
            tools.rename(target)
        return target / 'bin'

    def ensure_command_tools(self):
        candidates = [self.sdk / 'cmdline-tools/latest/bin', self.sdk / f'cmdline-tools/{TOOLS_VERSION}/bin']
        candidates.extend(sorted((self.sdk / 'cmdline-tools').glob('*/bin'), reverse=True))
        tools = next((path for path in candidates if all(os.access(path / name, os.X_OK)
                     for name in ('sdkmanager', 'avdmanager'))), None)
        # Prefer configured Java or Android Studio's bundled JBR; leave license interaction to the user.
        java_homes = [self.env.get('JAVA_HOME'), '/Applications/Android Studio.app/Contents/jbr/Contents/Home']
        java_homes.extend(str(path) for path in (Path.home() / 'Applications').glob('Android Studio*.app/Contents/jbr/Contents/Home'))
        for home in java_homes:
            if home and os.access(Path(home) / 'bin/java', os.X_OK):
                self.env['JAVA_HOME'] = home
                break
        try:
            java = str(Path(self.env['JAVA_HOME']) / 'bin/java') if self.env.get('JAVA_HOME') else shutil.which('java')
            if not java:
                raise PreparationError('缺少 Java；请安装 JDK 17+ 或配置 Android Studio 的 JBR/JAVA_HOME。')
            self.run([java, '-version'], limit=10)
        except (PreparationError, OSError) as error:
            raise PreparationError('Java 不可用；请配置可用 JDK 17+ 的 JAVA_HOME。') from error
        return tools or self.bootstrap_tools()

    def package_ready(self, package):
        if package == 'platform-tools':
            return os.access(self.sdk / 'platform-tools/adb', os.X_OK)
        if package == 'emulator':
            return os.access(self.sdk / 'emulator/emulator', os.X_OK)
        folder = self.sdk.joinpath(*package.split(';'))
        image = folder / 'system.img'
        return image.is_file() and image.stat().st_size > 0 and (folder / 'package.xml').is_file()

    def install(self, packages):
        missing = [package for package in packages if not self.package_ready(package)]
        if not missing:
            return
        tools = self.ensure_command_tools()
        self.stage = 'install_packages'
        result = self.run([tools / 'sdkmanager', f'--sdk_root={self.sdk}', '--install', *missing], limit=1200)
        detail = result.stdout.lower()
        if 'license' in detail and ('not accepted' in detail or 'accept?' in detail):
            raise PreparationError(f'SDK 许可尚未接受；请用户运行 {tools / "sdkmanager"} --sdk_root="{self.sdk}" --licenses 后重试。')
        incomplete = [package for package in missing if not self.package_ready(package)]
        if incomplete:
            raise PreparationError(f'安装后资源仍不完整：{incomplete}；查看 {self.log_path}（包括许可或下载错误）。')

    def ensure_runtime(self, adb_only=False):
        packages = ('platform-tools',) if adb_only else ('platform-tools', 'emulator')
        self.install([package for package in packages if not self.package_ready(package)])

    @property
    def avd_home(self):
        if os.environ.get('ANDROID_AVD_HOME'):
            return Path(os.environ['ANDROID_AVD_HOME']).expanduser().resolve()
        user = Path(os.environ.get('ANDROID_USER_HOME', str(Path.home() / '.android'))).expanduser()
        return user / 'avd'

    def avd_config(self, name):
        index = properties(self.avd_home / f'{name}.ini')
        path = Path(index['path']).expanduser() if index.get('path') else self.avd_home / f'{name}.avd'
        return properties(path / 'config.ini')

    def matches(self, name, api=None, device=None):
        config = self.avd_config(name)
        image = config.get('image.sysdir.1', '').replace('\\', '/')
        return (api is None or f'/android-{api}/' in '/' + image) and (device is None or config.get('hw.device.name') == device)

    def ensure_avd_image(self, name):
        self.stage = 'prepare_image'
        image = self.avd_config(name).get('image.sysdir.1', '').replace('\\', '/')
        if not image:
            return  # External AVD metadata may not be readable; boot remains authoritative.
        location = Path(image)
        if location.is_absolute():
            try:
                image = location.relative_to(self.sdk).as_posix()
            except ValueError:
                if (location / 'system.img').is_file():
                    return
                raise PreparationError(f'AVD {name} 的外部镜像路径不可用，不改写已有配置：{location}')
        match = re.fullmatch(r'system-images/(android-\d+(?:\.\d+)?)/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/?', image)
        if not match:
            raise PreparationError(f'AVD {name} 的镜像路径无法映射到 SDK 包：{image}')
        self.install(['system-images;' + ';'.join(match.groups())])

    def configure_created_screen(self, owned, screen):
        if not screen:
            return
        path = owned / 'config.ini'
        values = {'hw.lcd.width': screen['width_px'], 'hw.lcd.height': screen['height_px'],
                  'hw.lcd.density': screen['density_dpi'], 'skin.dynamic': 'yes',
                  'skin.name': f'{screen["width_px"]}x{screen["height_px"]}',
                  'skin.path': '_no_skin', 'showDeviceFrame': 'no'}
        lines = []
        for line in path.read_text().splitlines():
            key = line.partition('=')[0].strip()
            lines.append(f'{key}={values.pop(key)}' if key in values else line)
        lines.extend(f'{key}={value}' for key, value in values.items())
        temporary = path.with_suffix('.ini.tmp')
        temporary.write_text('\n'.join(lines) + '\n')
        temporary.replace(path)

    def ensure_avd(self, name=None, api=None, device=None, screen=None):
        if screen:
            from android_screen import screen_target
            screen_target(screen['width_px'], screen['height_px'], screen['density_dpi'])
        self.stage = 'create_avd'
        machine = platform.machine().lower()
        if machine not in ('arm64', 'aarch64', 'x86_64', 'amd64'):
            raise PreparationError(f'不支持的宿主架构：{machine}')
        abi = 'arm64-v8a' if machine in ('arm64', 'aarch64') else 'x86_64'
        # Fallback is explicit in CLI help/receipt; project requirements should supply --api/--device.
        api, device = api or 35, device or 'pixel_6'
        suffix = f'_{screen["width_px"]}x{screen["height_px"]}_{screen["density_dpi"]}dpi' if screen else ''
        name = name or f'Panda_API{api}_{abi}_{device}{suffix}'
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or not re.fullmatch(r'[A-Za-z0-9_.-]+', device):
            raise PreparationError('AVD 名称和设备 ID 仅支持字母、数字、下划线、点和连字符。')
        self.avd = name
        owned = self.state_dir / 'avds' / f'{name}.avd'
        pending = self.state_dir / f'creating-{name}.json'
        index = self.avd_home / f'{name}.ini'
        # A killed creator may leave partial output. Only recover our own marked path.
        if pending.exists():
            record = json.loads(pending.read_text())
            saved = properties(index).get('path')
            if record != {'name': name, 'path': str(owned)} or (saved and Path(saved) != owned):
                raise PreparationError(f'AVD {name} 创建记录与现有配置冲突；不覆盖。')
            if self.matches(name, api, device):
                self.configure_created_screen(owned, screen)
                pending.unlink()
            else:
                config = self.avd_config(name)
                if config.get('image.sysdir.1') and config.get('hw.device.name'):
                    raise PreparationError(f'AVD {name} 已创建但规格不匹配，不覆盖；请指定其他名称。')
                if owned.is_symlink():
                    raise PreparationError(f'AVD {name} 的准备目录被替换为链接；不覆盖。')
                if owned.exists():
                    shutil.rmtree(owned)
                if index.exists():
                    index.unlink()
                pending.unlink()
        if (self.avd_home / f'{name}.ini').exists() or (self.avd_home / f'{name}.avd').exists():
            if not self.matches(name, api, device):
                raise PreparationError(f'AVD {name} 与 API/设备要求不匹配或创建不完整，不覆盖；请指定其他 --avd 名称。')
            if screen:
                config = self.avd_config(name)
                expected = {'hw.lcd.width': screen['width_px'], 'hw.lcd.height': screen['height_px'],
                            'hw.lcd.density': screen['density_dpi']}
                if any(config.get(key) != str(value) for key, value in expected.items()):
                    raise PreparationError(f'AVD {name} 屏幕与要求不匹配；不覆盖已有配置。')
            return name
        package = f'system-images;android-{api};google_apis;{abi}'
        self.install([package])
        tools = self.ensure_command_tools()
        self.stage = 'create_avd'
        self.avd_home.mkdir(parents=True, exist_ok=True)
        owned.parent.mkdir(parents=True, exist_ok=True)
        if owned.exists():
            raise PreparationError(f'AVD 准备目录已存在且无创建记录，不覆盖：{owned}')
        pending.write_text(json.dumps({'name': name, 'path': str(owned)}))
        self.run([tools / 'avdmanager', 'create', 'avd', '--name', name, '--package', package,
                  '--device', device, '--path', owned], input_text='no\n', limit=120)
        if not self.matches(name, api, device):
            raise PreparationError(f'AVD {name} 创建结果不完整；见 {self.log_path}')
        self.configure_created_screen(owned, screen)
        self.created = True
        pending.unlink()
        return name

    def describe(self, name):
        config = self.avd_config(name)
        image = config.get('image.sysdir.1', '').replace('\\', '/')
        match = re.search(r'android-(\d+)', image)
        return {'api': int(match[1]) if match else None, 'device_profile': config.get('hw.device.name'),
                'abi': config.get('abi.type'), 'created': self.created,
                'preparation_log_path': str(self.log_path) if self.log_path.exists() else None}
