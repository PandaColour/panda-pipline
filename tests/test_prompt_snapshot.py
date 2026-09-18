import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents import Agent
from agents import _prompt_snapshot as snapshots


class PromptSnapshotTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='中文 prompt ')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'temp-prompt-skills'
        self.patch = patch.object(snapshots, 'PROMPT_ROOT', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.source = Path(snapshots.SOURCE_REPO_DIR) / 'system-prompt/code_developer.md'

    def test_writes_exact_utf8_rules_then_overwrites_same_file(self):
        content = '中文\n"quoted"\r\n$() & %PATH% ' * 5000
        first = snapshots.freeze_system_prompt(content, self.source)
        self.assertEqual(first.path.read_bytes(), content.encode('utf-8'))
        second = snapshots.freeze_system_prompt('edited during current run', self.source)
        self.assertEqual(first.path, second.path)
        self.assertEqual(first.path.read_text(), 'edited during current run')
        self.assertEqual(str(first), content)
        self.assertEqual(first.path, self.root.resolve() / 'system-prompt/code_developer.md')
        self.assertEqual(len(list(self.root.rglob('*.md'))), 1)
        self.assertFalse(any(self.root.rglob('*.txt')))

    def test_new_run_overwrites_same_path(self):
        original = snapshots.freeze_system_prompt('old run', self.source)
        new = snapshots.freeze_system_prompt('new run', self.source)
        self.assertEqual(original.path, new.path)
        self.assertEqual(new.path.read_text(), 'new run')
        self.assertEqual(len(list(self.root.rglob('*.md'))), 1)

    def test_role_directories_are_isolated(self):
        source2 = Path(snapshots.SOURCE_REPO_DIR) / 'break-system-prompt/code_developer.md'
        a = snapshots.freeze_system_prompt('normal', self.source)
        b = snapshots.freeze_system_prompt('split', source2)
        self.assertNotEqual(a.path, b.path)
        self.assertEqual(a.path.read_text(), 'normal')
        self.assertEqual(b.path.read_text(), 'split')

    def test_agent_freezes_only_after_rendering_placeholders(self):
        # Test rendering independently of which role still embeds a script command.
        source = self.root.parent / 'templates/developer.md'
        source.parent.mkdir()
        source.write_text('Run __PANDA_FIGMA_AUDIT_COMMAND__ for this task.\n')
        agent = Agent('developer', source.name, '/business', prompt_dir=str(source.parent))
        fixed = agent.system_prompt
        self.assertIsInstance(fixed, str)
        self.assertNotIn('__ANDROID_EMULATOR_COMMAND__', fixed)
        self.assertEqual(fixed.path.read_text(), fixed)
        self.assertIn('python3 scripts/figma_asset_audit.py', fixed)
        self.assertNotIn('__PANDA_', fixed)

    def test_snapshot_failure_does_not_silently_remove_role_rules(self):
        with patch('agents.agent.freeze_system_prompt', side_effect=FileNotFoundError('snapshot failed')):
            with self.assertRaises(FileNotFoundError):
                Agent('developer', 'code_developer.md', '/business')

    def test_atomic_write_failure_preserves_previous_run(self):
        old = snapshots.freeze_system_prompt('old', self.source)
        with patch.object(snapshots.os, 'replace', side_effect=OSError('denied')):
            with self.assertRaises(OSError):
                snapshots.freeze_system_prompt('new', self.source)
        self.assertEqual(old.path.read_text(), 'old')
        self.assertFalse(list(self.root.rglob('.writing-*')))

    def test_no_rules_creates_no_directory(self):
        self.assertEqual(snapshots.freeze_system_prompt(''), '')
        self.assertIsNone(snapshots.freeze_system_prompt(None))
        self.assertFalse(self.root.exists())

    def test_windows_guard_counts_serialized_utf16(self):
        with patch.object(snapshots.sys, 'platform', 'win32'):
            with self.assertRaisesRegex(ValueError, 'Windows'):
                snapshots.check_command_length(['agent.cmd', '界' * 9000])
            snapshots.check_command_length(['agent.exe', '界' * 9000])
            with self.assertRaisesRegex(ValueError, 'Windows'):
                snapshots.check_command_length(['agent.exe', '😀' * 20000])

    def test_paths_with_spaces_and_unicode_roundtrip(self):
        fixed = snapshots.freeze_system_prompt('rules', self.source)
        quoted = subprocess.list2cmdline(['claude.cmd', '--append-system-prompt-file', str(fixed.path)])
        self.assertIn('code_developer.md', quoted)
        self.assertEqual(snapshots.prompt_file(fixed), str(fixed.path))


if __name__ == '__main__':
    unittest.main()
