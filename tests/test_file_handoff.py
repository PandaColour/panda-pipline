import json
import tempfile
import unittest
from pathlib import Path

from review_context import CodeReviewContext
from review_decision import review_passed
from unittest.mock import MagicMock
from break_pipeline import BreakPipeline


class FileHandoffTests(unittest.TestCase):
    def test_zero_exit_receipt_is_corrected_locally_once_across_stages(self):
        from agents import Agent
        from agents._result import AgentRunResult
        from task_protocol import TaskRetryRequired
        from unittest.mock import patch
        for stage in ('analysis', 'development', 'memory_analysis', 'memory_development',
                      'breakdown', 'summary', 'normalize', 'requirements_review',
                      'code_review', 'breakdown_review'):
            for correction_ok in (True, False):
                with self.subTest(stage=stage, correction_ok=correction_ok), tempfile.TemporaryDirectory() as root:
                    pipeline = self.pipeline_fixture(root)
                    item = None if stage in {'breakdown', 'summary', 'normalize', 'breakdown_review'} else pipeline._load_items()[0]
                    rid = item.requirement_id if item else None
                    reviewing = stage in {'requirements_review', 'code_review', 'breakdown_review'}
                    if reviewing:
                        pipeline.execution_plan.increment_stage_attempt(stage, rid)
                    _, outputs, _ = pipeline._task_paths(stage, item)
                    for output in outputs:
                        if stage != 'normalize':
                            Path(output).write_text('existing evidence')
                    with patch.object(Agent, '_load_system_prompt', return_value=''):
                        agent = Agent('test', 'unused.md', root, agent_type='cursor')
                    valid = 'FINAL_ANSWER ' + json.dumps(dict(
                        status='approved' if reviewing else 'completed', summary='verified',
                        outputs={str(i): path for i, path in enumerate(outputs)}))
                    agent.agent_impl = MagicMock()
                    agent.agent_impl.run.side_effect = [
                        AgentRunResult('报告已写入', 'same-session', 0),
                        AgentRunResult(valid if correction_ok else '', 'same-session', 0)]
                    if correction_ok:
                        self.assertIn('verified', pipeline._send_task(agent, 'business task', stage, item))
                        self.assertIsNone(pipeline._pending_receipt(stage, rid))
                    else:
                        with self.assertRaises(TaskRetryRequired):
                            pipeline._send_task(agent, 'business task', stage, item)
                        self.assertEqual(pipeline._pending_receipt(stage, rid)['mode'], 'receipt')
                    self.assertEqual(agent.agent_impl.run.call_count, 2)
                    self.assertEqual(pipeline.execution_plan.get_stage_attempt(stage, rid), 2)
                    second = agent.agent_impl.run.call_args.kwargs
                    self.assertEqual(second['session_id'], 'same-session')
                    self.assertIn('回执补正', second['message'])
                    self.assertIn('不得重新执行开发、测试或审核', second['message'])
                    self.assertIn('缺少 FINAL_ANSWER', second['message'])
                    state = pipeline.execution_plan._agent_session_target(pipeline.execution_plan.read(), rid)
                    self.assertEqual(state['attempt_history'][stage][0]['exit_code'], 0)
                    self.assertEqual(state['attempt_history'][stage][-1]['attempt'],
                                     2 if reviewing or not correction_ok else 1)

    def test_review_local_correction_respects_last_available_attempt(self):
        from agents._result import AgentRunResult
        from task_protocol import ReceiptError, TaskRetryRequired
        with tempfile.TemporaryDirectory() as root:
            pipeline = self.pipeline_fixture(root, 9)
            reviewer = MagicMock()
            reviewer.last_run_result = AgentRunResult('', None, 0)
            reviewer.send_message.side_effect = ReceiptError('缺少 FINAL_ANSWER')
            with self.assertRaises(TaskRetryRequired):
                pipeline._run_item(pipeline._load_items()[0], MagicMock(), reviewer)
            self.assertEqual(reviewer.send_message.call_count, 1)
            self.assertEqual(pipeline.execution_plan.get_stage_attempt('code_review', 'R-001'), 10)

    def test_corrected_rejection_at_limit_does_not_start_development(self):
        from agents._result import AgentRunResult
        with tempfile.TemporaryDirectory() as root:
            pipeline = self.pipeline_fixture(root, 8)
            developer, reviewer = MagicMock(), MagicMock()
            reviewer.last_run_result = AgentRunResult('', None, 0)
            reviewer.send_message.side_effect = [
                'broken', 'FINAL_ANSWER {"status":"changes_requested","summary":"CR-001 remains"}']
            pipeline._run_item(pipeline._load_items()[0], developer, reviewer)
            developer.send_message.assert_not_called()
            self.assertEqual(reviewer.send_message.call_count, 2)
            self.assertEqual(pipeline.execution_plan.get_stage_attempt('code_review', 'R-001'), 10)
            self.assertEqual(pipeline.execution_plan.read()['items'][0]['status'], '未通过，跳过执行')

    def test_normalizer_correction_preserves_written_plan_and_failure_accounting(self):
        from agents import Agent
        from agents._result import AgentRunResult
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root:
            pipeline = self.pipeline_fixture(root)
            with patch.object(Agent, '_load_system_prompt', return_value=''):
                agent = Agent('test', 'unused.md', root, agent_type='cursor')
            def run(**kwargs):
                plan = pipeline.execution_plan.read()
                if '回执补正' not in kwargs['message']:
                    plan['items'][0]['name'] = 'new normalized requirement'
                    plan['demand'].pop('stage_attempts', None)
                    pipeline.execution_plan.write(plan)
                    return AgentRunResult('', None, 0)
                self.assertEqual(plan['items'][0]['name'], 'new normalized requirement')
                return AgentRunResult('FINAL_ANSWER ' + json.dumps(dict(
                    status='completed', summary='ok', outputs={'plan': pipeline.execution_plan_file})), None, 0)
            agent.agent_impl = MagicMock()
            agent.agent_impl.run.side_effect = run
            pipeline._send_task(agent, 'normalize', 'normalize')
            plan = pipeline.execution_plan.read()
            self.assertEqual(plan['items'][0]['name'], 'new normalized requirement')
            self.assertEqual(plan['demand']['stage_attempts']['normalize'], 2)
            self.assertEqual(plan['demand']['attempt_history']['normalize'][0]['attempt'], 1)


    def test_deduplication_stays_within_owner_and_preserves_original_bytes(self):
        from task_protocol import save_handoff
        with tempfile.TemporaryDirectory() as root:
            content = '中文\r\noriginal\n'
            a = Path(save_handoff(Path(root) / 'R-001', 'review', content))
            again = Path(save_handoff(Path(root) / 'R-001', 'feedback', content))
            b = Path(save_handoff(Path(root) / 'R-002', 'review', content))
            self.assertEqual(a, again)
            self.assertNotEqual(a, b)
            self.assertEqual(a.read_bytes(), content.encode('utf-8'))

    def test_overall_failure_task_stays_in_outer_handoffs(self):
        from task_protocol import TaskRetryRequired
        with tempfile.TemporaryDirectory() as root:
            pipeline = self.pipeline_fixture(root)
            agent = MagicMock()
            agent.last_run_result = None
            agent.send_message.side_effect = RuntimeError('connection failed')
            with self.assertRaises(TaskRetryRequired):
                pipeline._send_task(agent, 'overall split', 'breakdown')
            saved = pipeline._pending_receipt('breakdown', None)
            self.assertEqual(Path(saved['task_path']).parent,
                             (Path(pipeline.requirements_dir) / 'handoffs').resolve())

    def test_handoff_scope_separates_item_from_overall_inputs(self):
        with tempfile.TemporaryDirectory() as root:
            pipeline = self.pipeline_fixture(root)
            item = pipeline._load_items()[0]
            message = pipeline._handoff('feedback', 'item feedback', item)
            item_file = Path(message.removeprefix('请读取文档：'))
            self.assertEqual(item_file.parent, (Path(pipeline._item_paths(item)['workspace']) / 'handoffs').resolve())
            self.assertFalse((Path(pipeline.requirements_dir) / 'handoffs').exists())
            global_file = Path(pipeline._handoff('user_idea', 'global input').removeprefix('请读取文档：'))
            self.assertEqual(global_file.parent, (Path(pipeline.requirements_dir) / 'handoffs').resolve())

    def test_same_item_review_reuses_context_snapshot_despite_different_label(self):
        from task_protocol import save_handoff
        with tempfile.TemporaryDirectory() as root:
            pipeline = self.pipeline_fixture(root)
            item = pipeline._load_items()[0]
            paths = pipeline._item_paths(item)
            context = CodeReviewContext(item.requirement_id, paths)
            response = 'FINAL_ANSWER {"status":"changes_requested","summary":"CR-001"}'
            context.record_review(response)
            expected = context.state['previous_review']['response_path']
            actual = pipeline._handoff('review', response, item).removeprefix('请读取文档：')
            self.assertEqual(actual, expected)
            self.assertEqual(save_handoff(paths['workspace'], 'feedback', response), expected)
            copies = [p for p in Path(root).rglob('*.txt') if p.read_text() == response]
            self.assertEqual(len(copies), 1)

    def test_failed_item_task_is_local_and_legacy_recovery_path_is_preserved(self):
        from task_protocol import TaskRetryRequired
        with tempfile.TemporaryDirectory() as root:
            pipeline = self.pipeline_fixture(root)
            item = pipeline._load_items()[0]
            agent = MagicMock()
            agent.last_run_result = None
            agent.send_message.side_effect = RuntimeError('network failed')
            with self.assertRaises(TaskRetryRequired):
                pipeline._send_task(agent, 'original task', 'development', item)
            saved = pipeline._pending_receipt('development', item.requirement_id)
            task = Path(saved['task_path'])
            self.assertEqual(task.parent, (Path(pipeline._item_paths(item)['workspace']) / 'handoffs').resolve())
            legacy = Path(pipeline.requirements_dir) / 'handoffs/producer-task-old.txt'
            legacy.parent.mkdir()
            legacy.write_bytes(task.read_bytes())
            saved['task_path'] = str(legacy)
            pipeline._save_pending_receipt('development', item.requirement_id, saved)
            restarted = BreakPipeline(root, skip_human=True)
            with self.assertRaises(TaskRetryRequired):
                restarted._send_task(agent, 'retry', 'development', restarted._load_items()[0])
            self.assertEqual(restarted._pending_receipt('development', item.requirement_id)['task_path'], str(legacy))
            self.assertIn(str(legacy), agent.send_message.call_args.args[0])
            self.assertTrue(task.is_file())
            self.assertTrue(legacy.is_file())

    def test_device_entry_is_in_each_execution_turn_only_for_allowed_stages(self):
        for stage in ('development', 'code_review', 'analysis', 'requirements_review', 'memory_development'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as root:
                pipeline = self.pipeline_fixture(root)
                item = pipeline._load_items()[0]
                agent = MagicMock()
                status = 'approved' if stage.endswith('review') else 'completed'
                agent.send_message.return_value = 'FINAL_ANSWER ' + json.dumps(dict(status=status, summary='ok', outputs={}))
                pipeline._send_task(agent, '执行本轮任务', stage, item)
                task = agent.send_message.call_args.args[0]
                if stage in {'development', 'code_review'}:
                    self.assertIn('python3 scripts/android_emulator.py', task)
                    self.assertIn('SKILL.md 所在目录', task)
                    self.assertIn('覆盖旧会话', task)
                else:
                    self.assertNotIn('android_emulator.py', task)
                    self.assertIn('不启动模拟器', task)

    def test_development_and_code_review_use_analysis_as_primary_requirement_input(self):
        with tempfile.TemporaryDirectory() as root:
            pipeline = self.pipeline_fixture(root)
            item = pipeline._load_items()[0]
            paths = pipeline._item_paths(item)
            for stage in ('development', 'code_review'):
                inputs, _, _ = pipeline._task_paths(stage, item)
                self.assertIn(paths['requirements_analysis'], inputs)
                self.assertNotIn(paths['requirements'], inputs)
                self.assertIn(paths['code_review'], inputs)
            for stage in ('analysis', 'requirements_review'):
                inputs, _, _ = pipeline._task_paths(stage, item)
                self.assertIn(paths['requirements'], inputs)

    def test_material_entry_is_forwarded_without_requiring_ui_on_every_task(self):
        with tempfile.TemporaryDirectory() as root:
            pipeline = self.pipeline_fixture(root)
            item = pipeline._load_items()[0]
            workspace = Path(pipeline._item_paths(item)['workspace'])
            for stage in ('analysis', 'requirements_review', 'development', 'code_review'):
                inputs, outputs, _ = pipeline._task_paths(stage, item)
                self.assertIn(str(workspace / 'figma_assets/asset_manifest.json'), inputs)
                self.assertIn(str(Path(pipeline.requirements_dir) / '_figma_inventory.json'), inputs)
                self.assertNotIn(str(workspace / 'figma_assets/asset_manifest.json'), outputs)
            self.assertFalse((workspace / 'figma_assets').exists())

    def test_producer_success_keeps_only_counters_and_formal_reports(self):
        from agents import Agent
        from agents._result import AgentRunResult
        from unittest.mock import patch
        for stage in ('analysis', 'development', 'memory_analysis', 'memory_development', 'breakdown', 'normalize', 'summary'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as root:
                pipeline = self.pipeline_fixture(root)
                item = None if stage in ('breakdown', 'normalize', 'summary') else pipeline._load_items()[0]
                _, outputs, _ = pipeline._task_paths(stage, item)
                report = Path(outputs[0])
                if stage != 'normalize':
                    report.write_text('verified facts')
                before = set(Path(pipeline.requirements_dir).rglob('*.txt'))
                with patch.object(Agent, '_load_system_prompt', return_value=''):
                    agent = Agent('记忆', 'item_developer.md', root, agent_type='cursor')
                agent.agent_impl = MagicMock()
                agent.agent_impl.run.return_value = AgentRunResult('FINAL_ANSWER ' + json.dumps(dict(
                    status='completed', summary='done', outputs={'report': str(report)})), None, 0)
                pipeline._send_task(agent, '整理记忆', stage, item)
                state = pipeline.execution_plan._agent_session_target(pipeline.execution_plan.read(), item.requirement_id if item else None)
                self.assertNotIn(stage, state.get('attempt_history', {}))
                self.assertEqual(state['stage_attempts'][stage], 1)
                self.assertEqual(set(Path(pipeline.requirements_dir).rglob('*.txt')), before)
                if stage != 'normalize':
                    self.assertEqual(report.read_text(), 'verified facts')

    def test_failures_use_plan_and_recovery_keeps_existing_files(self):
        from agents import Agent
        from agents._result import AgentRunResult
        from task_protocol import TaskRetryRequired
        from unittest.mock import patch
        for stage in ('analysis', 'development', 'memory_analysis', 'memory_development'):
            for failed in (AgentRunResult('invalid receipt', None, 0),
                           AgentRunResult('', None, 1, 'startup failed')):
                with self.subTest(stage=stage, failed=failed), tempfile.TemporaryDirectory() as root:
                    pipeline = self.pipeline_fixture(root)
                    item = pipeline._load_items()[0]
                    _, outputs, _ = pipeline._task_paths(stage, item)
                    report = Path(outputs[0])
                    report.write_text('existing facts')
                    with patch.object(Agent, '_load_system_prompt', return_value=''):
                        agent = Agent('记忆', 'item_developer.md', root, agent_type='cursor')
                    agent.agent_impl = MagicMock()
                    agent.agent_impl.run.return_value = failed
                    with self.assertRaises(TaskRetryRequired):
                        pipeline._send_task(agent, '整理记忆', stage, item)
                    state = pipeline.execution_plan.read()['items'][0]
                    entry = state['attempt_history'][stage][0]
                    failures = state['attempt_history'][stage]
                    expected_failures = 2 if failed.returncode == 0 else 1
                    self.assertEqual(len(failures), expected_failures)
                    self.assertEqual(agent.agent_impl.run.call_count, expected_failures)
                    self.assertNotIn('log_path', entry)
                    self.assertNotIn('outputs', entry)
                    self.assertEqual(entry['exit_code'], failed.returncode)
                    self.assertIn('缺少 FINAL_ANSWER' if failed.returncode == 0 else 'startup failed', entry['error'])
                    pending = state['pending_receipts'][stage]
                    self.assertNotIn('log_path', pending)
                    if failed.returncode == 0:
                        self.assertEqual(pending['raw_receipt'], failed.text)
                    else:
                        self.assertNotIn('raw_receipt', pending)
                    self.assertFalse(list(Path(pipeline.requirements_dir).rglob('call-*.txt')))
                    self.assertTrue(Path(state['pending_receipts'][stage]['task_path']).is_file())
                    saved = {p: p.read_bytes() for p in Path(pipeline.requirements_dir).rglob('*.txt')}
                    agent.agent_impl.run.return_value = AgentRunResult('FINAL_ANSWER ' + json.dumps(dict(
                        status='completed', summary='done', outputs={'report': str(report)})), None, 0)
                    restarted = BreakPipeline(root)
                    restarted._send_task(agent, '整理记忆', stage, restarted._load_items()[0])
                    state = restarted.execution_plan.read()['items'][0]
                    self.assertEqual(state['attempt_history'][stage], failures)
                    self.assertEqual(state['stage_attempts'][stage], expected_failures + 1)
                    self.assertNotIn(stage, state.get('pending_receipts', {}))
                    self.assertEqual({p: p.read_bytes() for p in Path(pipeline.requirements_dir).rglob('*.txt')}, saved)

    def test_review_keeps_decision_without_duplicate_receipts_or_reports(self):
        for stage in ('requirements_review', 'code_review', 'breakdown_review'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as root:
                pipeline = self.pipeline_fixture(root)
                pipeline._record_attempt(stage, 'R-001', 'approved', 'receipt')
                entry = pipeline.execution_plan.read()['items'][0]['attempt_history'][stage][0]
                self.assertEqual(entry, {'attempt': 0, 'kind': 'approved'})
                self.assertFalse(list(Path(pipeline.requirements_dir).rglob('*.txt')))

    def test_breakdown_failure_before_index_resumes_without_user_input(self):
        from unittest.mock import patch
        from task_protocol import TaskRetryRequired
        with tempfile.TemporaryDirectory() as root:
            pipeline = BreakPipeline(root)
            breaker = MagicMock()
            breaker.send_message.side_effect = RuntimeError('network timeout')
            reviewer = MagicMock()
            with patch.object(pipeline, '_create_agent', side_effect=[breaker, reviewer]), self.assertRaises(TaskRetryRequired):
                pipeline._run_breakdown('原始需求')
            self.assertFalse(Path(pipeline.requirements_index_file).exists())
            restarted = BreakPipeline(root)
            with patch.object(restarted, '_create_agent', side_effect=[breaker, reviewer]), \
                    patch('builtins.input', side_effect=AssertionError('不应重新询问需求')), \
                    self.assertRaises(TaskRetryRequired):
                restarted._run_breakdown()
            self.assertEqual(restarted.execution_plan.get_stage_attempt('breakdown'), 2)
            self.assertEqual(restarted.execution_plan.read()['demand']['source'], '原始需求')
            reviewer.send_message.assert_not_called()

    def test_producer_execution_failure_counts_once_and_resumes_original_work(self):
        from task_protocol import TaskRetryRequired, TaskMessage
        for stage in ('analysis', 'development', 'breakdown', 'normalize', 'memory_analysis', 'memory_development', 'summary'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as root:
                pipeline = self.pipeline_fixture(root)
                item = None if stage in ('breakdown', 'normalize', 'summary') else pipeline._load_items()[0]
                rid = item.requirement_id if item else None
                agent = MagicMock()
                agent.send_message.side_effect = RuntimeError('HTTP/2 keepalive ping timed out')
                with self.assertRaises(TaskRetryRequired):
                    pipeline._send_task(agent, '完成原始业务任务', stage, item)
                agent.send_message.assert_called_once()
                self.assertEqual(pipeline.execution_plan.get_stage_attempt(stage, rid), 1)
                state = pipeline.execution_plan._agent_session_target(pipeline.execution_plan.read(), rid)
                self.assertEqual(state['attempt_history'][stage][0]['kind'], 'network_error')
                self.assertEqual(state['pending_receipts'][stage]['mode'], 'execution')
                task_path = state['pending_receipts'][stage]['task_path']
                self.assertIn('完成原始业务任务', Path(task_path).read_text())
                restarted = BreakPipeline(root)
                agent.send_message.reset_mock(side_effect=True)
                agent.send_message.return_value = 'FINAL_ANSWER {"status":"completed","summary":"done","outputs":{}}'
                restarted._send_task(agent, '恢复入口的简短说明', stage, item)
                task = agent.send_message.call_args.args[0]
                self.assertIsInstance(task, TaskMessage)
                self.assertIn(task_path, task)
                self.assertIn('继续未完成', task)
                self.assertNotIn('仅根据恢复记录', task)
                if stage == 'development':
                    self.assertIn('android_emulator.py', task)
                    self.assertIn('覆盖旧会话', task)
                else:
                    self.assertNotIn('android_emulator.py', task)
                self.assertEqual(restarted.execution_plan.get_stage_attempt(stage, rid), 2)
                self.assertIsNone(restarted._pending_receipt(stage, rid))

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
        for suffix in (' trailing text', 'WWL1B 大需求拆分已完成。', '\n无需再跟进。' * 1000):
            with self.subTest(suffix=suffix[:40]):
                self.assertEqual(validate_receipt('写入报告。' + receipt + suffix, task, '.'),
                                 validate_receipt(receipt, task, '.'))
        for suffix in ('\nFINAL_ANSWER {broken}', '\nFINAL_ANSWER ' + json.dumps(dict(status='approved'))):
            with self.subTest(suffix=suffix), self.assertRaises(ReceiptError):
                validate_receipt('写入报告。' + receipt + suffix, task, '.')

    def test_receipt_extraction_preserves_nested_json_and_escaped_text(self):
        from task_protocol import parse_final_answer
        data = dict(status='completed', summary='嵌套 { }、引号 "、换行\n与 FINAL_ANSWER 已补正',
                    outputs={'report': 'requirements/report.md'})
        body = json.dumps(data, ensure_ascii=False)
        for wrapper in (body, '```json\n' + body + '\n```', '```\r\n' + body + '\r\n```'):
            with self.subTest(wrapper=wrapper):
                self.assertEqual(parse_final_answer('准备交付。FINAL_ANSWER\n' + wrapper + '任务已完成。'), data)

    def test_receipt_extraction_rejects_broken_or_multiple_json_objects(self):
        from task_protocol import parse_final_answer, ReceiptError
        body = json.dumps(dict(status='approved', summary='done', outputs={}))
        for suffix in (body[:-1], body + '\n' + body, '["approved"]',
                       '```json\n' + body, '{broken}\n' + body):
            with self.subTest(suffix=suffix), self.assertRaises(ReceiptError):
                parse_final_answer('FINAL_ANSWER\n' + suffix)

    def test_receipt_surrounding_prose_cannot_override_status_or_required_fields(self):
        from task_protocol import TaskMessage, validate_receipt, ReceiptError
        task = TaskMessage('审核', [], [], '仅回执', {'approved', 'changes_requested'})
        for data in ({'status': 'completed', 'summary': 'done', 'outputs': {}},
                     {'status': 'approved', 'outputs': {}},
                     {'status': 'approved', 'summary': 'done'}):
            with self.subTest(data=data), self.assertRaises(ReceiptError):
                validate_receipt('approved FINAL_ANSWER\n' + json.dumps(data) + '任务完成', task, '.')
        data = dict(status='changes_requested', summary='需修复', outputs={})
        normalized = validate_receipt('FINAL_ANSWER\n' + json.dumps(data) + 'approved 任务完成', task, '.')
        self.assertFalse(review_passed(normalized))

    def test_producer_correction_failure_is_persisted_and_resumes_without_development(self):
        from task_protocol import ReceiptError, ReceiptPending, TaskRetryRequired
        for failure in (ReceiptError('缺少 FINAL_ANSWER'), RuntimeError('network timeout')):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as root:
                pipeline = self.pipeline_fixture(root)
                pipeline._set_status('R-001', '开发中')
                item = pipeline._load_items()[0]
                dev = MagicMock()
                original_log = Path(root) / 'original.txt'
                original_log.write_text('original execution evidence')
                pipeline._save_pending_receipt('development', 'R-001', dict(
                    log_path=str(original_log), task_path=str(original_log)))
                dev.send_message.side_effect = [ReceiptError('缺少 FINAL_ANSWER'), failure]
                with self.assertRaises(ReceiptPending):
                    pipeline._send_task(dev, '实现登录', 'development', item)
                self.assertEqual(dev.send_message.call_count, 1)
                self.assertEqual(pipeline.execution_plan.get_stage_attempt("development", "R-001"), 1)
                state = pipeline.execution_plan.read()['items'][0]
                self.assertEqual(state['status'], '开发中')
                self.assertEqual(state['pending_receipts']['development']['log_path'], str(original_log))
                restarted = BreakPipeline(root)
                dev.send_message.reset_mock(side_effect=True)
                dev.send_message.side_effect = failure
                with self.assertRaises(TaskRetryRequired):
                    restarted._send_task(dev, '实现登录', 'development', restarted._load_items()[0])
                dev.send_message.assert_called_once()
                self.assertIn('缺少 FINAL_ANSWER', dev.send_message.call_args.args[0])
                self.assertEqual(restarted.execution_plan.get_stage_attempt('development', 'R-001'), 2)
                self.assertEqual(restarted.execution_plan.read()['items'][0]['pending_receipts']['development']['log_path'], str(original_log))
                dev.send_message.reset_mock(side_effect=True)
                dev.send_message.return_value = 'FINAL_ANSWER {"status":"completed","approval_token":"","summary":"done","outputs":{}}'
                restarted._send_task(dev, '实现登录', 'development', restarted._load_items()[0])
                dev.send_message.assert_called_once()
                prompt = dev.send_message.call_args.args[0]
                self.assertIn('仅根据恢复记录', prompt)
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
            self.assertIn('仅根据恢复记录', dev.agent_impl.run.call_args.kwargs['message'])
            reviewer.send_message.assert_called_once()
            self.assertEqual(restarted.execution_plan.read()['items'][0]['status'], '记忆整理中')

    def test_developer_receipt_with_closing_summary_reaches_review_without_retry(self):
        from agents import Agent
        from agents._result import AgentRunResult
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
            dev.agent_impl.run.return_value = AgentRunResult(
                '正在写报告。FINAL_ANSWER\n' + json.dumps(dict(status='completed',
                    summary='done', outputs={'report': str(report)})) + '开发已完成，无需再跟进。', None, 0)
            reviewer = MagicMock()
            reviewer.send_message.return_value = 'FINAL_ANSWER {"status":"approved","summary":"ok"}'
            pipeline._run_item(item, dev, reviewer)
            dev.agent_impl.run.assert_called_once()
            reviewer.send_message.assert_called_once()
            self.assertEqual(pipeline.execution_plan.read()['items'][0]['status'], '记忆整理中')

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
            self.assertIn('仅根据恢复记录', normalizer.send_message.call_args.args[0])
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
            self.assertIn('仅根据恢复记录', breaker.send_message.call_args.args[0])
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
        from task_protocol import TaskRetryRequired
        for failure in (RuntimeError('[Errno 7] Argument list too long'), RuntimeError('network connection failed'), ''):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as root:
                pipeline = self.pipeline_fixture(root)
                dev, reviewer = MagicMock(), MagicMock()
                if isinstance(failure, Exception):
                    reviewer.send_message.side_effect = failure
                else:
                    reviewer.send_message.return_value = failure
                for expected in range(1, 11):
                    with self.assertRaises(TaskRetryRequired):
                        pipeline._run_item(pipeline._load_items()[0], dev, reviewer)
                    self.assertEqual(reviewer.send_message.call_count, expected)
                    self.assertEqual(pipeline.execution_plan.get_stage_attempt('code_review', 'R-001'), expected)
                    pipeline = BreakPipeline(root, skip_human=True)
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
        from task_protocol import TaskRetryRequired
        with tempfile.TemporaryDirectory() as root:
            pipeline = self.pipeline_fixture(root, 8)
            dev, reviewer = MagicMock(), MagicMock()
            reviewer.send_message.side_effect = ['broken', 'FINAL_ANSWER {"status":"approved","approval_token":"任务完成","summary":"ok"}']
            with self.assertRaises(TaskRetryRequired):
                pipeline._run_item(pipeline._load_items()[0], dev, reviewer)
            pipeline = BreakPipeline(root, skip_human=True)
            pipeline._run_item(pipeline._load_items()[0], dev, reviewer)
            self.assertIn('本轮为回执补正', reviewer.send_message.call_args.args[0])
            self.assertIn('缺少 FINAL_ANSWER', reviewer.send_message.call_args.args[0])
            self.assertEqual(pipeline.execution_plan.read()['items'][0]['stage_attempts']['code_review'], 10)
            dev.send_message.assert_not_called()

    def test_correction_survives_network_failure_and_keeps_original_receipt(self):
        from task_protocol import TaskRetryRequired
        with tempfile.TemporaryDirectory() as root:
            pipeline = self.pipeline_fixture(root, 7)
            dev, reviewer = MagicMock(), MagicMock()
            reviewer.send_message.side_effect = ['broken', RuntimeError('network failure'),
                'FINAL_ANSWER {"status":"approved","approval_token":"任务完成","summary":"ok"}']
            for _ in range(2):
                with self.assertRaises(TaskRetryRequired):
                    pipeline._run_item(pipeline._load_items()[0], dev, reviewer)
                pipeline = BreakPipeline(root, skip_human=True)
            pipeline._run_item(pipeline._load_items()[0], dev, reviewer)
            calls = reviewer.send_message.call_args_list
            self.assertIn('本轮为回执补正', calls[1].args[0])
            self.assertIn('本轮为回执补正', calls[2].args[0])
            record = pipeline.execution_plan.read()['items'][0]
            self.assertIn(pipeline.execution_plan_file, calls[2].args[0])
            self.assertIsNone(pipeline._pending_receipt('code_review', 'R-001'))
            self.assertEqual(record['stage_attempts']['code_review'], 10)
            dev.send_message.assert_not_called()

    def test_bounded_receipt_survives_transport_failure_and_is_cleared_on_success(self):
        from agents import Agent
        from agents._result import AgentRunResult
        from task_protocol import TaskRetryRequired
        from unittest.mock import patch
        for stage in ('development', 'requirements_review', 'code_review', 'breakdown_review'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as root:
                pipeline = self.pipeline_fixture(root)
                item = None if stage == 'breakdown_review' else pipeline._load_items()[0]
                rid = item.requirement_id if item else None
                _, outputs, _ = pipeline._task_paths(stage, item)
                for output in outputs:
                    Path(output).write_text('formal evidence')
                with patch.object(Agent, '_load_system_prompt', return_value=''):
                    agent = Agent('test', 'unused.md', root, agent_type='cursor')
                agent.agent_impl = MagicMock()
                agent.agent_impl.run.return_value = AgentRunResult('receipt start ' + 'x' * 20000 + ' receipt end', None, 0)
                with self.assertRaises(TaskRetryRequired):
                    pipeline._send_task(agent, 'original task', stage, item)
                saved = pipeline._pending_receipt(stage, rid)
                self.assertEqual(len(saved['raw_receipt']), 4096)
                self.assertTrue(saved['raw_receipt'].startswith('receipt start'))
                self.assertTrue(saved['raw_receipt'].endswith('receipt end'))
                self.assertIn('已截断', saved['raw_receipt'])
                # run() raises before producing a result: no stale exit code or
                # previous turn's payload may be attributed to this invocation.
                agent.agent_impl.run.side_effect = RuntimeError('network ' + 'y' * 20000 + ' timeout')
                pipeline = BreakPipeline(root)
                with self.assertRaises(TaskRetryRequired):
                    pipeline._send_task(agent, 'original task', stage, item)
                pending = pipeline._pending_receipt(stage, rid)
                self.assertEqual(pending['raw_receipt'], saved['raw_receipt'])
                self.assertEqual(pending['receipt_error'], saved['receipt_error'])
                self.assertLessEqual(len(pending['last_error']), 1000)
                self.assertTrue(pending['last_error'].endswith('timeout'))
                state = pipeline.execution_plan._agent_session_target(pipeline.execution_plan.read(), rid)
                self.assertNotIn('exit_code', state['attempt_history'][stage][-1])
                agent.agent_impl.run.side_effect = None
                agent.agent_impl.run.return_value = AgentRunResult('FINAL_ANSWER ' + json.dumps(dict(
                    status='completed' if stage == 'development' else 'approved', summary='ok',
                    outputs={str(i): path for i, path in enumerate(outputs)})), None, 0)
                pipeline._send_task(agent, 'original task', stage, item)
                self.assertIsNone(pipeline._pending_receipt(stage, rid))
                self.assertNotIn('receipt start', Path(pipeline.execution_plan_file).read_text())
                self.assertFalse(list(Path(pipeline.requirements_dir).rglob('call-*.txt')))
                self.assertFalse(list(Path(pipeline.requirements_dir).rglob('review-result-*.txt')))
                self.assertFalse(list(Path(pipeline.requirements_dir).rglob('report-snapshot-*.txt')))

    def test_legacy_review_log_is_used_without_creating_new_log_files(self):
        from task_protocol import TaskRetryRequired
        with tempfile.TemporaryDirectory() as root:
            pipeline = self.pipeline_fixture(root)
            legacy = Path(pipeline.requirements_dir) / 'handoffs' / 'old-call.txt'
            legacy.parent.mkdir()
            legacy.write_text('original malformed receipt')
            plan = pipeline.execution_plan.read()
            plan['items'][0]['attempt_history'] = {'code_review': [dict(
                attempt=1, kind='receipt_format_error', log_path=str(legacy), receipt_error='old error')]}
            pipeline.execution_plan.write(plan)
            reviewer = MagicMock()
            reviewer.send_message.side_effect = RuntimeError('network timeout')
            with self.assertRaises(TaskRetryRequired):
                pipeline._send_task(reviewer, 'review', 'code_review', pipeline._load_items()[0])
            pipeline = BreakPipeline(root)
            reviewer.send_message.side_effect = None
            reviewer.send_message.return_value = 'FINAL_ANSWER {"status":"approved","summary":"ok"}'
            pipeline._send_task(reviewer, 'review', 'code_review', pipeline._load_items()[0])
            self.assertIn(str(legacy), reviewer.send_message.call_args.args[0])
            self.assertIn('old error', reviewer.send_message.call_args.args[0])
            self.assertEqual(legacy.read_text(), 'original malformed receipt')
            self.assertEqual(list(legacy.parent.iterdir()), [legacy])

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
            self.assertEqual(validate_receipt(reply + ' trailing text', task, root),
                             validate_receipt(reply, task, root))

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
            self.assertEqual(agent.last_run_result.text, 'plain text')
            self.assertFalse(list(Path(root).rglob('*.txt')))

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

    def test_requirements_review_keeps_decision_without_generic_snapshot(self):
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
            self.assertEqual(history, {'attempt': 1, 'kind': 'changes_requested'})
            self.assertFalse(list(Path(pipeline.requirements_dir).rglob('report-snapshot-*.txt')))
