import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agents import Agent


class AgentSessionTests(unittest.TestCase):
    def _agent_with_runner(self, *results):
        with patch.object(Agent, "_load_system_prompt", return_value="system"):
            agent = Agent("developer", "prompt.md", "/work/repo", agent_type="cursor")
        agent.agent_impl = MagicMock()
        agent.agent_impl.run.side_effect = results
        return agent

    def test_saves_first_session_id_and_resumes_it_on_second_call(self):
        agent = self._agent_with_runner(
            SimpleNamespace(text="first", session_id="chat-1", returncode=0, error=None),
            SimpleNamespace(text="second", session_id="chat-1", returncode=0, error=None),
        )

        self.assertEqual(agent.send_message("first prompt"), "first")
        self.assertEqual(agent.send_message("second prompt"), "second")

        first_call, second_call = agent.agent_impl.run.call_args_list
        self.assertIsNone(first_call.kwargs.get("session_id"))
        self.assertEqual(second_call.kwargs.get("session_id"), "chat-1")
        self.assertEqual(getattr(agent, "session_id", None), "chat-1")

    def test_failed_first_call_without_id_keeps_next_call_fresh(self):
        agent = self._agent_with_runner(
            SimpleNamespace(text="", session_id=None, returncode=1, error="failed"),
            SimpleNamespace(text="retry", session_id="chat-2", returncode=0, error=None),
        )

        with self.assertRaisesRegex(RuntimeError, "failed"):
            agent.send_message("first prompt")
        self.assertEqual(agent.send_message("retry prompt"), "retry")

        first_call, second_call = agent.agent_impl.run.call_args_list
        self.assertIsNone(first_call.kwargs.get("session_id"))
        self.assertIsNone(second_call.kwargs.get("session_id"))
        self.assertEqual(getattr(agent, "session_id", None), "chat-2")

    def test_failed_call_keeps_captured_session_id_for_retry(self):
        agent = self._agent_with_runner(
            SimpleNamespace(text="", session_id="chat-3", returncode=1, error="interrupted"),
            SimpleNamespace(text="retry", session_id="chat-3", returncode=0, error=None),
        )

        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            agent.send_message("first prompt")
        self.assertEqual(agent.send_message("retry prompt"), "retry")

        first_call, second_call = agent.agent_impl.run.call_args_list
        self.assertIsNone(first_call.kwargs.get("session_id"))
        self.assertEqual(second_call.kwargs.get("session_id"), "chat-3")
        self.assertEqual(agent.session_id, "chat-3")

    def test_agents_in_same_work_dir_resume_their_own_sessions(self):
        developer = self._agent_with_runner(
            SimpleNamespace(text="dev-1", session_id="dev-chat", returncode=0, error=None),
            SimpleNamespace(text="dev-2", session_id="dev-chat", returncode=0, error=None),
        )
        reviewer = self._agent_with_runner(
            SimpleNamespace(text="review-1", session_id="review-chat", returncode=0, error=None),
            SimpleNamespace(text="review-2", session_id="review-chat", returncode=0, error=None),
        )

        developer.send_message("develop")
        reviewer.send_message("review")
        developer.send_message("continue developing")
        reviewer.send_message("continue reviewing")

        self.assertEqual(
            developer.agent_impl.run.call_args_list[1].kwargs["session_id"],
            "dev-chat",
        )
        self.assertEqual(
            reviewer.agent_impl.run.call_args_list[1].kwargs["session_id"],
            "review-chat",
        )


if __name__ == "__main__":
    unittest.main()
