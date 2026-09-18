"""Opt-in macOS integration check; uses a fake SDK and cleans its launchd job.

Run: python3 tests/android_emulator_launchd_smoke.py (outside a restricted sandbox).
Never connects to the real adb server or starts a business-project emulator.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
scripts = repo / 'skills/panda-pipeline-android-device-validation/scripts'
sys.path.insert(0, str(scripts))
# Load the same self-contained scripts used by the installed skill.
from android_emulator import EmulatorManager  # noqa: E402

with tempfile.TemporaryDirectory(prefix='panda-emulator-smoke-') as directory:
    root = Path(directory)
    sdk = root / 'sdk'
    state = root / 'state'
    marker = root / 'emulator.json'
    for folder in ('emulator', 'platform-tools'):
        (sdk / folder).mkdir(parents=True)
    emulator = sdk / 'emulator/emulator'
    emulator.write_text(f'''#!{sys.executable}
import json, os, pathlib, sys, time
if '-list-avds' in sys.argv:
    print('PipelineSmoke')
else:
    pathlib.Path({str(marker)!r}).write_text(json.dumps({{'pid':os.getpid(),'ppid':os.getppid(),'port':sys.argv[sys.argv.index('-port')+1]}}))
    print('independent emulator output', flush=True)
    time.sleep(30)
''')
    adb = sdk / 'platform-tools/adb'
    adb.write_text(f'''#!{sys.executable}
import json, pathlib, sys
p=pathlib.Path({str(marker)!r})
if sys.argv[1:] == ['devices']:
    print('List of devices attached')
    if p.exists(): print('emulator-' + json.loads(p.read_text())['port'] + '\\tdevice')
elif sys.argv[-3:] == ['emu','avd','name']: print('PipelineSmoke\\nOK')
elif sys.argv[-3:] == ['shell','getprop','sys.boot_completed']: print('1')
''')
    emulator.chmod(0o700)
    adb.chmod(0o700)
    caller = root / 'caller.py'
    caller.write_text(f'''import json, sys
from pathlib import Path
sys.path.insert(0,{str(scripts)!r})
from android_emulator import EmulatorManager
m=EmulatorManager(Path({str(sdk)!r}),Path({str(state)!r}),timeout=12)
print(json.dumps(m.ensure('PipelineSmoke')))
''')
    manager = EmulatorManager(sdk, state, timeout=15)
    try:
        started = time.monotonic()
        result = subprocess.run([sys.executable, str(caller)], capture_output=True, text=True, timeout=15, check=False)
        if result.returncode:
            raise RuntimeError(result.stderr + result.stdout)
        receipt = json.loads(result.stdout)
        assert receipt['status'] == 'ready' and receipt['managed'], receipt
        info = json.loads(marker.read_text())
        os.kill(info['pid'], 0)
        parent = subprocess.run(['/bin/ps','-p',str(info['ppid']),'-o','ppid=,command='], capture_output=True,text=True,check=True)
        assert info['ppid'] == 1 and '/sbin/launchd' in parent.stdout, parent.stdout
        processes = subprocess.run(['/bin/ps','-axo','pid=,ppid=,command='],capture_output=True,text=True,check=True).stdout
        caffeinates = [line.split()[0] for line in processes.splitlines() if '/usr/bin/caffeinate -i ' + str(emulator) in line]
        assert caffeinates, processes
        assertions = subprocess.run(['/usr/bin/pmset','-g','assertions'],capture_output=True,text=True,check=True).stdout
        assert any(f'pid {pid}(caffeinate)' in assertions for pid in caffeinates), assertions
        assert 'independent emulator output' in Path(receipt['log_path']).read_text()
        # The original caller exited, but its launchd-owned emulator still lives.
        reused = manager.ensure('PipelineSmoke')
        assert reused['source'] == 'reused' and reused['serial'] == receipt['serial']
        print(json.dumps({'result':'passed','caller_return_seconds':round(time.monotonic()-started,2),
            'launchd_parent_verified':True,'sleep_assertion_verified':True,
            'reuse_verified':True,'external_business_devices_touched':False}))
    finally:
        manager.deadline = time.monotonic() + 10
        print(json.dumps(manager.stop('PipelineSmoke')))
