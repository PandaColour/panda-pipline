import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents import _prompt_snapshot as snapshots
from agents.cursor import CursorAgent


class CursorPromptFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='中文 prompt ')
        self.addCleanup(self.tmp.cleanup)
        root = patch.object(snapshots, 'PROMPT_ROOT', Path(self.tmp.name))
        root.start()
        self.addCleanup(root.stop)
        base = patch('agents.cursor.build_cursor_base_cmd', side_effect=lambda: ['agent', '-p', '--force'])
        base.start()
        self.addCleanup(base.stop)
        self.process = MagicMock()
        self.process.returncode = 0
        self.process.poll.return_value = 0
        self.process.stdout.readline.return_value = ''

    def test_fresh_and_resume_pass_path_instead_of_full_rules(self):
        rules = 'ROLE_BODY 中文\n' * 20000
        message = 'TASK_BODY\n原样保留 "引号" & %value%'
        fixed = snapshots.freeze_system_prompt(rules)
        for session in (None, 'saved-session'):
            with self.subTest(session=session), patch('agents.cursor.subprocess.Popen', return_value=self.process) as spawn:
                result = CursorAgent()._run_once('/business/project', message, fixed, session, ['/dependency'])
                self.assertEqual(result.returncode, 0, result.error)
                cmd = spawn.call_args.args[0]
                prompt = cmd[-1]
                self.assertFalse('ROLE_BODY' in prompt, '命令不应携带角色全文')
                self.assertIn(str(fixed.path), prompt)
                self.assertIn(message, prompt)
                self.assertLess(len(subprocess.list2cmdline(cmd).encode('utf-16-le')) // 2, 8191)
                self.assertEqual(spawn.call_args.kwargs['stdin'], subprocess.DEVNULL)
                self.assertEqual(spawn.call_args.kwargs['cwd'], '/business/project')
                if session:
                    self.assertIn('需要时重新读取', prompt)
                    self.assertIn('--resume', cmd)
                    self.assertNotIn('/dependency', prompt)
                else:
                    self.assertIn('先完整读取', prompt)
                    self.assertIn('读取失败', prompt)
                    self.assertIn('/dependency', prompt)
                self.assertEqual(fixed.path.read_text(), rules)
        self.assertEqual(len(list(Path(self.tmp.name).rglob('*.md'))), 1)

    def test_missing_fixed_file_fails_before_starting_cursor(self):
        fixed = snapshots.freeze_system_prompt('rules')
        fixed.path.unlink()
        with patch('agents.cursor.subprocess.Popen') as spawn:
            result = CursorAgent()._run_once('/business', 'task', fixed, None, None)
        self.assertFalse(spawn.called, '不应启动 Cursor')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(fixed.path), result.error)

    def test_oversized_windows_task_fails_without_truncation_or_process(self):
        fixed = snapshots.freeze_system_prompt('rules')
        with patch('agents._prompt_snapshot.sys.platform', 'win32'), patch('agents.cursor.subprocess.Popen') as spawn:
            result = CursorAgent()._run_once('/business', '任务' * 40000, fixed, None, None)
        self.assertFalse(spawn.called, '不应启动 Cursor')
        self.assertIn('No text was truncated', result.error)

    def test_invalid_session_retry_requires_full_read_again(self):
        fixed = snapshots.freeze_system_prompt('ROLE_BODY')
        failed = MagicMock()
        failed.returncode = 1
        failed.poll.return_value = 1
        failed.stdout.readline.side_effect = [json.dumps({'type': 'result', 'result': 'invalid session'}) + '\n', '']
        agent = CursorAgent()
        agent.max_retries = 1
        with patch('agents.cursor.subprocess.Popen', side_effect=[failed, self.process]) as spawn, patch('agents.cursor.time.sleep'):
            result = agent.run('/business', 'task', fixed, 'expired')
        self.assertEqual(result.returncode, 0)
        fresh = spawn.call_args_list[1].args[0]
        self.assertNotIn('--resume', fresh)
        self.assertIn('先完整读取', fresh[-1])
        self.assertIn(str(fixed.path), fresh[-1])
        self.assertNotIn('ROLE_BODY', fresh[-1])
