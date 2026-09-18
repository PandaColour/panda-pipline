"""Load skill-owned scripts for unit tests without production import wrappers."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'skills'


def load(skill, name):
    path = ROOT / skill / 'scripts' / f'{name}.py'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


android_screen = load('panda-pipeline-android-device-validation', 'android_screen')
android_sdk = load('panda-pipeline-android-device-validation', 'android_sdk')
android_emulator = load('panda-pipeline-android-device-validation', 'android_emulator')
figma_asset_audit = load('panda-pipeline-ui-assets', 'figma_asset_audit')
static_scan = load('panda-pipeline-static-analysis', 'static_scan')
