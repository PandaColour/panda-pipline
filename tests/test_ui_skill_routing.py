import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/panda-pipeline-ui-fidelity'
MODES = {
    'breakdown': 'breakdown.md',
    'breakdown-review': 'breakdown.md',
    'analysis': 'analysis.md',
    'requirements-review': 'analysis.md',
    'development': 'development.md',
    'code-review': 'review.md',
    'summary': 'summary.md',
}


class UISkillRoutingTests(unittest.TestCase):
    def test_each_mode_has_an_explicit_readable_reference(self):
        entry = (SKILL / 'SKILL.md').read_text()
        for mode, filename in MODES.items():
            with self.subTest(mode=mode):
                rows = [line for line in entry.splitlines() if f'`{mode}`' in line]
                self.assertTrue(any(f'(references/{filename})' in row for row in rows))
                self.assertTrue((SKILL / 'references' / filename).is_file())

    def test_ui_roles_trigger_the_skill_without_carrying_the_extracted_chapters(self):
        roles = []
        for directory in ('system-prompt', 'break-system-prompt'):
            for path in (ROOT / directory).glob('*.md'):
                text = path.read_text()
                if '当前角色模式为' not in text:
                    continue
                roles.append(path)
                self.assertIn('`panda-pipeline-ui-fidelity`', text, path.name)
                self.assertIn('## UI 职责与交付', text, path.name)
                self.assertIn('项目已安装 skills 目录', text, path.name)
                for heading in ('UI 拆分交接', 'UI 资源缺口与验收结论',
                                'UI 设计来源优先级与验收边界', 'Figma 资源筛选与交接协议'):
                    self.assertNotIn(f'## {heading}\n', text, path.name)
        self.assertEqual(len(roles), 10)

    def test_shared_rules_are_available_without_reading_role_prompts(self):
        entry = (SKILL / 'SKILL.md').read_text()
        self.assertIn('(references/sources-and-boundaries.md)', entry)
        common = (SKILL / 'references/sources-and-boundaries.md').read_text()
        for term in ('以远程 Figma 为准', '仅对失败节点降级', '本地', '安全区',
                     '字重', '已接受差异', 'Mock', 'density'):
            self.assertIn(term, common)
        self.assertNotIn('仍以角色 prompt', entry)

    def test_summary_uses_existing_evidence_and_installed_skill(self):
        prompt = (ROOT / 'break-command/requirement_summary.md').read_text()
        self.assertIn('`panda-pipeline-ui-fidelity`', prompt)
        self.assertIn('`summary`', prompt)
        self.assertIn('项目已安装 skills 目录', prompt)
        reference = (SKILL / 'references/summary.md').read_text()
        for term in ('不启动设备', '已有', '已接受差异', '未验证', '失效'):
            self.assertIn(term, reference)
        for relative in ('system-command/memory_curation.md',
                         'break-command/memory_curation.md',
                         'break-system-prompt/index_normalizer.md'):
            self.assertNotIn('`panda-pipeline-ui-fidelity`', (ROOT / relative).read_text())

    def test_references_are_closed_and_have_no_render_directory_dependency(self):
        for path in SKILL.rglob('*.md'):
            text = path.read_text()
            self.assertNotIn('temp-prompt', text, str(path))
            for target in re.findall(r'\]\(([^)]+\.md)\)', text):
                self.assertTrue((path.parent / target).resolve().is_file(), (path, target))


if __name__ == '__main__':
    unittest.main()
