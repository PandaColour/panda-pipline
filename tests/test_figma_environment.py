import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

import environment as env


class FigmaEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.work = self.root / 'project'
        self.work.mkdir()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.enterContext(patch.object(Path, 'home', return_value=self.home))
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        self.enterContext(patch.object(env.shutil, 'which', side_effect=lambda name, **kwargs: '/bin/' + name))

    def write_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def cursor(self, token='secret-test-token'):
        self.write_json(self.work / '.cursor/mcp.json', {'mcpServers': {
            'figma-android-mcp': {'url': 'http://localhost:3333/mcp',
                                 'headers': {'X-Figma-Token': token}}}})

    def test_unconfigured_does_not_call_network_or_clients(self):
        with patch.object(env.subprocess, 'run') as run, patch.object(env, 'urlopen') as request:
            env._prepare_figma_mcp(str(self.work))
        run.assert_not_called()
        request.assert_not_called()

    def test_cursor_project_config_wins_and_figma_is_enabled_once(self):
        self.cursor('project-token')
        self.write_json(self.home / '.cursor/mcp.json', {'mcpServers': {
            'figma-android-mcp': {'url': 'http://localhost:3333/mcp',
                                 'headers': {'X-Figma-Token': 'global-token'}}}})
        tools = 'get_figma_node\nget_skill\ndownload_figma_images'
        with patch.object(env, '_check_figma_token', return_value='valid') as token, \
                patch.object(env.subprocess, 'run', return_value=Mock(returncode=0, stdout=tools, stderr='')) as run:
            env._prepare_figma_mcp(str(self.work))
        token.assert_called_once_with('X-Figma-Token', 'project-token')
        self.assertEqual([c.args[0][1:] for c in run.call_args_list], [
            ['mcp', 'enable', 'figma-android-mcp'], ['mcp', 'list-tools', 'figma-android-mcp']])
        self.assertTrue(all(c.kwargs['cwd'] == str(self.work) and c.kwargs['timeout'] > 0
                            for c in run.call_args_list))

    def test_cursor_approves_all_project_servers_without_figma(self):
        path = self.work / '.cursor/mcp.json'
        self.write_json(path, {'mcpServers': {
            'design': {'command': 'node'}, 'codegraph': {'command': 'python'}}})
        original = path.read_text()
        self.write_json(self.home / '.cursor/mcp.json', {'mcpServers': {
            'global-only': {'command': 'node'}}})
        with patch.object(env.subprocess, 'run', return_value=Mock(returncode=0, stdout='', stderr='')) as run, \
                patch.object(env, '_check_figma_token') as check:
            env._prepare_figma_mcp(str(self.work))
        self.assertEqual([c.args[0][1:] for c in run.call_args_list], [
            ['mcp', 'enable', 'design'], ['mcp', 'enable', 'codegraph']])
        self.assertTrue(all(c.kwargs['cwd'] == str(self.work) for c in run.call_args_list))
        check.assert_not_called()
        self.assertEqual(path.read_text(), original)

    def test_cursor_approval_failure_attempts_remaining_servers_and_reports_failure(self):
        self.write_json(self.work / '.cursor/mcp.json', {'mcpServers': {
            'first': {'command': 'node'}, 'second': {'command': 'node'}}})
        with patch.object(env.subprocess, 'run', side_effect=[
                Mock(returncode=1, stdout='', stderr='secret-error'),
                Mock(returncode=0, stdout='', stderr='')]) as run:
            with self.assertRaisesRegex(RuntimeError, 'Cursor.*first') as error:
                env._prepare_figma_mcp(str(self.work))
        self.assertEqual(run.call_count, 2)
        self.assertNotIn('secret-error', str(error.exception))

    def test_cursor_mixed_services_keep_figma_validation_and_avoid_duplicate_enable(self):
        self.write_json(self.work / '.cursor/mcp.json', {'mcpServers': {
            'other': {'command': 'node'}, 'figma-android-mcp': {
                'command': 'node', 'env': {'FIGMA_API_KEY': 'secret'}}}})
        with patch.object(env, '_check_figma_token', return_value='valid') as check, \
                patch.object(env.subprocess, 'run', return_value=Mock(returncode=0,
                    stdout='get_figma_node get_skill download_figma_images', stderr='')) as run:
            env._prepare_figma_mcp(str(self.work))
        self.assertEqual([c.args[0][1:] for c in run.call_args_list], [
            ['mcp', 'enable', 'other'], ['mcp', 'enable', 'figma-android-mcp'],
            ['mcp', 'list-tools', 'figma-android-mcp']])
        check.assert_called_once()

    def test_cursor_global_figma_still_gets_approved_and_checked(self):
        self.write_json(self.home / '.cursor/mcp.json', {'mcpServers': {
            'figma-android-mcp': {'command': 'node', 'env': {'FIGMA_API_KEY': 'secret'}}}})
        with patch.object(env, '_check_figma_token', return_value='valid'), \
                patch.object(env.subprocess, 'run', return_value=Mock(returncode=0,
                    stdout='get_figma_node get_skill download_figma_images', stderr='')) as run:
            env._prepare_figma_mcp(str(self.work))
        self.assertEqual([c.args[0][1:] for c in run.call_args_list], [
            ['mcp', 'enable', 'figma-android-mcp'], ['mcp', 'list-tools', 'figma-android-mcp']])

    def test_cursor_not_installed_does_not_claim_project_approval(self):
        self.write_json(self.work / '.cursor/mcp.json', {'mcpServers': {'other': {'command': 'node'}}})
        with patch('agents.cursor.build_cursor_base_cmd', side_effect=FileNotFoundError), \
                patch.object(env.subprocess, 'run') as run, patch('builtins.print') as output:
            env._prepare_figma_mcp(str(self.work))
        run.assert_not_called()
        self.assertIn('跳过批准', str(output.call_args_list))
        self.assertNotIn('已批准', str(output.call_args_list))

    def test_http_does_not_mistake_process_env_for_forwarded_token(self):
        self.cursor('')
        os.environ['FIGMA_API_KEY'] = 'environment-secret'
        with patch.object(env.subprocess, 'run', return_value=Mock(returncode=0, stdout='', stderr='')) as run:
            with self.assertRaisesRegex(RuntimeError, 'X-Figma-Token'):
                env._prepare_figma_mcp(str(self.work))
        self.assertEqual([c.args[0][1:] for c in run.call_args_list], [
            ['mcp', 'enable', 'figma-android-mcp']])

    def test_placeholder_token_and_stdio_oauth(self):
        os.environ['FIGMA_TEST_TOKEN'] = 'resolved'
        self.assertEqual(env._figma_credential({'url': 'http://localhost/mcp',
                         'headers': {'X-Figma-Token': '${env:FIGMA_TEST_TOKEN}'}}),
                         ('X-Figma-Token', 'resolved'))
        self.assertEqual(env._figma_credential({'command': 'node', 'env': {
                         'FIGMA_OAUTH_TOKEN': '${FIGMA_TEST_TOKEN}'}}),
                         ('Authorization', 'Bearer resolved'))
        self.assertEqual(env._figma_credential({'url': 'http://localhost/mcp',
                         'env_http_headers': {'X-Figma-Token': 'FIGMA_TEST_TOKEN'}}),
                         ('X-Figma-Token', 'resolved'))

    def test_token_probe_sends_header_and_does_not_log_identity(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(env, 'urlopen', return_value=response) as request:
            self.assertEqual(env._check_figma_token('X-Figma-Token', 'secret'), 'valid')
        self.assertEqual(request.call_args.args[0].full_url, 'https://api.figma.com/v1/me')
        self.assertIn('secret', request.call_args.args[0].headers.values())
        response.read.assert_not_called()

    def test_token_errors_distinguish_auth_scope_quota_and_network(self):
        cases = [(401, b'invalid token', 'invalid'), (403, b'Invalid token', 'invalid'),
                 (403, b'Invalid scope: current_user:read', 'scope'),
                 (429, b'rate limit', 'rate_limited'), (503, b'bad gateway', 'unverified')]
        for status, body, expected in cases:
            with self.subTest(status=status, body=body), patch.object(env, 'urlopen', side_effect=
                    HTTPError('https://api.figma.com/v1/me', status, 'error', {}, io.BytesIO(body))):
                self.assertEqual(env._check_figma_token('X-Figma-Token', 'secret'), expected)
        with patch.object(env, 'urlopen', side_effect=URLError('secret')):
            self.assertEqual(env._check_figma_token('X-Figma-Token', 'secret'), 'unverified')

    def test_invalid_token_fails_without_leaking_it(self):
        self.cursor()
        with patch.object(env, '_check_figma_token', return_value='invalid'), \
                patch('builtins.print') as output, patch.object(env.subprocess, 'run',
                    return_value=Mock(returncode=0, stdout='', stderr='')) as run:
            with self.assertRaisesRegex(RuntimeError, 'Token') as error:
                env._prepare_figma_mcp(str(self.work))
        self.assertNotIn('secret-test-token', str(error.exception) + str(output.call_args_list))
        self.assertEqual([c.args[0][1:] for c in run.call_args_list], [
            ['mcp', 'enable', 'figma-android-mcp']])

    def test_rate_limit_warns_but_still_repairs_cursor_approval(self):
        self.cursor()
        with patch.object(env, '_check_figma_token', return_value='rate_limited'), \
                patch('builtins.print') as output, patch.object(env.subprocess, 'run', return_value=Mock(
                    returncode=0, stdout='get_figma_node get_skill download_figma_images', stderr='')):
            env._prepare_figma_mcp(str(self.work))
        self.assertIn('429', str(output.call_args_list))
        self.assertNotIn('Token 有效', str(output.call_args_list))

    def test_cursor_missing_tools_is_not_success(self):
        self.cursor()
        with patch.object(env, '_check_figma_token', return_value='valid'), \
                patch.object(env.subprocess, 'run', return_value=Mock(returncode=0, stdout='get_skill', stderr='')):
            with self.assertRaisesRegex(RuntimeError, '工具'):
                env._prepare_figma_mcp(str(self.work))

    def test_claude_approves_all_project_mcps_preserving_other_settings(self):
        self.write_json(self.work / '.mcp.json', {'mcpServers': {'figma-android-mcp': {
            'command': 'node', 'env': {'FIGMA_API_KEY': 'secret-test-token'}}}})
        path = self.work / '.claude/settings.local.json'
        self.write_json(path, {'enabledMcpjsonServers': ['existing'],
                             'disabledMcpjsonServers': ['figma-android-mcp', 'other'],
                             'permissions': {'deny': ['Shell(rm)']}})
        with patch.object(env, '_check_figma_token', return_value='valid'), \
                patch.object(env.subprocess, 'run', return_value=Mock(returncode=0, stdout='Status: ✔ Connected', stderr='')):
            env._prepare_figma_mcp(str(self.work))
        saved = json.loads(path.read_text())
        self.assertEqual(saved['enabledMcpjsonServers'], ['existing'])
        self.assertEqual(saved['disabledMcpjsonServers'], [])
        self.assertEqual(saved['permissions'], {'deny': ['Shell(rm)']})
        self.assertTrue(saved['enableAllProjectMcpServers'])

    def test_claude_approval_also_applies_without_figma(self):
        self.write_json(self.work / '.mcp.json', {'mcpServers': {'other': {'command': 'node'}}})
        with patch.object(env.subprocess, 'run') as run:
            env._prepare_figma_mcp(str(self.work))
        self.assertTrue(json.loads((self.work / '.claude/settings.local.json').read_text())[
            'enableAllProjectMcpServers'])
        run.assert_not_called()

    def test_claude_approval_is_idempotent_and_clears_new_rejections(self):
        self.write_json(self.work / '.mcp.json', {'mcpServers': {
            'first': {'command': 'node'}, 'second': {'command': 'node'}}})
        env._approve_claude_project_mcps(str(self.work))
        path = self.work / '.claude/settings.local.json'
        with patch.object(env, '_write_private_config') as write:
            env._approve_claude_project_mcps(str(self.work))
        write.assert_not_called()
        self.write_json(path, {'enableAllProjectMcpServers': True,
                               'disabledMcpjsonServers': ['second']})
        env._approve_claude_project_mcps(str(self.work))
        self.assertEqual(json.loads(path.read_text())['disabledMcpjsonServers'], [])

    def test_client_failure_and_timeout_never_expose_output(self):
        failures = [Mock(returncode=1, stdout='secret-token', stderr='secret-token'),
                    subprocess.TimeoutExpired(['client'], 45, output='secret-token')]
        for failure in failures:
            kwargs = {'side_effect': failure} if isinstance(failure, Exception) else {'return_value': failure}
            with self.subTest(failure=type(failure).__name__), patch.object(env.subprocess, 'run', **kwargs):
                with self.assertRaises(RuntimeError) as error:
                    env._mcp_command(['client'], str(self.work))
                self.assertNotIn('secret-token', str(error.exception))

    def test_codex_trust_changes_only_current_project_and_is_idempotent(self):
        path = self.home / '.codex/config.toml'
        path.parent.mkdir(parents=True)
        current = str(self.work.resolve())
        path.write_text('model = "unchanged"\n\n[projects."/other"]\ntrust_level = "untrusted"\n'
                        f'\n[projects.{json.dumps(current)}]\ntrust_level = "untrusted"\n')
        env._trust_codex_project(path, str(self.work))
        data = env._mcp_config(path)
        self.assertEqual(data['projects'][current]['trust_level'], 'trusted')
        self.assertEqual(data['projects']['/other']['trust_level'], 'untrusted')
        self.assertEqual(data['model'], 'unchanged')
        before = path.stat().st_mtime_ns
        env._trust_codex_project(path, str(self.work))
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_claude_health_failure_not_hidden_by_exit_zero(self):
        self.write_json(self.home / '.claude.json', {'mcpServers': {'figma-android-mcp': {
            'command': 'node', 'env': {'FIGMA_API_KEY': 'secret'}}}})
        with patch.object(env, '_check_figma_token', return_value='valid'), \
                patch.object(env.subprocess, 'run', return_value=Mock(returncode=0,
                    stdout='Status: ⏸ Pending approval', stderr='')):
            with self.assertRaisesRegex(RuntimeError, 'Claude'):
                env._prepare_figma_mcp(str(self.work))

    def test_codex_uses_effective_config_and_rejects_disabled_tools(self):
        path = self.home / '.codex/config.toml'
        path.parent.mkdir(parents=True)
        path.write_text('[mcp_servers.figma-android-mcp]\ncommand="node"\n')
        data = {'enabled': True, 'transport': {'type': 'stdio', 'command': 'node',
                'env': {'FIGMA_API_KEY': 'secret'}}, 'disabled_tools': ['get_figma_node']}
        with patch.object(env.subprocess, 'run', return_value=Mock(returncode=0, stdout=json.dumps(data), stderr='')):
            with self.assertRaisesRegex(RuntimeError, 'Codex.*get_figma_node'):
                env._prepare_figma_mcp(str(self.work))

    def test_shared_token_checked_once_across_clients(self):
        self.cursor('same-secret')
        self.write_json(self.home / '.claude.json', {'mcpServers': {'figma-android-mcp': {
            'command': 'node', 'env': {'FIGMA_API_KEY': 'same-secret'}}}})
        with patch.object(env, '_check_figma_token', return_value='valid') as check, \
                patch.object(env.subprocess, 'run', return_value=Mock(returncode=0,
                    stdout='Status: ✓ Connected\nget_figma_node get_skill download_figma_images', stderr='')):
            env._prepare_figma_mcp(str(self.work))
        check.assert_called_once()


if __name__ == '__main__':
    unittest.main()
