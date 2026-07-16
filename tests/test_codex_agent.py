import subprocess
import unittest
from unittest.mock import MagicMock, patch

from agents import Agent


class CodexAgentTests(unittest.TestCase):
    def _process(self, *lines, returncode=0):
        process = MagicMock()
        process.stdout.readline.side_effect = [*(line + "\n" for line in lines), ""]
        process.poll.return_value = returncode
        process.returncode = returncode
        return process

    def test_fresh_call_captures_thread_id(self):
        process = self._process(
            '{"type":"thread.started","thread_id":"codex-thread"}',
            '{"type":"item.completed","item":{"type":"agent_message","text":"done"}}',
        )

        with patch.object(Agent, "_load_system_prompt", return_value="Be precise."), \
                patch("agents.codex.subprocess.Popen", return_value=process) as popen:
            result = Agent("codex", "prompt.md", "/work/repo", agent_type="codex").send_message(
                "Analyze this code"
            )

        cmd = popen.call_args.args[0]
        self.assertNotIn("resume", cmd)
        self.assertNotIn("--last", cmd)
        self.assertEqual(cmd[-1], "-")
        self.assertEqual(popen.call_args.kwargs["stdin"], subprocess.PIPE)
        process.stdin.write.assert_called_once_with(
            "[SYSTEM PROMPT]\nBe precise.\n[/SYSTEM PROMPT]\n\n[USER PROMPT]\nAnalyze this code"
        )
        process.stdin.close.assert_called_once()
        self.assertEqual(result, "done")

    def test_follow_up_resumes_explicit_thread_id(self):
        process = self._process(
            '{"type":"thread.started","thread_id":"codex-thread"}',
            '{"type":"text","content":"continued"}',
        )

        with patch.object(Agent, "_load_system_prompt", return_value="ignored after first turn"), \
                patch("agents.codex.subprocess.Popen", return_value=process) as popen:
            agent = Agent("codex", "prompt.md", "/work/repo", agent_type="codex")
            agent.session_id = "codex-thread"
            result = agent.send_message("Continue task")

        cmd = popen.call_args.args[0]
        self.assertEqual(
            cmd,
            ["codex", "exec", "resume", "--json", "codex-thread", "-"],
        )
        self.assertEqual(popen.call_args.kwargs["cwd"], "/work/repo")
        self.assertNotIn("-C", cmd)
        self.assertNotIn("--last", cmd)
        self.assertEqual(popen.call_args.kwargs["stdin"], subprocess.PIPE)
        process.stdin.write.assert_called_once_with("Continue task")
        process.stdin.close.assert_called_once()
        self.assertEqual(result, "continued")


if __name__ == "__main__":
    unittest.main()
