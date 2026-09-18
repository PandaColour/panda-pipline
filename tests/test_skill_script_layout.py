import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import Pipeline


ROOT = Path(__file__).resolve().parents[1]
TOOLS = {
    'panda-pipeline-ui-assets': 'figma_asset_audit.py',
    'panda-pipeline-static-analysis': 'static_scan.py',
    'panda-pipeline-android-device-validation': 'android_emulator.py',
}


class SkillScriptLayoutTests(unittest.TestCase):
    def test_sources_are_self_contained_and_run_outside_repository(self):
        with tempfile.TemporaryDirectory(prefix='独立工具 ') as cwd:
            env = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
            for skill, filename in TOOLS.items():
                with self.subTest(skill=skill):
                    script = ROOT / 'skills' / skill / 'scripts' / filename
                    self.assertTrue(script.is_file(), script)
                    self.assertFalse((ROOT / filename).exists())
                    self.assertFalse((script.parent.parent / 'bundle.json').exists())
                    result = subprocess.run([sys.executable, str(script), '--help'], cwd=cwd,
                                            env=env, capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_pipeline_static_scan_uses_skill_cli_and_propagates_failure(self):
        with tempfile.TemporaryDirectory(prefix='项目 空格 ') as work:
            pipeline = Pipeline(work)
            with patch('pipeline.subprocess.run') as run:
                pipeline._run_static_scan()
            command = run.call_args.args[0]
            self.assertEqual(command, [sys.executable,
                str(ROOT / 'skills/panda-pipeline-static-analysis/scripts/static_scan.py'),
                '--work-dir', pipeline.work_dir, '--report', pipeline.static_scan_report_file])
            self.assertTrue(run.call_args.kwargs['check'])
            with patch('pipeline.subprocess.run', side_effect=subprocess.CalledProcessError(2, command)):
                with self.assertRaises(subprocess.CalledProcessError):
                    pipeline._run_static_scan()

    def test_pipeline_static_scan_writes_report_through_real_cli(self):
        with tempfile.TemporaryDirectory(prefix='空项目 ') as work:
            pipeline = Pipeline(work)
            pipeline._run_static_scan()
            self.assertIn('未发现可静态扫描', Path(pipeline.static_scan_report_file).read_text())


if __name__ == '__main__':
    unittest.main()
