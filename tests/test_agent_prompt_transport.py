import importlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents import _prompt_snapshot as snapshots


class AgentPromptTransportTests(unittest.TestCase):
    def test_three_backends_reuse_fixed_rules_and_keep_tasks_off_disk(self):
        for backend, cls in (('codex', 'CodexAgent'), ('claude', 'ClaudeAgent'), ('opencode', 'OpencodeAgent')):
            for session in (None, 'saved-session'):
                with self.subTest(backend=backend, session=session), tempfile.TemporaryDirectory(prefix='中文 prompt ') as tmp:
                    module = importlib.import_module('agents.' + backend)
                    system = 'RENDERED_ROLE /absolute/emulator.py\n' * 3000
                    message = 'TASK_BODY 中文 "quote" & %value%\n' * 4000
                    captured = {}
                    process = MagicMock()
                    process.returncode = 0
                    process.poll.return_value = 0
                    process.stdout.readline.return_value = ''

                    def spawn(cmd, **kwargs):
                        captured['cmd'] = cmd
                        self.assertLess(len(subprocess.list2cmdline(cmd).encode('utf-16-le')) // 2, 8191)
                        self.assertNotIn('RENDERED_ROLE', ' '.join(cmd))
                        self.assertNotIn('TASK_BODY', ' '.join(cmd))
                        files = list(Path(tmp).rglob('*.md'))
                        self.assertEqual(len(files), 1)
                        role_file = files[0].resolve()
                        self.assertEqual(role_file.read_text(), system)
                        if backend == 'claude':
                            self.assertEqual(Path(cmd[cmd.index('--append-system-prompt-file') + 1]), role_file)
                            self.assertNotIn('--append-system-prompt', cmd)
                        self.assertEqual(kwargs['stdin'], subprocess.PIPE)
                        self.assertEqual(kwargs['cwd'], '/business')
                        return process

                    with patch.object(snapshots, 'PROMPT_ROOT', Path(tmp)), \
                            patch.object(module.subprocess, 'Popen', side_effect=spawn), \
                            patch('agents.opencode.build_opencode_base_cmd', return_value=['opencode', 'run']):
                        fixed = snapshots.freeze_system_prompt(system)
                        result = getattr(module, cls)()._run_once('/business', message, fixed, session, ['/dependency'])
                        self.assertEqual(result.returncode, 0, result.error)
                        self.assertTrue(fixed.path.exists())
                        self.assertEqual(len(list(Path(tmp).rglob('*'))), 2)  # inline/ + role file
                    sent = process.stdin.write.call_args.args[0]
                    self.assertIn(message, sent)
                    process.stdin.close.assert_called_once()
                    if backend in {'codex', 'opencode'} and not session:
                        self.assertIn(system, sent)
                        if backend == 'opencode':
                            self.assertIn('/dependency', sent)
                    else:
                        self.assertNotIn(system, sent)
                    if session:
                        self.assertIn(session, captured['cmd'])


if __name__ == '__main__':
    unittest.main()
