import json
import re
import tempfile
import unittest
from pathlib import Path

from task_protocol import TaskMessage, parse_final_answer, validate_receipt


ROOT = Path(__file__).resolve().parents[1]
ROLES = {
    'break-system-prompt/requirement_breaker.md': ('breakdown', {'completed', 'blocked'}),
    'break-system-prompt/requirement_break_reviewer.md': ('breakdown_review', {'approved', 'changes_requested', 'blocked'}),
    'break-system-prompt/item_requirements_analyst.md': ('analysis', {'completed'}),
    'break-system-prompt/item_requirements_reviewer.md': ('requirements_review', {'approved', 'changes_requested'}),
    'break-system-prompt/item_developer.md': ('development', {'completed'}),
    'break-system-prompt/item_code_reviewer.md': ('code_review', {'approved', 'changes_requested', 'requirement_change'}),
    'break-system-prompt/index_normalizer.md': ('normalize', {'completed'}),
    'system-prompt/requirements_analyst.md': ('analysis', {'completed', 'blocked'}),
    'system-prompt/requirements_reviewer.md': ('requirements_review', {'approved', 'changes_requested'}),
    'system-prompt/code_developer.md': ('development', {'completed'}),
    'system-prompt/code_reviewer.md': ('code_review', {'approved', 'changes_requested'}),
}


class FinalReceiptPromptTests(unittest.TestCase):
    def test_each_role_enumerates_and_demonstrates_all_its_states(self):
        for relative, (primary, statuses) in ROLES.items():
            with self.subTest(prompt=relative), tempfile.TemporaryDirectory() as root:
                text = (ROOT / relative).read_text()
                before, final = text.split('## FINAL_ANSWER（最终回执）', 1)
                self.assertNotRegex(final, r'(?m)^## ', relative)
                self.assertIn('allowed_statuses', final)
                self.assertIn('### status 枚举', final)
                rows = set(re.findall(r'^\| `([a-z_]+)` \|', final, re.M))
                self.assertEqual(rows, statuses)
                self.assertNotRegex(before, r'"status"\s*:\s*"(?:completed|approved|changes_requested|requirement_change|blocked)"')
                examples = re.findall(r'#### (\w+) / (\w+)\n.*?```text\n(FINAL_ANSWER\n[^`]+)```', final, re.S)
                self.assertTrue(examples, relative)
                primary_states = {status for stage, status, _ in examples if stage == primary}
                self.assertEqual(primary_states, statuses, relative)
                for stage, status, reply in examples:
                    result = parse_final_answer(reply)
                    self.assertEqual(result['status'], status)
                    if stage != primary:
                        self.assertIn(stage, {'memory_analysis', 'memory_development', 'summary'})
                        self.assertEqual(status, 'completed')
                    filenames = {
                        'breakdown': ['index.md'], 'breakdown_review': ['split_review_report.json'],
                        'analysis': ['user_requirements.md' if relative.startswith('system-') else 'requirements_analysis.md'],
                        'development': ['develop_report.md'], 'requirements_review': ['requirement_review.md'],
                        'code_review': ['code_review.md', 'test_report.md'], 'normalize': ['execution_plan.json'],
                        'memory_analysis': ['memory_analysis_report.md'], 'memory_development': ['memory_report.md'],
                        'summary': ['requirement_summary.md'],
                    }[stage]
                    base = 'requirements' if stage in {'breakdown', 'breakdown_review', 'normalize', 'summary'} else (
                        'requirements/R-001-main' if relative.startswith('system-') else 'requirements/R-001-example')
                    outputs = [f'{base}/{name}' for name in filenames]
                    blocker = f'{base}/resource_blocker.json'
                    optional = [blocker] if status == 'blocked' else []
                    for output in result['outputs'].values():
                        path = Path(root) / output
                        path.parent.mkdir(parents=True, exist_ok=True)
                        if path.name == 'resource_blocker.json':
                            report = next(json.loads(block) for block in re.findall(r'```json\n(.*?)\n```', final, re.S)
                                          if '"kind"' in block)
                            path.write_text(json.dumps(report))
                        else:
                            path.write_text('example output')
                    task = TaskMessage('example', [], outputs, '', {status}, root=root, optional_outputs=optional)
                    validate_receipt(reply, task, root)

    def test_role_and_command_templates_are_separate(self):
        from break_pipeline import BreakPipeline
        from pipeline import Pipeline
        role_paths = {str(p.relative_to(ROOT)) for folder in ('system-prompt', 'break-system-prompt')
                      for p in (ROOT / folder).glob('*.md')}
        self.assertEqual(role_paths, set(ROLES))
        for cls, filenames in ((BreakPipeline, ('memory_curation.md', 'requirement_summary.md')),
                               (Pipeline, ('memory_curation.md',))):
            with tempfile.TemporaryDirectory() as work:
                pipeline = cls(work)
                self.assertNotEqual(pipeline.command_dir, pipeline.prompt_dir)
                for filename in filenames:
                    with self.subTest(pipeline=cls.__name__, command=filename):
                        source = Path(pipeline.command_dir, filename).read_text()
                        self.assertNotIn('FINAL_ANSWER', source)
                        self.assertNotIn('## 每轮任务与文档交接', source)
                        command = pipeline._render_command(
                            filename, opening='开始整理', read_instruction='读取报告',
                            curation_scope='整理事实', execution_plan_file=pipeline.execution_plan_file,
                            closing_instruction='写入报告')
                        self.assertIn(pipeline.execution_plan_file, command)
                        self.assertNotIn('{opening}', command)
                        self.assertNotIn('{closing_instruction}', command)
                        with self.assertRaisesRegex(ValueError, 'Command template .* missing placeholder'):
                            pipeline._render_command(filename)

    def test_protocol_and_receipt_only_correction_remain_explicit(self):
        for relative in ROLES:
            text = (ROOT / relative).read_text().split('## FINAL_ANSWER（最终回执）', 1)[1]
            for term in ('2048', 'summary', 'outputs', 'approval_token 仅为可选补充说明',
                         '回执补正', '不重做业务任务', '回执后立即结束本轮', 'optional_outputs'):
                self.assertIn(term, text, relative)


if __name__ == '__main__':
    unittest.main()
