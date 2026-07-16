import unittest
from unittest.mock import MagicMock, patch

from agents import Agent


class CursorAgentTests(unittest.TestCase):
    def _process(self, *lines, returncode=0):
        process = MagicMock()
        process.stdout.readline.side_effect = [*(line + "\n" for line in lines), ""]
        process.poll.return_value = returncode
        process.returncode = returncode
        return process

    def test_package_exposes_only_agent(self):
        import agents

        self.assertEqual(agents.__all__, ["Agent"])

    def test_agent_type_cursor_uses_cursor_strategy(self):
        with patch.object(Agent, "_load_system_prompt", return_value=""):
            agent = Agent("cursor", "prompt.md", "/work/repo", agent_type="cursor")

        self.assertEqual(agent.agent_impl.__class__.__name__, "CursorAgent")

    def test_run_cursor_task_uses_headless_streaming_command(self):
        process = self._process(
            '{"type":"system","subtype":"init","session_id":"cursor-chat","model":"auto"}',
            '{"type":"assistant","timestamp_ms":1,"message":{"content":[{"type":"text","text":"done"}]}}',
            '{"type":"assistant","model_call_id":"call-1","message":{"content":[{"type":"text","text":"buffered duplicate"}]}}',
        )

        with patch.object(Agent, "_load_system_prompt", return_value="Be precise."), \
                patch("agents.cursor.build_cursor_base_cmd", return_value=[
            "/usr/local/bin/agent", "-p", "--force", "--output-format", "stream-json", "--stream-partial-output"
        ]), patch("agents.cursor.subprocess.Popen", return_value=process) as popen:
            result = Agent("cursor", "prompt.md", "/work/repo", agent_type="cursor").send_message(
                "Analyze this code"
            )

        popen.assert_called_once()
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[0], "/usr/local/bin/agent")
        self.assertEqual(cmd[1:5], ["-p", "--force", "--output-format", "stream-json"])
        self.assertIn("--stream-partial-output", cmd)
        self.assertEqual(cmd[-1], "[SYSTEM PROMPT]\nBe precise.\n[/SYSTEM PROMPT]\n\n[USER PROMPT]\nAnalyze this code")
        self.assertEqual(popen.call_args.kwargs["cwd"], "/work/repo")
        self.assertNotIn("--resume", cmd)
        self.assertNotIn("--continue", cmd)
        self.assertEqual(result, "done")

    def test_run_cursor_task_resumes_explicit_session_for_follow_up(self):
        process = self._process(
            '{"type":"system","subtype":"init","session_id":"cursor-chat","model":"auto"}',
            '{"type":"result","session_id":"cursor-chat","result":"continued"}',
        )

        with patch.object(Agent, "_load_system_prompt", return_value="ignored after first turn"), \
                patch("agents.cursor.build_cursor_base_cmd", return_value=[
            "/usr/local/bin/agent", "-p", "--force", "--output-format", "stream-json", "--stream-partial-output"
        ]), patch("agents.cursor.subprocess.Popen", return_value=process) as popen:
            agent = Agent("cursor", "prompt.md", "/work/repo", agent_type="cursor")
            agent.session_id = "cursor-chat"
            result = agent.send_message("Continue task")

        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[0], "/usr/local/bin/agent")
        self.assertEqual(cmd[1:5], ["-p", "--force", "--output-format", "stream-json"])
        self.assertIn("--resume", cmd)
        self.assertEqual(cmd[cmd.index("--resume") + 1], "cursor-chat")
        self.assertNotIn("--continue", cmd)
        self.assertEqual(cmd[-1], "Continue task")
        self.assertEqual(result, "continued")


if __name__ == "__main__":
    unittest.main()
