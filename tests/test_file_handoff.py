import json
import tempfile
import unittest
from pathlib import Path

from review_context import CodeReviewContext
from review_decision import review_passed
from unittest.mock import MagicMock
from break_pipeline import BreakPipeline


class FileHandoffTests(unittest.TestCase):
    def test_receipt_status_is_independent_of_optional_approval_description(self):
        from task_protocol import TaskMessage, validate_receipt, parse_final_answer, ReceiptError
        from review_decision import structured_review_decision
        for status in ('completed', 'approved', 'changes_requested', 'requirement_change', 'blocked'):
            for extra in ({}, {'approval_token': None}, {'approval_token': ''},
                          {'approval_token': '任务完成'}, {'approval_token': '任意说明'}):
                with self.subTest(status=status, extra=extra):
                    data = dict(status=status, summary='说明', outputs={}, **extra)
                    reply = 'FINAL_ANSWER ' + json.dumps(data)
                    if status != 'blocked':
                        task = TaskMessage('task', [], [], '', {status})
                        self.assertEqual(parse_final_answer(validate_receipt(reply, task, '.'))['status'], status)
                    if status != 'completed':
                        self.assertEqual(structured_review_decision(reply)['status'], status)
                    self.assertEqual(review_passed(reply), status == 'approved')
        # Optional metadata cannot turn a developer receipt into a review pass.
        task = TaskMessage('development', [], [], '', {'completed'})
        with self.assertRaises(ReceiptError):
            validate_receipt('FINAL_ANSWER {"status":"approved","summary":"ok","outputs":{}}', task, '.')

    def test_all_review_stages_accept_approved_without_token_in_both_pipelines(self):
        from pipeline import Pipeline
        from agents import Agent
        from agents._result import AgentRunResult
        from unittest.mock import patch
        from task_protocol import parse_final_answer
        for cls in (Pipeline, BreakPipeline):
            for stage in ('requirements_review', 'code_review', 'breakdown_review'):
                if cls is Pipeline and stage == 'breakdown_review':
                    continue
                with self.subTest(cls=cls, stage=stage), tempfile.TemporaryDirectory() as root:
                    pipeline = self.pipeline_fixture(root) if cls is BreakPipeline else Pipeline(root)
                    if cls is Pipeline:
                        pipeline._ensure_execution_plan('test')
                    item = pipeline._load_items()[0] if cls is BreakPipeline and stage != 'breakdown_review' else None
                    _, outputs, _ = pipeline._task_paths(stage, item)
                    for value in outputs:
                        path = Path(value)
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text('review evidence')
                    with patch.object(Agent, '_load_system_prompt', return_value=''):
                        reviewer = Agent('review', 'unused.md', root, agent_type='cursor')
                    reviewer.agent_impl = MagicMock()
                    reviewer.agent_impl.run.return_value = AgentRunResult('FINAL_ANSWER ' + json.dumps(
                        dict(status='approved', summary='passed', outputs={str(i): p for i, p in enumerate(outputs)})), None, 0)
                    response = pipeline._send_task(reviewer, 'review', stage, item)
                    self.assertEqual(parse_final_answer(response)['status'], 'approved')
                    self.assertTrue(review_passed(response))
                    reviewer.agent_impl.run.assert_called_once()

    def test_inline_final_receipt_after_progress_is_validated(self):
        from task_protocol import TaskMessage, validate_receipt, ReceiptError
        task = TaskMessage('开发', [], [], '仅回执', {'completed'})
        receipt = 'FINAL_ANSWER\n' + json.dumps(dict(status='completed', approval_token='',
            summary='FINAL_ANSWER 已补正', outputs={}), ensure_ascii=False)
        for prefix in ('正在写入报告。', '只做回执补正：确认后再发合规 FINAL_ANSWER。'):
            self.assertEqual(validate_receipt(prefix + receipt, task, '.').splitlines()[0], 'FINAL_ANSWER')
        for suffix in (' trailing text', '\nFINAL_ANSWER {broken}', '\nFINAL_ANSWER ' + json.dumps(dict(status='approved'))):
            with self.subTest(suffix=suffix), self.assertRaises(ReceiptError):
                validate_receipt('写入报告。' + receipt + suffix, task, '.')

    def test_producer_correction_failure_is_persisted_and_resumes_without_development(self):
        from task_protocol import ReceiptError, ReceiptPending
        for failure in (ReceiptError('缺少 FINAL_ANSWER'), RuntimeError('network timeout')):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as root:
                pipeline = self.pipeline_fixture(root)
                pipeline._set_status('R-001', '开发中')
                item = pipeline._load_items()[0]
                dev = MagicMock()
                original_log = Path(root) / 'original.txt'
                original_log.write_text('original execution evidence')
                dev.last_log_path = str(original_log)
                dev.send_message.side_effect = [ReceiptError('缺少 FINAL_ANSWER'), failure]
                with self.assertRaises(ReceiptPending):
                    pipeline._send_task(dev, '实现登录', 'development', item)
                self.assertEqual(dev.send_message.call_count, 2)
                self.assertIn('缺少 FINAL_ANSWER', dev.send_message.call_args.args[0])
                state = pipeline.execution_plan.read()['items'][0]
                self.assertEqual(state['status'], '开发中')
                self.assertEqual(state['pending_receipts']['development']['log_path'], str(original_log))
                restarted = BreakPipeline(root)
                dev.send_message.reset_mock(side_effect=True)
                dev.send_message.side_effect = RuntimeError('network timeout again')
                with self.assertRaises(ReceiptPending):
                    restarted._send_task(dev, '实现登录', 'development', restarted._load_items()[0])
                dev.send_message.assert_called_once()
                self.assertIn(str(failure), dev.send_message.call_args.args[0])
                self.assertEqual(restarted.execution_plan.read()['items'][0]['pending_receipts']['development']['log_path'], str(original_log))
                dev.send_message.reset_mock(side_effect=True)
                dev.send_message.return_value = 'FINAL_ANSWER {"status":"completed","approval_token":"","summary":"done","outputs":{}}'
                restarted._send_task(dev, '实现登录', 'development', restarted._load_items()[0])
                dev.send_message.assert_called_once()
                prompt = dev.send_message.call_args.args[0]
                self.assertIn('仅根据调用日志', prompt)
                self.assertIn(str(original_log), prompt)
                self.assertNotIn('实现登录', prompt)
                self.assertNotIn('development', restarted.execution_plan.read()['items'][0].get('pending_receipts', {}))

    def test_real_developer_receipt_failure_cannot_reach_review_until_recovered(self):
        from agents import Agent
        from agents._result import AgentRunResult
        from task_protocol import ReceiptPending
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root:
            pipeline = self.pipeline_fixture(root)
            pipeline._set_status('R-001', '待开发')
            item = pipeline._load_items()[0]
            report = Path(pipeline._item_paths(item)['develop'])
            report.write_text('completed work and evidence')
            with patch.object(Agent, '_load_system_prompt', return_value=''):
                dev = Agent('开发', 'item_developer.md', root, agent_type='cursor')
            dev.agent_impl = MagicMock()
            dev.agent_impl.run.return_value = AgentRunResult('broken receipt', None, 0)
            reviewer = MagicMock()
            with self.assertRaises(ReceiptPending):
                pipeline._run_item(item, dev, reviewer)
            reviewer.send_message.assert_not_called()
            self.assertEqual(dev.agent_impl.run.call_count, 2)
            restarted = BreakPipeline(root, skip_human=True)
            dev.agent_impl.run.reset_mock()
            dev.agent_impl.run.return_value = AgentRunResult('报告已写入。FINAL_ANSWER\n' + json.dumps(dict(
                status='completed', approval_token=None, summary='done', outputs={'report': str(report)})), None, 0)
            reviewer.send_message.return_value = 'FINAL_ANSWER {"status":"approved","summary":"ok"}'
            restarted._run_item(restarted._load_items()[0], dev, reviewer)
            dev.agent_impl.run.assert_called_once()
            self.assertIn('仅根据调用日志', dev.agent_impl.run.call_args.kwargs['message'])
            reviewer.send_message.assert_called_once()
            self.assertEqual(restarted.execution_plan.read()['items'][0]['status'], '记忆整理中')

    def test_normalizer_recovery_does_not_restore_cleared_pending_record(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root:
            pipeline = self.pipeline_fixture(root)
            pending = dict(log_path='original.log', task_path='original-task.txt')
            pipeline._save_pending_receipt('normalize', None, pending)
            normalizer = MagicMock()
            normalizer.send_message.return_value = 'FINAL_ANSWER {"status":"completed","approval_token":"","summary":"done","outputs":{}}'
            with patch.object(pipeline, '_create_agent', return_value=normalizer):
                pipeline._ensure_execution_plan()
            self.assertIn('仅根据调用日志', normalizer.send_message.call_args.args[0])
            self.assertIsNone(pipeline._pending_receipt('normalize', None))

    def test_existing_index_resumes_pending_breaker_before_review(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root:
            pipeline = self.pipeline_fixture(root)
            pipeline._save_pending_receipt('breakdown', None, dict(log_path='original.log', task_path='original-task.txt'))
            breaker, reviewer = MagicMock(), MagicMock()
            calls = []
            breaker.send_message.side_effect = lambda task: calls.append('breaker') or 'FINAL_ANSWER {"status":"completed"}'
            reviewer.send_message.side_effect = lambda task: calls.append('reviewer') or 'FINAL_ANSWER {"status":"approved","approval_token":"拆分方案通过","summary":"ok"}'
            with patch.object(pipeline, '_create_agent', side_effect=[breaker, reviewer]):
                pipeline._run_breakdown()
            self.assertEqual(calls, ['breaker', 'reviewer'])
            self.assertIn('仅根据调用日志', breaker.send_message.call_args.args[0])
            self.assertIsNone(pipeline._pending_receipt('breakdown', None))

    def pipeline_fixture(self, root, attempts=0):
        pipeline = BreakPipeline(root, skip_human=True)
        Path(pipeline.requirements_dir).mkdir(exist_ok=True)
        Path(pipeline.requirements_index_file).write_text('index')
        target = Path(pipeline.requirements_dir) / 'R-001' / 'user_requirements.md'
        target.parent.mkdir(exist_ok=True)
        target.write_text('AC-01')
        pipeline.execution_plan.write(dict(demand=dict(id='D-001', status='开发中', source='test'),
            source_index_sha256=pipeline.execution_plan.index_hash(), items=[dict(order=1,
            id='R-001', name='登录', status='代码评审中', dependencies=[], requirements_file='R-001/user_requirements.md',
            acceptance_summary='AC-01', stage_attempts={'code_review': attempts})]))
        return pipeline

    def test_all_failed_invocations_exhaust_budget_without_developer_rework(self):
        for failure in (RuntimeError('[Errno 7] Argument list too long'), RuntimeError('network connection failed'), ''):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as root:
                pipeline = self.pipeline_fixture(root)
                dev, reviewer = MagicMock(), MagicMock()
                if isinstance(failure, Exception):
                    reviewer.send_message.side_effect = failure
                else:
                    reviewer.send_message.return_value = failure
                pipeline._run_item(pipeline._load_items()[0], dev, reviewer)
                record = pipeline.execution_plan.read()['items'][0]
                self.assertEqual(record['stage_attempts']['code_review'], 10)
                self.assertEqual(reviewer.send_message.call_count, 10)
                self.assertEqual(record['status'], '未通过，跳过执行')
                self.assertEqual(len(record['attempt_history']['code_review']), 10)
                dev.send_message.assert_not_called()
                self.assertNotEqual(record['review_outcomes']['code_review']['last_feedback'], '已达到累计 10 次上限')
                # Restart cannot invoke an eleventh review or reset the budget.
                restarted = BreakPipeline(root, skip_human=True)
                restarted._run_item(restarted._load_items()[0], dev, reviewer)
                self.assertEqual(reviewer.send_message.call_count, 10)

    def test_receipt_correction_is_charged_and_does_not_rerun_review(self):
        with tempfile.TemporaryDirectory() as root:
            pipeline = self.pipeline_fixture(root, 8)
            dev, reviewer = MagicMock(), MagicMock()
            reviewer.send_message.side_effect = ['broken', 'FINAL_ANSWER {"status":"approved","approval_token":"任务完成","summary":"ok"}']
            pipeline._run_item(pipeline._load_items()[0], dev, reviewer)
            self.assertIn('本轮为回执补正', reviewer.send_message.call_args.args[0])
            self.assertIn('缺少 FINAL_ANSWER', reviewer.send_message.call_args.args[0])
            self.assertEqual(pipeline.execution_plan.read()['items'][0]['stage_attempts']['code_review'], 10)
            dev.send_message.assert_not_called()

    def test_correction_survives_network_failure_and_keeps_original_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            pipeline = self.pipeline_fixture(root, 7)
            dev, reviewer = MagicMock(), MagicMock()
            reviewer.send_message.side_effect = ['broken', RuntimeError('network failure'),
                'FINAL_ANSWER {"status":"approved","approval_token":"任务完成","summary":"ok"}']
            pipeline._run_item(pipeline._load_items()[0], dev, reviewer)
            calls = reviewer.send_message.call_args_list
            self.assertIn('本轮为回执补正', calls[1].args[0])
            self.assertIn('本轮为回执补正', calls[2].args[0])
            record = pipeline.execution_plan.read()['items'][0]
            self.assertIn(record['attempt_history']['code_review'][0]['log_path'], calls[2].args[0])
            self.assertEqual(record['stage_attempts']['code_review'], 10)
            dev.send_message.assert_not_called()

    def test_large_documents_never_enter_review_message(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = {'workspace': directory}
            for key in ('requirements', 'requirements_analysis', 'develop', 'test', 'code_review', 'bug'):
                p = Path(directory) / (key + '.md')
                p.write_text('PRIVATE_DOCUMENT_BODY' * 100000)
                paths[key] = str(p)
            context = CodeReviewContext('R-001', paths)
            first = context.render()
            self.assertNotIn('PRIVATE_DOCUMENT_BODY', first)
            self.assertLess(len(first.encode()), 16000)
            context.record_review('FINAL_ANSWER {"status":"changes_requested","approval_token":""}')
            Path(paths['test']).write_text('overwritten')
            second = CodeReviewContext('R-001', paths, 1).render()
            self.assertNotIn('PRIVATE_DOCUMENT_BODY', second)
            self.assertLess(len(second.encode()), 16000)
            evidence = context.state['previous_review']['evidence']['test']
            self.assertIn('PRIVATE_DOCUMENT_BODY', Path(evidence['path']).read_text())

    def test_empty_or_keyword_only_reply_never_approves(self):
        for response in (None, '', '任务完成', '不要输出任务完成'):
            self.assertFalse(review_passed(response))

    def test_oversize_final_answer_never_approves(self):
        response = 'FINAL_ANSWER ' + json.dumps(dict(status='approved', approval_token='任务完成', summary='中' * 2048), ensure_ascii=False)
        self.assertFalse(review_passed(response))

    def test_receipt_contract_rejects_missing_files_and_preserves_full_json(self):
        from task_protocol import TaskMessage, validate_receipt, ReceiptError
        with tempfile.TemporaryDirectory() as root:
            output = str(Path(root) / 'report.md')
            task = TaskMessage('实现登录', [], [output], '写开发报告', {'completed'})
            reply = 'FINAL_ANSWER ' + json.dumps(dict(status='completed', approval_token='', summary='已完成', outputs={'report': output}))
            with self.assertRaises(ReceiptError):
                validate_receipt(reply, task, root)
            Path(output).write_text('evidence')
            self.assertEqual(json.loads(validate_receipt(reply, task, root).split('\n', 1)[1])['status'], 'completed')
            with self.assertRaises(ReceiptError):
                validate_receipt(reply + ' trailing text', task, root)

    def test_no_unbounded_issue_details_in_final_answer(self):
        from task_protocol import TaskMessage, validate_receipt, ReceiptError
        task = TaskMessage('审核', [], [], '问题写报告', {'changes_requested'})
        with self.assertRaises(ReceiptError):
            validate_receipt('FINAL_ANSWER {"status":"changes_requested","approval_token":"","summary":"失败","outputs":{},"issues":[{"problem":"全文"}]}', task, '.')

    def test_final_marker_in_summary_does_not_break_valid_json(self):
        from task_protocol import TaskMessage, validate_receipt
        task = TaskMessage('分析', [], [], '仅回执', {'completed'})
        result = validate_receipt('FINAL_ANSWER {"status":"completed","approval_token":"","summary":"FINAL_ANSWER 已补正","outputs":{}}', task, '.')
        self.assertIn('已补正', result)

    def test_wrong_status_type_is_a_recorded_format_failure(self):
        from task_protocol import TaskMessage, validate_receipt, ReceiptError
        task = TaskMessage('分析', [], [], '仅回执', {'completed'})
        for status in ([], {}, None, 1):
            with self.subTest(status=status), self.assertRaises(ReceiptError):
                validate_receipt('FINAL_ANSWER ' + json.dumps(dict(status=status)), task, '.')

    def test_invalid_output_path_is_a_format_error(self):
        from task_protocol import TaskMessage, validate_receipt, ReceiptError
        task = TaskMessage('分析', [], [], '仅回执', {'completed'})
        with self.assertRaises(ReceiptError):
            validate_receipt('FINAL_ANSWER ' + json.dumps(dict(status='completed', approval_token='',
                summary='done', outputs={'report': 'invalid\x00.md'})), task, '.')

    def test_normal_pipeline_tenth_rejection_does_not_start_rework(self):
        from pipeline import Pipeline
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root:
            pipeline = Pipeline(root)
            pipeline._ensure_execution_plan('test')
            pipeline._set_status('需求评审中')
            for _ in range(9):
                pipeline.execution_plan.increment_stage_attempt('requirements_review', 'R-001')
            analyst, reviewer = MagicMock(), MagicMock()
            reviewer.send_message.return_value = 'FINAL_ANSWER {"status":"changes_requested","approval_token":"","summary":"fix"}'
            with patch.object(pipeline, '_create_agent', side_effect=[analyst, reviewer]):
                self.assertFalse(pipeline._run_stage_1_requirements())
            analyst.send_message.assert_not_called()
            self.assertEqual(reviewer.send_message.call_count, 1)

    def test_real_agent_enforces_protocol_and_disables_hidden_retries(self):
        from agents import Agent
        from agents._result import AgentRunResult
        from task_protocol import TaskMessage, ReceiptError
        with tempfile.TemporaryDirectory() as root:
            agent = Agent('开发', 'item_developer.md', root, agent_type='cursor')
            agent.agent_impl = MagicMock()
            agent.agent_impl.run.return_value = AgentRunResult('plain text', 'session', 0)
            with self.assertRaises(ReceiptError):
                agent.send_message(TaskMessage('实现登录', [], [], '写报告', {'completed'}))
            self.assertEqual(agent.agent_impl.max_retries, 0)
            self.assertEqual(Path(agent.last_log_path).read_text(), 'plain text')

    def test_long_blocker_url_stays_in_report_and_human_gate_reads_it(self):
        from task_protocol import TaskMessage, validate_receipt
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'requirements' / 'resource_blocker.json'
            path.parent.mkdir()
            url = 'https://example.invalid/' + 'x' * 3000
            path.write_text(json.dumps(dict(kind='material_permission_denied', resource=url,
                reason='403', impact='无法拆分', required_user_action='授予权限')))
            task = TaskMessage('拆分', [], [], '报告写完整资源', {'blocked'}, optional_outputs=[str(path)])
            reply = 'FINAL_ANSWER ' + json.dumps(dict(status='blocked', approval_token='', summary='FINAL_ANSWER：资源无权读取', outputs={'blocker': str(path)}))
            final = validate_receipt(reply, task, root)
            self.assertLess(len(final), 2048)
            self.assertEqual(BreakPipeline._breakdown_resource_blocker(final, root)['resource'], url)

    def test_requirement_change_with_marker_in_summary_keeps_its_status(self):
        self.assertTrue(BreakPipeline._is_requirement_change('FINAL_ANSWER {"status":"requirement_change","approval_token":"","summary":"FINAL_ANSWER: 需求需修订"}'))

    def test_normalizer_preserves_attempt_history(self):
        with tempfile.TemporaryDirectory() as root:
            pipeline = self.pipeline_fixture(root, 9)
            before = pipeline.execution_plan.read()
            before['items'][0]['attempt_history'] = {'code_review': [{'kind': 'receipt_format_error', 'log_path': 'previous.log'}]}
            before['demand']['attempt_history'] = {'breakdown_review': [{'kind': 'network_error'}]}
            normalized = pipeline.execution_plan.read()
            pipeline._preserve_unchanged_statuses(before, normalized)
            self.assertEqual(normalized['items'][0].get('attempt_history'), before['items'][0]['attempt_history'])
            self.assertEqual(normalized['demand'].get('attempt_history'), before['demand']['attempt_history'])

    def test_every_review_stage_snapshots_reports(self):
        with tempfile.TemporaryDirectory() as root:
            pipeline = self.pipeline_fixture(root, 0)
            item = pipeline._load_items()[0]
            output = Path(pipeline._item_paths(item)['requirements_review'])
            output.write_text('original issues')
            reviewer = MagicMock()
            reviewer.send_message.return_value = 'FINAL_ANSWER {"status":"changes_requested","approval_token":"","summary":"fix"}'
            pipeline.execution_plan.increment_stage_attempt('requirements_review', 'R-001')
            pipeline._send_task(reviewer, '完整需求审核', 'requirements_review', item)
            output.write_text('next round')
            history = pipeline._last_attempt('requirements_review', 'R-001')
            self.assertEqual(Path(history['outputs'][str(output)]).read_text(), 'original issues')
