import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agents import Agent
from agents._result import AgentRunResult
from agents._retry import run_with_retry, session_is_invalid
from execution_plan import ExecutionPlanStore


class SessionRecoveryTests(unittest.TestCase):
    def test_all_backends_clear_durable_reference_before_fresh_retry(self):
        for backend in ("codex", "claude", "cursor", "opencode", "dsh"):
            with self.subTest(backend=backend), tempfile.TemporaryDirectory() as directory:
                store = ExecutionPlanStore(directory, str(Path(directory, "index.md")))
                store.write({"demand": {"id": "D-001", "status": "开发中"},
                             "items": []})
                name = "批次-006 小需求验证审查"
                store.set_agent_session(name, session_id="old", prompt_file="p",
                                        agent_type=backend)

                def persist(session):
                    if session is None:
                        store.clear_agent_session(name)
                    else:
                        store.set_agent_session(name, session_id=session,
                                                prompt_file="p", agent_type=backend)

                with patch.object(Agent, "_load_system_prompt", return_value="role"):
                    agent = Agent(name, "p", directory, agent_type=backend,
                                  session_id="old", session_update_callback=persist)
                calls = []

                def run_once(work_dir, message, system_prompt, session, *extra):
                    calls.append(session)
                    self.assertEqual(system_prompt, "role")
                    if len(calls) == 1:
                        return AgentRunResult("", "old", 1, "context_window_exceeded")
                    self.assertIsNone(agent.session_id)
                    self.assertIsNone(store.get_agent_session(name))
                    return AgentRunResult("done", "new", 0)

                with patch.object(agent.agent_impl, "_run_once", side_effect=run_once), \
                        patch(f"agents.{backend}.time.sleep"):
                    self.assertEqual(agent.send_message("read current reports"), "done")
                self.assertEqual(calls, ["old", None])
                self.assertEqual(store.get_agent_session(name), "new")

    def test_network_failure_keeps_session(self):
        once = Mock(side_effect=[AgentRunResult("", "old", 1, "connection reset"),
                                 AgentRunResult("ok", "old", 0)])
        invalidate = Mock()
        run_with_retry(once, "old", retries=3, delay=5, sleep=Mock(), invalidate=invalidate)
        self.assertEqual([c.args[0] for c in once.call_args_list], ["old", "old"])
        invalidate.assert_not_called()

    def test_repeated_context_failure_does_not_create_endless_fresh_sessions(self):
        once = Mock(return_value=AgentRunResult("", "bad", 1, "context_length_exceeded"))
        result = run_with_retry(once, "old", retries=3, delay=5, sleep=Mock())
        self.assertEqual(once.call_count, 2)
        self.assertIsNone(result.session_id)
        self.assertNotEqual(result.returncode, 0)

    def test_failed_replacement_cannot_restore_old_session_on_restart(self):
        once = Mock(side_effect=[AgentRunResult("", "old", 1, "thread not found"),
                                 AgentRunResult("", "fresh", 1, "connection reset")])
        result = run_with_retry(once, "old", retries=1, delay=5, sleep=Mock())
        self.assertIsNone(result.session_id)

    def test_compaction_network_error_and_successful_prose_do_not_invalidate(self):
        self.assertFalse(session_is_invalid(
            AgentRunResult("", "old", 1, "Error running remote compact task: timeout")))
        self.assertFalse(session_is_invalid(
            AgentRunResult("context_window_exceeded", "old", 0)))

    def test_clearing_legacy_fallbacks_preserves_other_agents(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ExecutionPlanStore(directory, str(Path(directory, "index.md")))
            store.write({"demand": {"agent_sessions": {"reviewer": "old", "developer": "keep"}},
                         "items": [{"id": "R-001", "agent_sessions": {"reviewer": "old"}}]})
            store.clear_agent_session("reviewer", requirement_id="R-001")
            self.assertIsNone(store.get_agent_session("reviewer", requirement_id="R-001"))
            self.assertEqual(store.get_agent_session("developer"), "keep")

    def test_persistence_failure_prevents_retry(self):
        once = Mock(return_value=AgentRunResult("", "old", 1, "session expired"))
        with self.assertRaises(OSError):
            run_with_retry(once, "old", retries=3, delay=5, sleep=Mock(),
                           invalidate=Mock(side_effect=OSError("disk full")))
        self.assertEqual(once.call_count, 1)
