from handoff_helpers import read_handoff
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from break_pipeline import BreakPipeline


BLOCKED = 'FINAL_ANSWER ' + json.dumps(dict(status='blocked', approval_token='', blocker=dict(
    reason='真实账号缺失', affected_acs=['AC-01'], attempts=['Mock health OK'],
    evidence=['health.log'], resume_condition='真实账号')))


class ProgressiveDeliveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.pipeline = BreakPipeline(temp.name, skip_human=True)
        root = Path(self.pipeline.requirements_dir)
        root.mkdir()
        Path(self.pipeline.requirements_index_file).write_text('index', encoding='utf-8')
        items = []
        for number in range(1, 3):
            rid = f'R-{number:03}'
            target = root / rid / 'user_requirements.md'
            target.parent.mkdir()
            target.write_text('AC-01', encoding='utf-8')
            items.append(dict(order=number, id=rid, name=rid, status='待开发',
                              dependencies=[] if number == 1 else ['R-001'],
                              requirements_file=f'{rid}/user_requirements.md', acceptance_summary='AC-01'))
        self.pipeline.execution_plan.write(dict(demand=dict(id='D-001', status='开发中', source='test'),
            source_index_sha256=self.pipeline.execution_plan.index_hash(), items=items))

    def restart_until_complete(self, action):
        from task_protocol import TaskRetryRequired
        for _ in range(11):
            try:
                return action()
            except TaskRetryRequired:
                pass
        self.fail('Restart loop did not converge within persisted review limit')

    def record(self):
        return self.pipeline.execution_plan.read()['items'][0]

    def item(self, status):
        self.pipeline._set_status('R-001', status)
        return self.pipeline._load_items()[0]

    def test_developer_legacy_blocked_goes_to_review_not_suspension(self):
        dev, review = MagicMock(), MagicMock()
        dev.send_message.return_value = BLOCKED
        review.send_message.return_value = 'FINAL_ANSWER {"status": "approved", "approval_token": "任务完成", "summary": "任务完成", "outputs": {}}'
        self.pipeline._run_item(self.item('待开发'), dev, review)
        self.assertEqual(self.record()['status'], '记忆整理中')
        self.assertIn('blocked', self.record()['continuation_notes'][0]['response'])
        self.assertNotIn('真实账号缺失', review.send_message.call_args.args[0])
        self.assertIn('真实账号缺失', read_handoff(review.send_message.call_args.args[0]))

    def test_analyst_legacy_blocked_still_reaches_requirements_review(self):
        analyst, review = MagicMock(), MagicMock()
        analyst.send_message.return_value = BLOCKED
        review.send_message.return_value = 'FINAL_ANSWER {"status": "approved", "approval_token": "同意方案", "summary": "同意方案", "outputs": {}}'
        self.pipeline._run_item_requirements(self.item('需求分析中'), analyst, review)
        self.assertEqual(self.record()['status'], '待开发')
        review.send_message.assert_called_once()

    def test_code_review_blocked_is_bounded_rework_not_approval(self):
        dev, review = MagicMock(), MagicMock()
        dev.send_message.return_value = 'Mock implemented'
        review.send_message.return_value = BLOCKED
        item = self.item('代码评审中')
        self.restart_until_complete(lambda: self.pipeline._run_item(self.pipeline._load_items()[0], dev, review))
        self.assertEqual(review.send_message.call_count, 10)
        self.assertEqual(dev.send_message.call_count, 0)
        self.assertEqual(self.record()['status'], '未通过，跳过执行')
        self.assertEqual(self.pipeline._next_runnable_item(self.pipeline._load_items()).requirement_id, 'R-002')

    def test_requirements_limit_continues_to_development_without_approval(self):
        analyst, review = MagicMock(), MagicMock()
        review.send_message.return_value = BLOCKED
        self.item('需求分析中')
        self.restart_until_complete(lambda: self.pipeline._run_item_requirements(self.pipeline._load_items()[0], analyst, review))
        self.assertEqual(self.record()['status'], '待开发')
        self.assertEqual(review.send_message.call_count, 10)
        self.assertIn('requirements_review', self.record()['review_outcomes'])

    def test_existing_blocked_resumes_original_stage_preserving_evidence_and_attempts(self):
        self.pipeline.execution_plan.suspend('R-001', '外部阻塞', '代码评审中', json.loads(BLOCKED.split(' ', 1)[1])['blocker'])
        self.pipeline.execution_plan.increment_stage_attempt('code_review', 'R-001')
        self.pipeline._load_items()
        record = self.record()
        self.assertEqual(record['status'], '代码评审中')
        self.assertEqual(record['stage_attempts']['code_review'], 1)
        self.assertNotIn('suspension', record)
        self.assertEqual(record['suspension_history'][0]['reason'], '真实账号缺失')

    def test_legacy_requirements_limit_continues_to_development(self):
        self.pipeline.execution_plan.suspend('R-001', '未通过，跳过执行', '需求评审中', {'reason': '10 attempts'})
        self.pipeline._load_items()
        self.assertEqual(self.record()['status'], '待开发')
        self.assertIn('requirements_review', self.record()['review_outcomes'])

    def test_upstream_failure_context_is_given_to_downstream(self):
        self.pipeline._exhaust_stage('R-001', '代码评审中', '真实未验；Mock ready')
        item = self.pipeline._load_items()[1]
        dev, review = MagicMock(), MagicMock()
        review.send_message.return_value = 'FINAL_ANSWER {"status": "approved", "approval_token": "任务完成", "summary": "任务完成", "outputs": {}}'
        self.pipeline._run_item(item, dev, review)
        self.assertNotIn('真实未验；Mock ready', dev.send_message.call_args.args[0])
        self.assertIn('真实未验；Mock ready', read_handoff(dev.send_message.call_args.args[0]))

    def test_all_attempted_does_not_archive_or_claim_all_passed(self):
        self.pipeline._exhaust_stage('R-001', '代码评审中', 'unresolved')
        self.pipeline._set_status('R-002', '已完成')
        Path(self.pipeline.breakdown_approval_file).write_text('approved', encoding='utf-8')
        with patch.object(self.pipeline, '_archive_completed_requirements') as archive:
            self.assertFalse(self.pipeline.run())
            archive.assert_not_called()
        self.assertEqual(self.pipeline.execution_plan.read()['demand']['status'], '执行结束（有未通过项）')

    def test_breakdown_resource_blocking_remains(self):
        response = 'FINAL_ANSWER ' + json.dumps(dict(status='blocked', approval_token='',
            blocker=dict(kind='file_unreadable', resource='https://example.test/spec', reason='403', required_user_action='grant read')))
        self.assertIsNotNone(self.pipeline._breakdown_resource_blocker(response))

    def test_full_execution_continues_dependent_after_code_review_limit(self):
        agents = {name: MagicMock() for name in ['analyst', 'requirements_reviewer', 'developer', 'code_reviewer']}
        agents['developer'].send_message.return_value = 'Mock implemented'
        agents['code_reviewer'].send_message.side_effect = [BLOCKED] * 10 + ['FINAL_ANSWER {"status": "approved", "approval_token": "任务完成", "summary": "任务完成", "outputs": {}}']
        with patch.object(self.pipeline, '_item_agents', return_value=agents), \
                patch.object(self.pipeline, '_should_save_item_memory', return_value=False):
            self.assertFalse(self.restart_until_complete(self.pipeline._run_execution))
        records = self.pipeline.execution_plan.read()['items']
        self.assertEqual([item['status'] for item in records], ['未通过，跳过执行', '已完成'])
        self.assertEqual(agents['code_reviewer'].send_message.call_count, 11)
        self.assertEqual(records[0]['stage_attempts']['code_review'], 10)

    def test_analysis_limit_still_allows_current_and_dependent_development(self):
        self.item('需求分析中')
        agents = {name: MagicMock() for name in ['analyst', 'requirements_reviewer', 'developer', 'code_reviewer']}
        agents['requirements_reviewer'].send_message.return_value = BLOCKED
        agents['code_reviewer'].send_message.return_value = 'FINAL_ANSWER {"status": "approved", "approval_token": "任务完成", "summary": "任务完成", "outputs": {}}'
        with patch.object(self.pipeline, '_item_agents', return_value=agents), \
                patch.object(self.pipeline, '_should_save_item_memory', return_value=False):
            self.assertFalse(self.restart_until_complete(self.pipeline._run_execution))
        self.assertEqual(agents['developer'].send_message.call_count, 2)
        self.assertEqual(self.pipeline.execution_plan.read()['demand']['status'], '执行结束（有未通过项）')

    def test_migration_is_idempotent_and_keeps_counters(self):
        self.pipeline.execution_plan.suspend('R-001', '外部阻塞', '需求分析中', json.loads(BLOCKED.split(' ', 1)[1])['blocker'])
        self.pipeline._load_items()
        first = self.pipeline.execution_plan.read()
        self.pipeline._load_items()
        self.assertEqual(self.pipeline.execution_plan.read(), first)

    def test_normalization_preserves_new_runtime_facts(self):
        previous = self.pipeline.execution_plan.read()
        previous['items'][0]['review_outcomes'] = {'requirements_review': {'status': 'not_approved'}}
        previous['items'][0]['continuation_notes'] = [{'stage': '开发中', 'response': 'Mock ready'}]
        current = self.pipeline.execution_plan.read()
        self.pipeline._preserve_unchanged_statuses(previous, current)
        self.assertEqual(current['items'][0], previous['items'][0])

    def test_malformed_blocked_with_approval_text_is_not_passed(self):
        item = self.item('代码评审中')
        output = self.pipeline._normalize_item_response(item, '代码评审中', 'FINAL_ANSWER {"status":"blocked", "summary":"任务完成"')
        self.assertFalse(self.pipeline._review_passed(output))
        self.assertEqual(self.record()['status'], '代码评审中')


class ProgressivePromptTests(unittest.TestCase):
    def test_four_item_prompts_prioritize_existing_fallbacks(self):
        root = Path(__file__).resolve().parents[1] / 'break-system-prompt'
        for name in ['item_requirements_analyst', 'item_requirements_reviewer', 'item_developer', 'item_code_reviewer']:
            with self.subTest(name=name):
                text = (root / f'{name}.md').read_text(encoding='utf-8')
                self.assertIn('不得返回 blocked', text)
                self.assertNotIn('"status":"blocked"', text)
                self.assertIn('Mock/Stub/Fake', text)
                self.assertIn('Agent 保守决策', text)
                self.assertIn('按失败节点', text)
                self.assertNotIn('不得擅自购买/创建环境', text)
