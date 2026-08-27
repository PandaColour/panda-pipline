import json
import unittest
from unittest.mock import MagicMock, patch

from agents import Agent
from agents.opencode import OpencodeAgent


class OpencodeAgentTests(unittest.TestCase):
    def _process(self, *lines, returncode=0):
        process = MagicMock()
        process.stdout.readline.side_effect = [*(line + "\n" for line in lines), ""]
        process.poll.return_value = returncode
        process.returncode = returncode
        return process

    def _text_event(self, session_id, message_id, text):
        return json.dumps({
            "type": "text",
            "timestamp": 1786602955843,
            "sessionID": session_id,
            "part": {"type": "text", "text": text, "messageID": message_id},
        })

    def test_agent_type_opencode_uses_opencode_strategy(self):
        with patch.object(Agent, "_load_system_prompt", return_value=""):
            agent = Agent("opencode", "prompt.md", "/work/repo", agent_type="opencode")

        self.assertEqual(agent.agent_impl.__class__.__name__, "OpencodeAgent")

    def test_run_opencode_task_uses_headless_json_command(self):
        process = self._process(
            self._text_event("ses-abc", "msg-1", "done"),
        )

        with patch.object(Agent, "_load_system_prompt", return_value="Be precise."), \
                patch("agents.opencode.build_opencode_base_cmd", return_value=[
            "/usr/local/bin/opencode", "run", "--format", "json", "--auto"
        ]), patch("agents.opencode.subprocess.Popen", return_value=process) as popen:
            result = Agent("opencode", "prompt.md", "/work/repo", agent_type="opencode").send_message(
                "Analyze this code"
            )

        popen.assert_called_once()
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[0], "/usr/local/bin/opencode")
        self.assertEqual(cmd[1:5], ["run", "--format", "json", "--auto"])
        self.assertEqual(cmd[-1], "[SYSTEM PROMPT]\nBe precise.\n[/SYSTEM PROMPT]\n\n[USER PROMPT]\nAnalyze this code")
        self.assertEqual(popen.call_args.kwargs["cwd"], "/work/repo")
        self.assertNotIn("--session", cmd)
        self.assertNotIn("--continue", cmd)
        self.assertEqual(result, "done")

    def test_run_opencode_task_resumes_explicit_session_for_follow_up(self):
        process = self._process(
            self._text_event("ses-opencode", "msg-2", "continued"),
        )

        with patch.object(Agent, "_load_system_prompt", return_value="ignored after first turn"), \
                patch("agents.opencode.build_opencode_base_cmd", return_value=[
            "/usr/local/bin/opencode", "run", "--format", "json", "--auto"
        ]), patch("agents.opencode.subprocess.Popen", return_value=process) as popen:
            agent = Agent("opencode", "prompt.md", "/work/repo", agent_type="opencode")
            agent.session_id = "ses-opencode"
            result = agent.send_message("Continue task")

        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[0], "/usr/local/bin/opencode")
        self.assertEqual(cmd[1:5], ["run", "--format", "json", "--auto"])
        self.assertIn("--session", cmd)
        self.assertEqual(cmd[cmd.index("--session") + 1], "ses-opencode")
        self.assertNotIn("--continue", cmd)
        self.assertEqual(cmd[-1], "Continue task")
        self.assertEqual(result, "continued")

    def test_prefers_last_assistant_message_text_over_tool_step_text(self):
        process = self._process(
            self._text_event("ses-abc", "msg-1", "intermediate note"),
            '{"type":"tool_use","sessionID":"ses-abc","part":{"type":"tool","tool":"bash","state":{"status":"completed"}}}',
            self._text_event("ses-abc", "msg-2", "final answer"),
        )

        with patch("agents.opencode.build_opencode_base_cmd", return_value=["opencode", "run"]), \
                patch("agents.opencode.subprocess.Popen", return_value=process):
            result = OpencodeAgent().run("/work/repo", "Review")

        self.assertEqual(result.text, "final answer")
        self.assertEqual(result.session_id, "ses-abc")
        self.assertEqual(result.returncode, 0)

    def test_missing_binary_returns_failure_result(self):
        with patch("agents.opencode.shutil.which", return_value=None):
            result = OpencodeAgent().run("/work/repo", "hi")

        self.assertEqual(result.returncode, -1)
        self.assertIn("opencode", result.error)

    def test_retries_transient_failure_once_after_five_seconds(self):
        failed_process = self._process(
            "Unexpected server error. Check server logs for details.",
            returncode=1,
        )
        successful_process = self._process(
            self._text_event("ses-abc", "msg-1", "retried successfully"),
        )

        with patch("agents.opencode.build_opencode_base_cmd", return_value=["opencode", "run"]), \
                patch("agents.opencode.subprocess.Popen", side_effect=[failed_process, successful_process]) as popen, \
                patch("agents.opencode.time.sleep") as sleep:
            result = OpencodeAgent().run("/work/repo", "Retry this task")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.text, "retried successfully")
        self.assertEqual(popen.call_count, 2)
        sleep.assert_called_once_with(5)

    def test_model_env_var_adds_model_flag(self):
        from agents.opencode import build_opencode_base_cmd

        with patch.dict("os.environ", {"OPENCODE_MODEL": "deepseek-anthropic/deepseek-v4-flash"}), \
                patch("agents.opencode.shutil.which", return_value="/usr/local/bin/opencode"):
            cmd = build_opencode_base_cmd()

        self.assertEqual(cmd[0], "/usr/local/bin/opencode")
        self.assertEqual(cmd[cmd.index("--model") + 1], "deepseek-anthropic/deepseek-v4-flash")


if __name__ == "__main__":
    unittest.main()
