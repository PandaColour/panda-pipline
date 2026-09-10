"""Explicit task contracts shared by the normal and split pipelines."""

import json
from pathlib import Path

from task_protocol import TaskMessage, ReceiptError, ReceiptPending, TaskRetryRequired, parse_final_answer, save_handoff, failure_kind

CALL_FAILURE = 'CALL_FAILURE '
REVIEW_STAGES = {'code_review', 'requirements_review', 'breakdown_review'}
TITLES = {
    'analysis': '分析当前需求并补全实现与验收方案',
    'development': '实现当前需求或依据审核报告返工，完成自测',
    'requirements_review': '评审当前需求分析的完整性、一致性及可实施性',
    'code_review': '验证并审查当前需求的实际代码、测试与交付证据',
    'breakdown': '拆分或增量修订大需求，形成有依赖顺序的小需求文档',
    'breakdown_review': '评审大需求拆分的范围、依赖、验收和上下文完整性',
    'normalize': '将需求索引规范化为执行计划，保留已有进度',
    'memory_analysis': '整理已验证的需求侧记忆',
    'memory_development': '整理已验证的实现侧记忆并写交接报告',
    'summary': '汇总所有需求的实现、证据、缺口和风险',
}


class PipelineTaskMixin:
    def _handoff(self, name, content):
        return '请读取文档：' + save_handoff(self.requirements_dir, name, str(content or ''))

    def _task_paths(self, stage, item):
        root = Path(self.requirements_dir)
        if item is not None:
            p = self._item_paths(item)
        elif hasattr(self, 'user_requirements_file'):
            p = dict(requirements=self.user_requirements_file,
                     requirements_analysis=self.user_requirements_file,
                     develop=self.develop_report_file, test=self.test_report_file,
                     code_review=self.code_review_file, bug=self.bug_report_file,
                     requirements_review=str(Path(self.requirement_dir) / 'requirement_review.md'),
                     memory_report=self.memory_report_file)
        else:
            p = {}
        inputs = [str(root / 'index.md'), str(root / 'shared_context.md'), self.execution_plan_file]
        input_keys = {
            'analysis': ('requirements', 'requirements_analysis', 'requirements_review', 'code_review'),
            'development': ('requirements', 'requirements_analysis', 'develop', 'code_review', 'bug'),
            'requirements_review': ('requirements', 'requirements_analysis', 'requirements_review'),
            'code_review': ('requirements', 'requirements_analysis', 'develop', 'test', 'code_review', 'bug'),
            'memory_analysis': ('requirements', 'requirements_analysis', 'requirements_review', 'code_review', 'test'),
            'memory_development': ('requirements', 'develop', 'test', 'code_review'),
        }.get(stage, ())
        inputs += list(dict.fromkeys(p[key] for key in input_keys if key in p))
        if item is None and stage == 'code_review':
            inputs.append(self.static_scan_report_file)
        outputs = {
            'analysis': [p.get('requirements_analysis', '')],
            'development': [p.get('develop', '')],
            'requirements_review': [p.get('requirements_review', '')],
            'code_review': [p.get('code_review', ''), p.get('test', '')],
            'breakdown': [str(root / 'index.md')],
            'breakdown_review': [str(root / 'split_review_report.json')],
            'normalize': [self.execution_plan_file],
            'memory_analysis': [str(Path(p.get('memory_report', root / 'memory_report.md')).parent / 'memory_analysis_report.md')],
            'memory_development': [p.get('memory_report', '')],
            'summary': [str(root / 'requirement_summary.md')],
        }[stage]
        optional = [p['bug']] if stage == 'code_review' else []
        return [x for x in inputs if x], [x for x in outputs if x], optional

    def _send_task(self, agent, instruction, stage, item=None):
        inputs, outputs, optional = self._task_paths(stage, item)
        instruction += ('\n输入清单是可用资料的定位：首轮尚未生成的历史报告不要求存在；'
                        '必需需求来源缺失必须如实处理，不能编造内容。'
                        '完整输出清单按本轮声明执行，报告正文不受回执 2048 字符限制。')
        reviewing = stage in REVIEW_STAGES
        statuses = {'approved', 'changes_requested', 'requirement_change'} if reviewing else {'completed'}
        if stage in {'breakdown', 'breakdown_review'} or (stage == 'analysis' and item is None):
            statuses.add('blocked')
            blocker_path = str(Path(outputs[0]).parent / 'resource_blocker.json')
            optional.append(blocker_path)
            instruction += ('\n本阶段若按既有规则返回 blocked，必须先写 ' + blocker_path
                            + '，内容为 JSON：kind、resource（原始完整 URL 或绝对路径）、reason、impact、required_user_action；'
                            '回执 outputs.blocker 指向此文件，summary 简述原因。')
        rid = item.requirement_id if item else (None if hasattr(self, 'requirement_summary_file') else 'R-001')
        if reviewing and not hasattr(self, 'requirement_summary_file'):
            if self.execution_plan.get_stage_attempt(stage, rid) >= 10:
                return CALL_FAILURE + '累计 10 次已耗尽'
            self.execution_plan.increment_stage_attempt(stage, rid)
        round_number = self.execution_plan.get_stage_attempt(stage, rid) if reviewing else None
        title = TITLES[stage]
        if item:
            title = f'{item.requirement_id}「{item.name}」：{title}'
        if reviewing:
            title += f'；第 {round_number} 次调用'
            instruction += '\n评审仅写入角色协议授权的报告/产物及共享条目，不修改业务源码。完整问题、稳定 issue ID、证据及修改要求写入审核报告。'
            correction_source = self._correction_source(stage, rid)
            if correction_source:
                instruction = ('本轮为回执补正：读取待补正回执的原始调用日志 ' + correction_source
                               + ' 和已有输出报告，只重发合规 FINAL_ANSWER；不得重新执行开发、测试或审核。')
                instruction += '\n待修正的校验错误：' + self._correction_error(stage, rid)
        task = TaskMessage(title, inputs, outputs, instruction, statuses,
                           root=self.work_dir, optional_outputs=optional)
        if not reviewing:
            return self._send_producer_task(agent, task, stage, rid, title, inputs, outputs, optional, statuses)
        try:
            response = agent.send_message(task)
            if reviewing:
                decision = parse_final_answer(response)
                if not isinstance(decision.get('status'), str) or decision['status'] not in statuses:
                    raise ReceiptError('审核回执 status 无效')
                self._record_attempt(stage, rid, decision['status'], response, outputs=outputs + optional)
            return response
        except RuntimeError as error:
            # A failed physical invocation is already charged by the caller.
            log_path = getattr(agent, 'last_log_path', None)
            if not isinstance(log_path, str):
                log_path = save_handoff(self.requirements_dir, 'call-error', str(error))
            kind = failure_kind(error)
            self._record_attempt(stage, rid, kind, str(error), log_path, outputs=outputs + optional)
            raise TaskRetryRequired(
                f'{rid or "总体需求"} / {stage} 第 {round_number} 次调用失败（{kind}）；'
                f'调用日志：{log_path}；恢复记录：{self.execution_plan_file}'
            ) from error

    def _pending_receipt(self, stage, rid):
        if not Path(self.execution_plan_file).is_file():
            return None
        plan = self.execution_plan.read()
        target = plan.get('demand', {}) if rid is None else self.execution_plan._agent_session_target(plan, rid)
        return target.get('pending_receipts', {}).get(stage)

    def _save_pending_receipt(self, stage, rid, pending):
        plan = self.execution_plan.read() if Path(self.execution_plan_file).is_file() else dict(demand={}, items=[])
        target = plan.setdefault('demand', {}) if rid is None else self.execution_plan._agent_session_target(plan, rid)
        records = target.setdefault('pending_receipts', {})
        if pending is None:
            records.pop(stage, None)
        else:
            records[stage] = pending
        self.execution_plan.write(plan)

    def _send_producer_task(self, agent, task, stage, rid, title, inputs, outputs, optional, statuses):
        pending = self._pending_receipt(stage, rid)
        original_task = task
        if pending:
            # Legacy records without a mode are receipt-only corrections.
            resuming_execution = pending.get('mode') == 'execution'
            instruction = (
                '上次执行失败。读取原始任务和调用日志，核实已写产物，继续未完成的工作；'
                '原任务要求仍有效，不重复已完成且有有效证据的工作，不凭日志中的完成声明跳过验收。'
                if resuming_execution else
                '仅根据调用日志和已生成报告重发合规 FINAL_ANSWER，不重新执行本轮业务任务。'
                '先核对原始任务与必需输出；不得编造完成状态或证据。'
            )
            task = TaskMessage(title + ('；恢复执行' if resuming_execution else '；回执补正'),
                inputs + [pending['log_path'], pending['task_path']], outputs,
                instruction + '\n上次失败原因：' + str(pending.get('last_error', '见原始调用日志'))[:1000],
                statuses, root=self.work_dir, optional_outputs=optional)
        if not Path(self.execution_plan_file).is_file():
            if hasattr(self, 'user_requirements_file'):
                self._ensure_execution_plan()
            else:
                self._set_demand_status('拆分中')
        attempt = self.execution_plan.increment_stage_attempt(stage, rid)
        normalization_state = self.execution_plan.read() if stage == 'normalize' else None
        try:
            response = agent.send_message(task)
        except RuntimeError as error:
            if normalization_state is not None:
                self.execution_plan.write(normalization_state)
            kind = failure_kind(error)
            log_path = getattr(agent, 'last_log_path', None)
            if not isinstance(log_path, str):
                log_path = save_handoff(self.requirements_dir, 'call-error', str(error))
            if pending is None:
                pending = dict(log_path=log_path, mode='execution',
                    task_path=save_handoff(self.requirements_dir, 'producer-task', str(original_task)))
            if isinstance(error, ReceiptError):
                pending['mode'] = 'receipt'
            pending['last_error'] = str(error)[:1000] if isinstance(error, ReceiptError) else kind
            pending['last_error_log'] = log_path
            self._save_pending_receipt(stage, rid, pending)
            self._record_attempt(stage, rid, kind, str(error), log_path, outputs=outputs + optional)
            stopped = ReceiptPending if pending.get('mode', 'receipt') == 'receipt' else TaskRetryRequired
            raise stopped(
                f'{rid or "总体需求"} / {stage} 第 {attempt} 次调用失败（{kind}）；'
                f'调用日志：{log_path}；恢复记录：{self.execution_plan_file}'
            ) from error
        if normalization_state is not None:
            plan = self.execution_plan.read()
            self.execution_plan.normalize_plan(plan, None)
            for field in ('stage_attempts', 'attempt_history', 'pending_receipts'):
                if field in normalization_state['demand']:
                    plan['demand'][field] = normalization_state['demand'][field]
            self.execution_plan.write(plan)
        self._record_attempt(stage, rid, 'success', str(response), outputs=outputs + optional)
        self._save_pending_receipt(stage, rid, None)
        return response

    def _last_attempt(self, stage, rid):
        target = self.execution_plan._agent_session_target(self.execution_plan.read(), rid)
        history = target.get('attempt_history', {}).get(stage, [])
        return history[-1] if history else None

    def _correction_source(self, stage, rid):
        target = self.execution_plan._agent_session_target(self.execution_plan.read(), rid)
        source = None
        for attempt in reversed(target.get('attempt_history', {}).get(stage, [])):
            if attempt['kind'] in {'approved', 'changes_requested', 'requirement_change', 'blocked'}:
                break
            if attempt['kind'] == 'receipt_format_error':
                source = attempt['log_path']
        return source

    def _record_attempt(self, stage, rid, kind, detail, log_path=None, outputs=()):
        plan = self.execution_plan.read()
        target = self.execution_plan._agent_session_target(plan, rid)
        log_path = log_path or save_handoff(self.requirements_dir, 'review-result', detail)
        target.setdefault('attempt_history', {}).setdefault(stage, []).append(dict(
            attempt=target.get('stage_attempts', {}).get(stage, 0), kind=kind, log_path=log_path,
            **({'receipt_error': str(detail)[:1000]} if kind == 'receipt_format_error' else {}),
            outputs={path: save_handoff(self.requirements_dir, 'report-snapshot', Path(path).read_text(encoding='utf-8'))
                     for path in outputs if Path(path).is_file()},
        ))
        self.execution_plan.write(plan)

    def _correction_error(self, stage, rid):
        target = self.execution_plan._agent_session_target(self.execution_plan.read(), rid)
        for attempt in reversed(target.get('attempt_history', {}).get(stage, [])):
            if attempt['kind'] in {'approved', 'changes_requested', 'requirement_change', 'blocked'}:
                break
            if attempt['kind'] == 'receipt_format_error':
                return attempt.get('receipt_error', '见原始调用日志；按当前回执协议补正')
        return '见原始调用日志；按当前回执协议补正'
