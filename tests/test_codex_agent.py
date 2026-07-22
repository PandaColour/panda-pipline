import subprocess
import unittest
from unittest.mock import MagicMock, patch

from agents import Agent
from agents.codex import CODEX_BASE_CMD


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
        self.assertNotIn("--sandbox", cmd)
        self.assertIn('sandbox_mode="danger-full-access"', cmd)
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
        expected_cmd = CODEX_BASE_CMD.copy()
        expected_cmd.insert(2, "resume")
        expected_cmd.extend(["codex-thread", "-"])
        self.assertEqual(
            cmd,
            expected_cmd,
        )
        self.assertEqual(popen.call_args.kwargs["cwd"], "/work/repo")
        self.assertNotIn("-C", cmd)
        self.assertNotIn("--last", cmd)
        self.assertNotIn("--sandbox", cmd)
        self.assertIn('sandbox_mode="danger-full-access"', cmd)
        self.assertEqual(popen.call_args.kwargs["stdin"], subprocess.PIPE)
        process.stdin.write.assert_called_once_with("Continue task")
        process.stdin.close.assert_called_once()
        self.assertEqual(result, "continued")

    def test_prefers_completed_agent_message_over_streamed_progress_text(self):
        process = self._process(
            '{"type":"thread.started","thread_id":"codex-thread"}',
            '{"type":"agent_message_delta","delta":"正在审查需求。"}',
            '{"type":"item.completed","item":{"type":"agent_message","text":"同意方案\\n需求完整。"}}',
        )

        with patch("agents.codex.subprocess.Popen", return_value=process):
            result = Agent("codex", "prompt.md", "/work/repo", agent_type="codex").send_message("审查")

        self.assertTrue(result.startswith("同意方案"))


if __name__ == "__main__":
    unittest.main()
