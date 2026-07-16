import unittest
from unittest.mock import patch

from agents._cli import executable_name


class CliExecutableTests(unittest.TestCase):
    @patch("agents._cli.sys.platform", "win32")
    def test_uses_cmd_suffix_on_windows(self):
        self.assertEqual(executable_name("claude"), "claude.cmd")
        self.assertEqual(executable_name("codex"), "codex.cmd")
        self.assertEqual(executable_name("agent"), "agent.cmd")

    @patch("agents._cli.sys.platform", "darwin")
    def test_keeps_bare_executable_name_off_windows(self):
        self.assertEqual(executable_name("claude"), "claude")


if __name__ == "__main__":
    unittest.main()
