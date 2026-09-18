import unittest
from pathlib import Path

from tests.test_figma_asset_prompts import prompt_contract


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/panda-pipeline-architecture'


class ArchitectureSkillTests(unittest.TestCase):
    def test_shared_context_and_architecture_templates_have_one_skill_entry(self):
        entry = (SKILL / 'SKILL.md').read_text()
        self.assertIn('(references/shared-context.md)', entry)
        self.assertIn('(references/planning.md)', entry)
        schema = (SKILL / 'references/shared-context.md').read_text()
        for term in ('本批次临时公共信息', '来源', '公共能力与复用边界',
                     'planned', 'unverified', 'verified', '物料入口',
                     'develop_urge.md', '相对 shared_context.md', '环境', '凭据'):
            self.assertIn(term, schema)
        self.assertIn('魔法值公共目录', (SKILL / 'references/planning.md').read_text())

    def test_roles_explicitly_load_schema_without_repeating_its_template(self):
        paths = [* (ROOT / 'break-system-prompt').glob('*.md'),
                 * (ROOT / 'system-prompt').glob('*.md')]
        roles = [p for p in paths if '当前角色模式为' in p.read_text()]
        self.assertEqual(len(roles), 10)
        for path in roles:
            text = path.read_text()
            self.assertIn('`panda-pipeline-architecture`', text, path.name)
            self.assertNotIn('能力 ID | 能力与提供方需求 | 实现入口', text, path.name)
        breaker = (ROOT / 'break-system-prompt/requirement_breaker.md').read_text()
        self.assertNotIn('### 架构规划必须包含的内容', breaker)
        self.assertIn('取得用户确认后再执行该变更', breaker)
        self.assertIn('公共能力与复用边界', prompt_contract(ROOT / 'break-system-prompt/requirement_breaker.md'))

    def test_schema_reading_does_not_authorize_global_rewrites(self):
        entry = (SKILL / 'SKILL.md').read_text()
        for term in ('requirements-review', 'code-review', 'summary', '只读',
                     '不扩大', '相关条目', '不要求'):
            self.assertIn(term, entry)
        summary = (ROOT / 'break-command/requirement_summary.md').read_text()
        self.assertIn('`panda-pipeline-architecture`', summary)
        self.assertIn('不修改共享表', summary)

    def test_scheduler_passes_output_and_skill_instead_of_schema_fields(self):
        from break_pipeline import BreakPipeline
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            pipeline = BreakPipeline(directory)
            text = pipeline._breakdown_instruction('test')
        self.assertIn('shared_context.md', text)
        self.assertIn('panda-pipeline-architecture', text)
        self.assertNotIn('明确提供方、入口、已有/未实现范围', text)
        self.assertNotIn('schema_version: 3', text)


if __name__ == '__main__':
    unittest.main()
