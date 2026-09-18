import json
import runpy
import unittest
from pathlib import Path
from unittest.mock import mock_open, patch

import config


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "config.json"
EXAMPLE_CONFIG_PATH = ROOT / "config" / "config.json.mac.example"
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
    def load_external(self, **extra):
        fixture = {'PROJECT_ROOT': '/tmp/project', 'REPOS': [], 'AGENT_TYPES': [], **extra}
        with patch('builtins.open', mock_open(read_data=json.dumps(fixture))):
            return runpy.run_path(str(ROOT / 'config.py'))

    def test_external_dependencies_default_to_empty_for_old_config(self):
        loaded = self.load_external()
        self.assertEqual(loaded['EXTERNAL_CLI_TOOLS'], [])
        self.assertEqual(loaded['EXTERNAL_SKILLS'], [])

    def test_external_skills_accept_claude_agent_type(self):
        entry = {'source': 'org/repo', 'names': ['example-skill'], 'agents': ['claude']}
        loaded = self.load_external(EXTERNAL_SKILLS=[entry])
        self.assertEqual(loaded['EXTERNAL_SKILLS'], [entry])

    def test_external_dependencies_reject_invalid_commands_and_skill_names(self):
        for values in (
            {'EXTERNAL_CLI_TOOLS': [{'name': 'tool', 'check': 'tool --version', 'install': ['npm']}]},
            {'EXTERNAL_SKILLS': [{'source': 'org/repo', 'names': []}]},
            {'EXTERNAL_SKILLS': [{'source': 'org/repo', 'names': ['a'], 'agents': ['unknown']}]},
            {'EXTERNAL_CLI_TOOLS': {}},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.load_external(**values)

    def test_cli_verification_options_are_validated(self):
        base = {'name': 'tool', 'check': ['tool', '--version'], 'install': ['installer']}
        for extra in (
            {'path_env': 'HOME'}, {'check_timeout': 0}, {'check_timeout': True},
            {'verify': 'not-array'}, {'verify': [{'command': ['tool'], 'contains': []}]},
        ):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.load_external(EXTERNAL_CLI_TOOLS=[{**base, **extra}])

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

    def test_all_platform_examples_load_with_matching_installers(self):
        for host, installer in (('mac', 'brew'), ('win', 'winget'), ('linux', 'bash')):
            with self.subTest(host=host):
                path = ROOT / 'config' / f'config.json.{host}.example'
                raw = json.loads(path.read_text())
                with patch('builtins.open', mock_open(read_data=json.dumps(raw))):
                    loaded = runpy.run_path(str(ROOT / 'config.py'))
                self.assertEqual(loaded['AGENT_TYPES'], EXPECTED_AGENT_TYPES)
                tool = next(row for row in loaded['EXTERNAL_CLI_TOOLS'] if row['name'] == 'android-cli')
                self.assertEqual(tool['install'][0], installer)
                self.assertTrue(all(row['command'][0] == tool['check'][0] for row in tool['verify']))

    def test_local_json_config_is_gitignored_but_example_is_not(self):
        ignored_paths = {
            line.strip()
            for line in GITIGNORE_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        self.assertIn("/config/config.json", ignored_paths)
        for host in ("win", "mac", "linux"):
            self.assertNotIn(f"/config/config.json.{host}.example", ignored_paths)

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
