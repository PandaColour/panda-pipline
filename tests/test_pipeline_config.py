import json
import runpy
import unittest
from pathlib import Path
from unittest.mock import mock_open, patch

import config


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "config.json"
EXAMPLE_CONFIG_PATH = ROOT / "config" / "config.json.example"
GITIGNORE_PATH = ROOT / ".gitignore"

EXPECTED_REPOS = [
    {
        "url": "https://gitee.com/pandacolour/aiphone.git",
        "branch": "main",
    },
]

EXPECTED_AGENT_TYPES = [
    {"role": "requirement_breaker", "agent_type": "cursor"},
    {"role": "breakdown_reviewer", "agent_type": "cursor"},
    {"role": "requirements_analyst", "agent_type": "cursor"},
    {"role": "requirements_reviewer", "agent_type": "cursor"},
    {"role": "developer", "agent_type": "cursor"},
    {"role": "code_reviewer", "agent_type": "cursor"},
]


class PipelineConfigTests(unittest.TestCase):
    def test_example_file_contains_object_array_runtime_configuration(self):
        raw_config = json.loads(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))

        self.assertEqual(
            raw_config["PROJECT_ROOT"],
            r"/Users/panda.colour/Company/ios-m6",
        )
        self.assertEqual(raw_config["REPOS"], EXPECTED_REPOS)
        self.assertEqual(raw_config["AGENT_TYPES"], EXPECTED_AGENT_TYPES)
        self.assertTrue(all(isinstance(repo, dict) for repo in raw_config["REPOS"]))
        self.assertTrue(all(isinstance(agent, dict) for agent in raw_config["AGENT_TYPES"]))

    def test_local_json_config_is_gitignored_but_example_is_not(self):
        ignored_paths = {
            line.strip()
            for line in GITIGNORE_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        self.assertIn("/config/config.json", ignored_paths)
        self.assertNotIn("/config/config.json.example", ignored_paths)

    def test_config_module_exposes_json_values(self):
        fixture = {
            "PROJECT_ROOT": "/tmp/pipeline-config-test",
            "REPOS": [{"url": "https://example.test/project.git", "branch": "test"}],
            "AGENT_TYPES": [{"role": "developer", "agent_type": "codex"}],
        }
        with patch("builtins.open", mock_open(read_data=json.dumps(fixture))) as read_config:
            # Execute in a fresh namespace; do not reload or mutate the runtime
            # config used by other tests, and never read the user's local JSON.
            loaded = runpy.run_path(str(ROOT / "config.py"))
        read_config.assert_called_once_with(str(CONFIG_PATH), encoding="utf-8")
        self.assertEqual(loaded["PIPELINE_CONFIG_PATH"], str(CONFIG_PATH))
        for field, value in fixture.items():
            self.assertEqual(loaded[field], value)

    def test_get_agent_type_reads_object_array(self):
        with patch.object(
            config,
            "AGENT_TYPES",
            [{"role": "developer", "agent_type": "codex"}],
        ):
            self.assertEqual(config.get_agent_type("developer"), "codex")

    def test_get_agent_type_rejects_missing_role(self):
        with patch.object(config, "AGENT_TYPES", []):
            with self.assertRaisesRegex(ValueError, "missing_role.*config/config.json"):
                config.get_agent_type("missing_role")

    def test_get_agent_type_rejects_blank_backend(self):
        with patch.object(
            config,
            "AGENT_TYPES",
            [{"role": "developer", "agent_type": " "}],
        ):
            with self.assertRaisesRegex(ValueError, "developer.*non-empty string"):
                config.get_agent_type("developer")


if __name__ == "__main__":
    unittest.main()
