import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import environment


class ExternalDependencyTests(unittest.TestCase):
    cli = {'name': 'example', 'check': ['example', '--version'], 'install': ['npm', 'install', '-g', 'example']}
    skill = {'source': 'org/repo', 'names': ['example-skill'], 'agents': ['codex', 'claude-code', 'cursor']}

    def setUp(self):
        for patcher in (
            patch.object(environment, 'EXTERNAL_CLI_TOOLS', [], create=True),
            patch.object(environment, 'EXTERNAL_SKILLS', [], create=True),
            patch.object(environment.shutil, 'which', side_effect=lambda x: x),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def listing(self, agents=None, source='org/repo'):
        return subprocess.CompletedProcess([], 0, json.dumps([{
            'name': 'example-skill', 'scope': 'global', 'source': source,
            'agents': agents if agents is not None else ['Codex', 'Claude Code', 'Cursor'],
        }]), '')

    def test_cli_ready_is_not_reinstalled(self):
        with patch.object(environment, 'EXTERNAL_CLI_TOOLS', [self.cli]), \
                patch.object(environment.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'v1', '')) as run:
            environment._prepare_external_dependencies('/work')
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], self.cli['check'])

    def test_user_relative_executable_is_expanded_for_check_and_published_path(self):
        entry = {**self.cli, 'check': ['~/.local/bin/example', '--version'],
                 'path_env': 'PANDA_PIPELINE_TEST_CLI'}
        with patch.dict(os.environ), patch.object(environment, 'EXTERNAL_CLI_TOOLS', [entry]), \
                patch.object(environment.shutil, 'which', return_value=None), \
                patch.object(environment.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            environment._prepare_external_dependencies('/work')
            expected = str(Path.home() / '.local/bin/example')
            self.assertEqual(run.call_args.args[0][0], expected)
            self.assertEqual(os.environ['PANDA_PIPELINE_TEST_CLI'], str(Path(expected).resolve()))

    def test_configured_capability_checks_publish_path_only_after_success(self):
        entry = {**self.cli, 'path_env': 'PANDA_PIPELINE_TEST_CLI', 'check_timeout': 90,
                 'verify': [{'command': ['example', 'layout', '--help'], 'contains': ['--full', '--device']}]}
        with patch.dict(os.environ, {'PANDA_PIPELINE_TEST_CLI': 'stale'}), \
                patch.object(environment, 'EXTERNAL_CLI_TOOLS', [entry]), \
                patch.object(environment.shutil, 'which', return_value='/tools/example'), \
                patch.object(environment.subprocess, 'run', side_effect=[
                    subprocess.CompletedProcess([], 0, 'v1', ''),
                    subprocess.CompletedProcess([], 0, '--full --device', '')]) as run:
            environment._prepare_external_dependencies('/work')
            self.assertEqual(os.environ['PANDA_PIPELINE_TEST_CLI'], '/tools/example')
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].kwargs['timeout'], 90)
        self.assertEqual(run.call_args_list[1].kwargs['timeout'], 15)

    def test_capability_failure_clears_path_without_reinstall(self):
        entry = {**self.cli, 'path_env': 'PANDA_PIPELINE_TEST_CLI',
                 'verify': [{'command': ['example', 'layout', '--help'], 'contains': ['--full']}]}
        with patch.dict(os.environ, {'PANDA_PIPELINE_TEST_CLI': 'stale'}), \
                patch.object(environment, 'EXTERNAL_CLI_TOOLS', [entry]), \
                patch.object(environment.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'old help', '')) as run:
            environment._prepare_external_dependencies('/work')
            self.assertEqual(os.environ['PANDA_PIPELINE_TEST_CLI'], '')
        self.assertEqual(run.call_count, 2)

    def test_disabled_cli_clears_previously_published_path(self):
        entry = {**self.cli, 'enabled': False, 'path_env': 'PANDA_PIPELINE_TEST_CLI'}
        with patch.dict(os.environ, {'PANDA_PIPELINE_TEST_CLI': 'stale'}), \
                patch.object(environment, 'EXTERNAL_CLI_TOOLS', [entry]):
            environment._prepare_external_dependencies('/work')
            self.assertEqual(os.environ['PANDA_PIPELINE_TEST_CLI'], '')

    def test_android_example_runs_entirely_through_generic_checks(self):
        example = json.loads((Path(__file__).resolve().parents[1] / 'config/config.json.mac.example').read_text())
        entry = next(row for row in example['EXTERNAL_CLI_TOOLS'] if row['name'] == 'android-cli')
        output = 'Android CLI 1.0 --full --device --annotate --screenshot --string --apks'
        with patch.dict(os.environ), patch.object(environment, 'EXTERNAL_CLI_TOOLS', [entry]), \
                patch.object(environment.shutil, 'which', return_value='/tools/android'), \
                patch.object(environment.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, '')) as run:
            environment._prepare_external_dependencies('/work')
            self.assertEqual(os.environ[entry['path_env']], '/tools/android')
        commands = [entry['check'], *[row['command'] for row in entry['verify']]]
        self.assertEqual([call.args[0] for call in run.call_args_list], [['/tools/android', *command[1:]] for command in commands])
        self.assertEqual(len(commands), 5)

    def test_missing_cli_is_installed_then_rechecked(self):
        ok = subprocess.CompletedProcess([], 0, '', '')
        with patch.object(environment, 'EXTERNAL_CLI_TOOLS', [self.cli]), \
                patch.object(environment.subprocess, 'run', side_effect=[FileNotFoundError(), ok, ok]) as run:
            environment._prepare_external_dependencies('/work')
        self.assertEqual([c.args[0] for c in run.call_args_list], [self.cli['check'], self.cli['install'], self.cli['check']])

    def test_cli_check_timeout_does_not_trigger_reinstall(self):
        with patch.object(environment, 'EXTERNAL_CLI_TOOLS', [self.cli]), \
                patch.object(environment.subprocess, 'run', side_effect=subprocess.TimeoutExpired('example', 45)) as run:
            environment._prepare_external_dependencies('/work')
        self.assertEqual(run.call_count, 1)

    def test_skills_ready_for_all_agents_is_not_reinstalled(self):
        with patch.object(environment, 'EXTERNAL_SKILLS', [self.skill]), \
                patch.object(environment.subprocess, 'run', return_value=self.listing()) as run:
            environment._prepare_external_dependencies('/work')
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], ['npx', '--yes', 'skills', 'ls', '-g', '--json'])

    def test_missing_agent_link_or_wrong_source_installs_and_rechecks(self):
        for listing in (self.listing(['Codex']), self.listing(source='other/repo')):
            with self.subTest(listing=listing.stdout), \
                    patch.object(environment, 'EXTERNAL_SKILLS', [self.skill]), \
                    patch.object(environment.subprocess, 'run', side_effect=[listing, subprocess.CompletedProcess([], 0, '', ''), self.listing()]) as run:
                environment._prepare_external_dependencies('/work')
            self.assertEqual(run.call_count, 3)
            self.assertEqual(run.call_args_list[1].args[0], ['npx', '--yes', 'skills', 'add', 'org/repo', '-y', '-g', '--agent', 'codex', 'claude-code', 'cursor'])

    def test_inventory_failure_does_not_install_anything(self):
        for result in (subprocess.TimeoutExpired('npx', 45), subprocess.CompletedProcess([], 0, 'not json', ''),
                       subprocess.CompletedProcess([], 1, '', 'offline')):
            with self.subTest(result=result), patch.object(environment, 'EXTERNAL_SKILLS', [self.skill]), \
                    patch.object(environment.subprocess, 'run', side_effect=[result]) as run:
                environment._prepare_external_dependencies('/work')
            self.assertEqual(run.call_count, 1)

    def test_disabled_entries_do_not_run_commands(self):
        with patch.object(environment, 'EXTERNAL_CLI_TOOLS', [{**self.cli, 'enabled': False}]), \
                patch.object(environment, 'EXTERNAL_SKILLS', [{**self.skill, 'enabled': False}]), \
                patch.object(environment.subprocess, 'run') as run:
            environment._prepare_external_dependencies('/work')
        run.assert_not_called()

    def test_cli_install_failure_does_not_block_next_tool(self):
        with patch.object(environment, 'EXTERNAL_CLI_TOOLS', [self.cli, {**self.cli, 'name': 'second'}]), \
                patch.object(environment.subprocess, 'run', side_effect=[
                    FileNotFoundError(), subprocess.CompletedProcess([], 1, '', ''),
                    subprocess.CompletedProcess([], 0, '', '')]) as run:
            environment._prepare_external_dependencies('/work')
        self.assertEqual(run.call_count, 3)
        for call in run.call_args_list:
            self.assertEqual(call.kwargs['stdin'], subprocess.DEVNULL)
            self.assertIn(call.kwargs['timeout'], (45, 300))
            self.assertFalse(call.kwargs.get('shell', False))

    def test_install_success_without_actual_skills_warns(self):
        empty = subprocess.CompletedProcess([], 0, '[]', '')
        with patch.object(environment, 'EXTERNAL_SKILLS', [self.skill]), \
                patch.object(environment.subprocess, 'run', side_effect=[empty, subprocess.CompletedProcess([], 0, '', ''), empty]), \
                patch('builtins.print') as output:
            environment._prepare_external_dependencies('/work')
        self.assertIn('安装后检查未通过', str(output.call_args_list))
