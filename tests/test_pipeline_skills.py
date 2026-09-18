import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pipeline_skills as ps


class PipelineSkillsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.work = self.root / '业务 project'
        self.work.mkdir()
        self.name = 'panda-pipeline-sample'
        self.skill = self.source / 'skills' / self.name
        self.skill.mkdir(parents=True)
        (self.skill / 'SKILL.md').write_text(
            f'---\nname: {self.name}\ndescription: Sample\n---\nRead [details](references/details.md).\n')
        (self.skill / 'references').mkdir()
        (self.skill / 'references/details.md').write_text('version A')
        self.prompt = self.source / 'system-prompt/developer.md'
        self.prompt.parent.mkdir()
        self.prompt.write_text('role A')
        self.enterContext(patch.object(ps, 'SOURCE_ROOT', self.source))
        self.enterContext(patch.dict(ps._PREPARED_ROOTS, {}, clear=True))

    def install(self):
        return ps.prepare_pipeline_skills(str(self.work))

    def test_installs_complete_bundle_and_native_entries(self):
        bundle = self.install()
        self.assertEqual(bundle, self.source.resolve() / 'temp-prompt-skills')
        self.assertFalse((self.work / '.panda-pipeline/skill-bundles').exists())
        self.assertEqual((bundle / 'skills' / self.name / 'references/details.md').read_text(), 'version A')
        for location in ('.agents/skills', '.claude/skills'):
            self.assertEqual((self.work / location / self.name / 'references/details.md').read_text(), 'version A')
        self.assertEqual(ps.role_prompt_text(str(self.work), self.prompt), 'role A')
        self.assertIn(str(self.work / '.agents/skills'), ps.skill_context(str(self.work)))

    def test_skill_context_points_to_installed_copy_for_each_backend(self):
        bundle = self.install()
        for backend in ('codex', 'cursor', 'claude', 'dsh', 'opencode'):
            with self.subTest(backend=backend):
                location = '.claude/skills' if backend == 'claude' else '.agents/skills'
                installed = self.work / location
                context = ps.skill_context(str(self.work), backend)
                self.assertIn(str(installed), context)
                self.assertIn('项目已安装 skills 目录', context)
                self.assertNotIn(str(bundle), context)
                self.assertNotIn('temp-prompt-skills', context)
                self.assertTrue((installed / self.name / 'SKILL.md').is_file())

    def test_command_templates_render_separately_and_overwrite_on_startup(self):
        command = self.source / 'break-command/memory_curation.md'
        command.parent.mkdir()
        command.write_text('__PANDA_WORK_DIR__\n{opening}\ncommand A')
        # Direct calls without environment preparation still render runtime tokens.
        self.assertEqual(ps.command_template_text(str(self.work), command),
                         f'{self.work.resolve()}\n{{opening}}\ncommand A')
        bundle = self.install()
        rendered = bundle / 'commands/break-command/memory_curation.md'
        self.assertFalse((bundle / 'prompts/break-command').exists())
        self.assertEqual(rendered.read_text(), f'{self.work.resolve()}\n{{opening}}\ncommand A')
        command.write_text('{opening}\ncommand B')
        self.assertIn('command A', ps.command_template_text(str(self.work), command))
        self.install()
        self.assertEqual(ps.command_template_text(str(self.work), command), '{opening}\ncommand B')
        rendered.unlink()
        with self.assertRaisesRegex(RuntimeError, '本轮命令模板缺失'):
            ps.command_template_text(str(self.work), command)

    def test_updates_overwrite_same_paths_and_remove_stale_files(self):
        first = self.install()
        (first / 'skills' / self.name / 'stale.txt').write_text('old')
        native = self.work / '.agents/skills' / self.name
        (native / 'stale.txt').write_text('old')
        (self.skill / 'references/details.md').write_text('updated')
        self.prompt.write_text('updated role')
        second = self.install()
        self.assertEqual(first, second)
        self.assertEqual((first / 'skills' / self.name / 'references/details.md').read_text(), 'updated')
        self.assertEqual((native / 'references/details.md').read_text(), 'updated')
        self.assertFalse((first / 'skills' / self.name / 'stale.txt').exists())
        self.assertFalse((native / 'stale.txt').exists())
        self.assertEqual(ps.role_prompt_text(str(self.work), self.prompt), 'updated role')
        self.assertFalse((self.work / '.panda-pipeline/skills-install.json').exists())

    def test_same_named_installation_is_overwritten_without_ownership_records(self):
        path = self.work / '.claude/skills' / self.name
        path.mkdir(parents=True)
        (path / 'SKILL.md').write_text('previous installation')
        self.install()
        self.assertEqual((path / 'SKILL.md').read_text(), (self.skill / 'SKILL.md').read_text())
        (path / 'SKILL.md').write_text('manual edit')
        self.install()
        self.assertEqual((path / 'SKILL.md').read_text(), (self.skill / 'SKILL.md').read_text())

    def test_legacy_version_directories_are_removed(self):
        root = self.source / 'temp-prompt-skills'
        legacy = root / ('a' * 64)
        legacy.mkdir(parents=True)
        (legacy / 'old.md').write_text('old')
        self.install()
        self.assertFalse(legacy.exists())
        self.assertTrue((root / 'prompts/system-prompt/developer.md').is_file())
        self.assertNotIn('版本', ps.skill_context(str(self.work)))
        self.assertNotIn('重新读取', ps.skill_context(str(self.work)))

    def test_unrelated_skills_are_untouched(self):
        path = self.work / '.agents/skills/panda-pipeline-user-owned'
        path.mkdir(parents=True)
        (path / 'SKILL.md').write_text('user owned')
        self.install()
        self.assertEqual((path / 'SKILL.md').read_text(), 'user owned')

    def test_installed_files_are_locally_ignored_without_changing_project_gitignore(self):
        subprocess.run(['git', 'init', '-q', str(self.work)], check=True, capture_output=True)
        ignore = self.work / '.gitignore'
        ignore.write_text('user-rule\n')
        self.install()
        self.install()
        self.assertEqual(ignore.read_text(), 'user-rule\n')
        patterns = (self.work / '.git/info/exclude').read_text()
        self.assertEqual(patterns.count('/.agents/skills/panda-pipeline-*/'), 1)
        result = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=all'],
                                cwd=self.work, check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), '?? .gitignore')

    def test_missing_reference_is_rejected_before_install(self):
        (self.skill / 'references/details.md').unlink()
        with self.assertRaisesRegex(RuntimeError, '引用|reference'):
            self.install()
        self.assertFalse((self.work / '.agents/skills' / self.name).exists())

    def test_wrong_name_is_rejected(self):
        (self.skill / 'SKILL.md').write_text('---\nname: other\ndescription: bad\n---\n')
        with self.assertRaisesRegex(RuntimeError, 'name|名称'):
            self.install()

    def test_prompt_only_change_overwrites_same_file(self):
        first = self.install()
        self.prompt.write_text('role B')
        self.assertEqual(first, self.install())
        self.assertEqual(ps.role_prompt_text(str(self.work), self.prompt), 'role B')

    def test_without_install_has_no_context_and_uses_source_prompt(self):
        self.assertEqual(ps.skill_context(str(self.work)), '')
        self.assertEqual(ps.role_prompt_text(str(self.work), self.prompt), 'role A')

    def test_renders_skills_and_prompts_from_same_context_and_preserves_templates(self):
        shared = 'cwd=__PANDA_WORK_DIR__ cmd=__PANDA_STATIC_SCAN_COMMAND__ skills=__PANDA_SKILLS_ROOT__'
        self.prompt.write_text(shared + ' {requirement_id}')
        (self.skill / 'references/details.md').write_text(shared)
        bundle = self.install()
        prompt = ps.role_prompt_text(str(self.work), self.prompt)
        detail = (bundle / 'skills' / self.name / 'references/details.md').read_text()
        self.assertEqual(prompt.removesuffix(' {requirement_id}'), detail)
        self.assertIn(str(self.work), prompt)
        self.assertNotIn('__PANDA_', prompt)
        self.assertIn('{requirement_id}', prompt)
        self.assertIn(str(self.work / '.agents/skills'), detail)
        self.assertNotIn('temp-prompt-skills', detail)

    def test_unknown_render_token_is_rejected_before_install(self):
        self.prompt.write_text('__PANDA_MISSPELLED_VALUE__')
        with self.assertRaisesRegex(RuntimeError, '渲染|占位符'):
            self.install()

    def test_bundles_script_dependencies_without_copying_source_credentials(self):
        (self.skill / 'scripts').mkdir()
        (self.skill / 'scripts/tool.py').write_text('print("hello")')
        bundle = self.install()
        self.assertEqual((bundle / 'skills' / self.name / 'scripts/tool.py').read_text(), 'print("hello")')
        self.assertFalse((bundle / 'config/config.json').exists())

    def test_external_bundle_mapping_is_rejected(self):
        (self.skill / 'bundle.json').write_text(json.dumps({'files': {'scripts/tool.py': '../secret'}}))
        with self.assertRaisesRegex(RuntimeError, 'bundle.json'):
            self.install()

    def test_executing_bundled_script_does_not_break_restart_integrity(self):
        (self.skill / 'scripts').mkdir()
        (self.skill / 'scripts/tool.py').write_text('import helper\nprint(helper.VALUE)')
        (self.skill / 'scripts/helper.py').write_text('VALUE = 42')
        bundle = self.install()
        for base in (bundle / 'skills', self.work / '.agents/skills'):
            result = subprocess.run([sys.executable, str(base / self.name / 'scripts/tool.py')],
                                    cwd=self.work, capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.strip(), '42')
        self.assertEqual(self.install(), bundle)

    def test_resumed_agent_receives_fixed_role_and_skill_paths_and_validates_original_task(self):
        from agents import Agent
        from agents._result import AgentRunResult
        from task_protocol import TaskMessage

        self.prompt.write_text('Use `panda-pipeline-sample` for this task.')
        first = self.install()
        agent = Agent('test', self.prompt.name, str(self.work),
                      prompt_dir=str(self.prompt.parent), session_id='existing-session')
        agent.agent_impl = Mock()
        agent.agent_impl.run.return_value = AgentRunResult(
            text='FINAL_ANSWER\n{"status":"completed","summary":"ok","outputs":{}}',
            session_id='existing-session', returncode=0)
        task = TaskMessage('test', [], [], '', {'completed'}, root=self.work)
        with patch('agents.agent.validate_receipt', return_value='validated') as validate:
            self.assertEqual(agent.send_message(task), 'validated')
        args = agent.agent_impl.run.call_args.kwargs
        self.assertEqual(args['session_id'], 'existing-session')
        self.assertIn(str(self.work / '.claude/skills'), args['message'])
        self.assertNotIn(str(first), args['message'])
        self.assertTrue(args['message'].endswith(str(task)))
        self.assertNotIn('版本', args['message'])
        self.assertNotIn('重新读取', args['message'])
        self.assertEqual(agent.system_prompt.path.read_text(), agent.system_prompt)
        self.assertIs(validate.call_args.args[1], task)
        self.assertEqual(agent.agent_impl.max_retries, 0)

    def test_missing_frozen_prompt_cannot_silently_drop_role_rules(self):
        from agents import Agent

        bundle = self.install()
        (bundle / 'prompts/system-prompt/developer.md').unlink()
        with self.assertRaisesRegex(RuntimeError, 'prompt 缺失'):
            Agent('test', self.prompt.name, str(self.work), prompt_dir=str(self.prompt.parent))

    def test_real_packages_render_and_run_without_source_repository_dependencies(self):
        repository = Path(__file__).resolve().parents[1]
        source = self.root / 'complete source'
        for directory in ('skills', 'system-prompt', 'break-system-prompt',
                          'system-command', 'break-command'):
            shutil.copytree(repository / directory, source / directory)
        with patch.object(ps, 'SOURCE_ROOT', source):
            bundle = self.install()
            for relative in ('break-command/memory_curation.md',
                             'break-command/requirement_summary.md',
                             'system-command/memory_curation.md'):
                self.assertEqual((bundle / 'commands' / relative).read_bytes(),
                                 (source / relative).read_bytes())
                self.assertNotIn('FINAL_ANSWER', ps.command_template_text(str(self.work), source / relative))
            for family in ('system-prompt', 'break-system-prompt'):
                for filename in ('memory_curation.md', 'requirement_summary.md'):
                    self.assertFalse((bundle / 'prompts' / family / filename).exists())
            for path in bundle.rglob('*.md'):
                self.assertNotRegex(path.read_text(), r'__PANDA_[A-Z_]+__|__ANDROID_EMULATOR_COMMAND__')
            scripts = {
                'ui-assets': 'figma_asset_audit.py',
                'static-analysis': 'static_scan.py',
                'android-device-validation': 'android_emulator.py',
            }
            for base in (bundle / 'skills', self.work / '.agents/skills', self.work / '.claude/skills'):
                architecture = base / 'panda-pipeline-architecture'
                for relative in ('SKILL.md', 'references/shared-context.md',
                                 'references/planning.md'):
                    self.assertEqual((architecture / relative).read_bytes(),
                                     (source / 'skills' / architecture.name / relative).read_bytes())
                fidelity = base / 'panda-pipeline-ui-fidelity'
                for relative in ('SKILL.md', 'references/sources-and-boundaries.md',
                                 'references/gaps.md', 'references/breakdown.md',
                                 'references/analysis.md', 'references/development.md',
                                 'references/review.md', 'references/evidence.md',
                                 'references/summary.md'):
                    self.assertEqual((fidelity / relative).read_bytes(),
                                     (source / 'skills' / fidelity.name / relative).read_bytes())
                asset_handoff = 'panda-pipeline-ui-assets/references/handoff.md'
                self.assertEqual((base / asset_handoff).read_bytes(),
                                 (source / 'skills' / asset_handoff).read_bytes())
                swagger = base / 'panda-pipeline-swagger-contract'
                for relative in ('SKILL.md', 'references/analysis.md',
                                 'references/development.md', 'references/review.md'):
                    self.assertEqual((swagger / relative).read_bytes(),
                                     (source / 'skills' / swagger.name / relative).read_bytes())
                scanner = base / 'panda-pipeline-static-analysis/scripts'
                self.assertFalse((scanner / 'config.py').exists())
                for filename in ('detekt.yml', '.swiftlint.yml', 'checkstyle-config.xml',
                                 'pmd-java-ruleset.xml', 'scan_config.json', 'eslint.config.mjs'):
                    relative = Path('panda-pipeline-static-analysis/scripts/static-analysis') / filename
                    self.assertEqual((base / relative).read_bytes(),
                                     (source / 'skills' / relative).read_bytes())
                for name, script in scripts.items():
                    skill_dir = base / f'panda-pipeline-{name}'
                    entry = (skill_dir / 'SKILL.md').read_text()
                    command = shlex.split(re.search(r'```bash\n([^\n]+)', entry)[1])[:2]
                    self.assertEqual(command, ['python3', f'scripts/{script}'])
                    result = subprocess.run(command + ['--help'], cwd=skill_dir,
                                            capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stderr)
            scan = bundle / 'skills/panda-pipeline-static-analysis/scripts/static_scan.py'
            report = self.work / 'scan.md'
            result = subprocess.run(['python3', 'scripts/static_scan.py', '--work-dir', str(self.work),
                                     '--report', str(report)], cwd=scan.parent.parent,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('未发现可静态扫描', report.read_text())
            audit = bundle / 'skills/panda-pipeline-ui-assets/scripts/figma_asset_audit.py'
            report = self.work / 'audit.json'
            result = subprocess.run(['python3', 'scripts/figma_asset_audit.py', '--requirements-dir',
                                     str(self.work / 'absent'), '--report', str(report)],
                                    cwd=audit.parent.parent, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(json.loads(report.read_text())['status'], 'error')
            self.assertEqual(self.install(), bundle)


if __name__ == '__main__':
    unittest.main()
