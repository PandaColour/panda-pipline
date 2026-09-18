import shlex
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents import Agent

ROOT = Path(__file__).resolve().parents[1]
ROLES = {'code_developer.md', 'code_reviewer.md', 'item_developer.md', 'item_code_reviewer.md'}


class EmulatorPromptTests(unittest.TestCase):
    def test_only_developer_and_code_review_trigger_device_skill(self):
        for directory in ('system-prompt', 'break-system-prompt'):
            for path in (ROOT / directory).glob('*.md'):
                with self.subTest(path=path):
                    agent = Agent('test', path.name, '/business/project', prompt_dir=str(path.parent))
                    if path.name in ROLES:
                        self.assertNotIn('__ANDROID_EMULATOR_COMMAND__', agent.system_prompt)
                        self.assertIn('panda-pipeline-android-device-validation', agent.system_prompt)
                        self.assertIn('记忆整理、总结和回执补正', agent.system_prompt)
                        device_rules = (ROOT / 'skills/panda-pipeline-android-device-validation/references/device.md').read_text()
                        self.assertIn('--serial', device_rules)
                        self.assertIn('--width', device_rules)
                        self.assertIn('未授权', device_rules)
                        self.assertIn('fallback_reason', device_rules)
                    else:
                        self.assertNotIn('panda-pipeline-android-device-validation', agent.system_prompt)
                        self.assertIn('不启动模拟器', agent.system_prompt)

    def test_rendered_command_uses_skill_relative_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'code_developer.md'
            path.write_text('__ANDROID_EMULATOR_COMMAND__')
            with patch('pipeline_skills.SOURCE_ROOT', Path('/tmp/a b/$(echo bad)')), \
                    patch('pipeline_skills.sys.executable', '/tmp/python with spaces'):
                agent = Agent('test', path.name, '/business/project', prompt_dir=directory)
            self.assertEqual(shlex.split(agent.system_prompt), [
                'python3', 'scripts/android_emulator.py'])


if __name__ == '__main__':
    unittest.main()
