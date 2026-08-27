import os
import unittest
from unittest.mock import MagicMock, patch

from agents.dsh import DshAgent


class DshAgentTests(unittest.TestCase):
    def test_launches_with_danger_full_access_in_child_environment(self):
        process = MagicMock()
        process.communicate.return_value = (
            '{"sessionId":"dsh-session","finalResponse":"ok"}\n',
            None,
        )
        process.returncode = 0

        with patch.dict(os.environ, {"PIPELINE_ENV_SENTINEL": "preserved"}, clear=False), \
                patch("agents.dsh.subprocess.Popen", return_value=process) as popen:
            result = DshAgent()._run_once("/tmp", "test")

        child_env = popen.call_args.kwargs["env"]
        self.assertEqual(child_env["DSH_PERMISSION_MODE"], "danger-full-access")
        self.assertEqual(child_env["PIPELINE_ENV_SENTINEL"], "preserved")
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
