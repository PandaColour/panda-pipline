from handoff_helpers import read_handoff
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from break_pipeline import BreakPipeline
from review_context import CodeReviewContext


REJECT = 'FINAL_ANSWER ' + json.dumps({
    'status': 'changes_requested', 'approval_token': '', 'summary': '修复登录',
    'issues': [{'id': 'CR-001', 'ac_ids': ['R-001-AC-01'],
                'problem': '点击登录无响应', 'severity': 'fatal'}],
}, ensure_ascii=False)


class IncrementalReviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.pipeline = BreakPipeline(temp.name, skip_human=True)
        root = Path(self.pipeline.requirements_dir)
        root.mkdir()
        Path(self.pipeline.requirements_index_file).write_text('index', encoding='utf-8')
        target = root / 'R-001' / 'user_requirements.md'
        target.parent.mkdir()
        target.write_text('必须 R-001-AC-01 登录；必须 R-001-AC-02 退出', encoding='utf-8')
        self.pipeline.execution_plan.write(dict(
            demand=dict(id='D-001', status='开发中', source='test'),
            source_index_sha256=self.pipeline.execution_plan.index_hash(),
            items=[dict(order=1, id='R-001', name='login', status='待开发',
                        dependencies=[], requirements_file='R-001/user_requirements.md',
                        acceptance_summary='登录、退出')]))
        self.paths = self.pipeline._item_paths(self.item())
        self.dev, self.reviewer = MagicMock(), MagicMock()
        self.dev.send_message.return_value = '实现完成'
        self.reviewer.send_message.return_value = 'FINAL_ANSWER {"status": "approved", "approval_token": "任务完成", "summary": "任务完成", "outputs": {}}'

    def item(self):
        return self.pipeline._load_items()[0]

    def write(self, key, text):
        Path(self.paths[key]).write_text(text, encoding='utf-8')

    def reject(self, _message):
        self.write('test', 'R-001-AC-02 已通过，证据 logout.log，构建 abc')
        self.write('code_review', 'CR-001 登录无响应；AC-02 通过')
        return REJECT

    def fix(self, _message):
        self.write('develop', 'CR-001：Login.kt onClick 接线；影响 AC-01；login.log 退出码 0')
        return '已修复 CR-001，修改 Login.kt，退出流程未变'

    def test_first_review_is_full_and_device_lifecycle_belongs_to_developer(self):
        self.pipeline._run_item(self.item(), self.dev, self.reviewer)
        message = read_handoff(self.reviewer.send_message.call_args.args[0])
        self.assertIn('首审', message)
        self.assertIn('Reviewer 不得接手启停设备', message)
        self.assertNotIn('否则检查/启动 AVD', message)
        self.assertIn('修复改动清单', self.dev.send_message.call_args.args[0])
        self.assertNotIn('仅对既有问题', message)

    def test_rereview_receives_issues_changes_evidence_and_all_required_acs(self):
        messages = []

        def review(message):
            messages.append(message)
            return self.reject(message) if len(messages) == 1 else 'FINAL_ANSWER {"status": "approved", "approval_token": "任务完成", "summary": "任务完成", "outputs": {}}'

        self.reviewer.send_message.side_effect = review
        self.dev.send_message.side_effect = lambda msg: self.fix(msg) if 'CR-001' in read_handoff(msg) else '初次实现'
        self.pipeline._run_item(self.item(), self.dev, self.reviewer)
        second = read_handoff(messages[1])
        for expected in ['增量复审', 'CR-001', 'Login.kt', 'login.log', 'logout.log',
                         'R-001-AC-02', '直接回归', 'regression_of']:
            self.assertIn(expected, second)
        self.assertIsNone(self.pipeline.execution_plan.get_pending_feedback('R-001'))

    def interrupt_after_review(self):
        self.reviewer.send_message.side_effect = self.reject
        self.dev.send_message.side_effect = ['实现完成', RuntimeError('interrupted')]
        with self.assertRaisesRegex(RuntimeError, 'interrupted'):
            self.pipeline._run_item(self.item(), self.dev, self.reviewer)

    def test_restart_keeps_review_snapshot_even_if_reports_are_overwritten(self):
        self.interrupt_after_review()
        self.write('test', '开发者覆盖的当前自测')
        self.write('code_review', '')
        restarted = BreakPipeline(self.pipeline.work_dir, skip_human=True)
        self.dev.send_message.side_effect = self.fix
        self.reviewer.send_message.side_effect = None
        restarted._run_item(restarted._load_items()[0], self.dev, self.reviewer)
        message = read_handoff(self.reviewer.send_message.call_args.args[0])
        self.assertIn('增量复审', message)
        self.assertIn('CR-001', message)
        self.assertIn('logout.log', message)
        self.assertIn('Login.kt', message)

    def test_requirement_change_starts_full_review_with_new_acceptance(self):
        self.interrupt_after_review()
        self.write('requirements', '必须 R-001-AC-03 注册')
        self.dev.send_message.side_effect = None
        self.reviewer.send_message.side_effect = None
        self.pipeline._run_item(self.item(), self.dev, self.reviewer)
        message = read_handoff(self.reviewer.send_message.call_args.args[0])
        self.assertIn('首审', message)
        self.assertIn('需求基线已变化', message)
        self.assertIn('R-001-AC-03', message)

    def test_human_feedback_is_in_next_review_context(self):
        self.dev.send_message.side_effect = lambda msg: self.fix(msg)
        with patch.object(self.pipeline, '_human_gate', side_effect=['请修正登录按钮颜色', None]):
            self.pipeline._run_item(self.item(), self.dev, self.reviewer)
        message = read_handoff(self.reviewer.send_message.call_args.args[0])
        self.assertIn('增量复审', message)
        self.assertIn('请修正登录按钮颜色', message)

    def test_legacy_resume_uses_existing_reports_and_discloses_missing_snapshot(self):
        self.pipeline._set_status('R-001', '代码评审中')
        self.pipeline.execution_plan.increment_stage_attempt('code_review', 'R-001')
        self.reject('')
        self.pipeline._run_item(self.item(), self.dev, self.reviewer)
        message = read_handoff(self.reviewer.send_message.call_args.args[0])
        self.assertIn('增量复审', message)
        self.assertIn('历史快照缺失', message)
        self.assertIn('CR-001', message)
        self.assertIn('logout.log', message)
        self.dev.send_message.assert_not_called()

    def test_restart_at_review_preserves_completed_fix_without_rerunning_developer(self):
        self.reviewer.send_message.side_effect = [REJECT, KeyboardInterrupt('interrupted')]
        self.dev.send_message.side_effect = self.fix
        with self.assertRaisesRegex(KeyboardInterrupt, 'interrupted'):
            self.pipeline._run_item(self.item(), self.dev, self.reviewer)
        self.assertIsNone(self.pipeline.execution_plan.get_pending_feedback('R-001'))
        restarted = BreakPipeline(self.pipeline.work_dir, skip_human=True)
        self.dev.reset_mock()
        self.reviewer.send_message.side_effect = None
        restarted._run_item(restarted._load_items()[0], self.dev, self.reviewer)
        self.dev.send_message.assert_not_called()
        message = read_handoff(self.reviewer.send_message.call_args.args[0])
        self.assertIn('增量复审', message)
        self.assertIn('CR-001', message)
        self.assertIn('Login.kt', message)

    def test_context_from_another_item_is_not_reused(self):
        self.interrupt_after_review()
        other = CodeReviewContext('R-002', self.paths)
        message = other.render()
        self.assertIn('首审', message)
        self.assertNotIn('点击登录无响应', message)
        self.assertNotIn('previous_review', other.state)

    def test_corrupt_snapshot_recovers_from_reports(self):
        self.reject('')
        context_file = Path(self.paths['workspace']) / 'code_review_context.json'
        context_file.write_text('{broken', encoding='utf-8')
        message = read_handoff(CodeReviewContext('R-001', self.paths, previous_attempts=2).render())
        self.assertIn('历史快照缺失', message)
        self.assertIn('CR-001', message)
        self.assertIn('logout.log', message)


if __name__ == '__main__':
    unittest.main()
