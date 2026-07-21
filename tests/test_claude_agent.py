import subprocess
import unittest
from unittest.mock import MagicMock, patch

from agents import Agent


class ClaudeAgentTests(unittest.TestCase):
    def _process(self, *lines, returncode=0):
        process = MagicMock()
        process.stdout.readline.side_effect = [*(line + "\n" for line in lines), ""]
        process.poll.return_value = returncode
        process.returncode = returncode
        return process

    def test_fresh_call_captures_session_id(self):
        process = self._process(
            '{"type":"system","subtype":"init","session_id":"claude-session"}',
            '{"type":"result","subtype":"success","session_id":"claude-session","result":"done"}',
        )

        with patch.object(Agent, "_load_system_prompt", return_value="Be precise."), \
                patch("agents.claude.subprocess.Popen", return_value=process) as popen:
            result = Agent("claude", "prompt.md", "/work/repo", agent_type="claude").send_message(
                "Analyze this code"
            )

        cmd = popen.call_args.args[0]
        self.assertNotIn("--resume", cmd)
        self.assertNotIn("--continue", cmd)
        self.assertEqual(cmd[-1], "-p")
        self.assertEqual(popen.call_args.kwargs["stdin"], subprocess.PIPE)
        process.stdin.write.assert_called_once_with("Analyze this code")
        process.stdin.close.assert_called_once()
        self.assertEqual(result, "done")

    def test_follow_up_resumes_explicit_session_id(self):
        process = self._process(
            '{"type":"result","subtype":"success","session_id":"claude-session","result":"continued"}',
        )

        with patch.object(Agent, "_load_system_prompt", return_value="Be precise."), \
                patch("agents.claude.subprocess.Popen", return_value=process) as popen:
            agent = Agent("claude", "prompt.md", "/work/repo", agent_type="claude")
            agent.session_id = "claude-session"
            result = agent.send_message("Continue task")

        cmd = popen.call_args.args[0]
        self.assertIn("--resume", cmd)
        self.assertEqual(cmd[cmd.index("--resume") + 1], "claude-session")
        self.assertNotIn("--continue", cmd)
        self.assertEqual(cmd[-1], "-p")
        self.assertEqual(popen.call_args.kwargs["stdin"], subprocess.PIPE)
        process.stdin.write.assert_called_once_with("Continue task")
        process.stdin.close.assert_called_once()
        self.assertEqual(result, "continued")

    def test_prefers_final_result_over_streamed_progress_text(self):
        process = self._process(
            '{"type":"assistant","session_id":"claude-session","message":{"content":[{"type":"text","text":"正在审查需求。"}]}}',
            '{"type":"result","subtype":"success","session_id":"claude-session","result":"同意方案\\n需求完整。"}',
        )

        with patch("agents.claude.subprocess.Popen", return_value=process):
            result = Agent("claude", "prompt.md", "/work/repo", agent_type="claude").send_message("审查")

        self.assertTrue(result.startswith("同意方案"))

    def test_retries_connection_closed_mid_response_once(self):
        failed_process = self._process(
            '{"type":"system","subtype":"init","session_id":"claude-session"}',
            "API Error: Connection closed mid-response. The response above may be incomplete.",
            returncode=1,
        )
        successful_process = self._process(
            '{"type":"result","subtype":"success","session_id":"claude-session","result":"retried successfully"}',
        )

        with patch("agents.claude.subprocess.Popen", side_effect=[failed_process, successful_process]) as popen, \
                patch("agents.claude.time.sleep") as sleep:
            result = Agent("claude", "prompt.md", "/work/repo", agent_type="claude").send_message("继续")

        self.assertEqual(result, "retried successfully")
        self.assertEqual(popen.call_count, 2)
        second_cmd = popen.call_args_list[1].args[0]
        self.assertIn("--resume", second_cmd)
        self.assertEqual(second_cmd[second_cmd.index("--resume") + 1], "claude-session")
        sleep.assert_called_once_with(3)


if __name__ == "__main__":
    unittest.main()
