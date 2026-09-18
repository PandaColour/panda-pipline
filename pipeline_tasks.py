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


def android_device_instruction(stage):
    if stage not in {'development', 'code_review'}:
        return '\n本阶段不启动模拟器，不调用设备启动脚本；启动仅授权开发和 Code Review。'
    return (
        '\n【本轮 Android 设备规则，覆盖旧会话中的启停规定】仅当前 AC 需要 Android 设备验证时：'
        '先读取 panda-pipeline-android-device-validation/SKILL.md，将命令工作目录设为该 SKILL.md 所在目录，'
        '调用 `python3 scripts/android_emulator.py ensure --timeout 180 --prepare-timeout 1800` 统一选择真机或模拟器；'
        '每轮实际设备验证重新默认选择，优先唯一在线真机，无在线真机才复用唯一在线模拟器；多台在线真机用 --serial 选择真机，仅多台在线模拟器时用 --serial 或 --avd 明确选择，两者互斥。不得沿用历史模拟器 ID 绕过真机优先；确需固定模拟器视觉基线时说明理由后明确指定。真机恢复后下一轮切回，执行中的测试不中途切换；断线后重新选择并重跑受影响测试，分别记录证据。真机离线/未授权/拔出不等待，立即降级到其他可用设备，无可用设备才准备模拟器；模拟器 offline 不重复创建。'
        '仅项目明确限制 API 时加 --api；--device 仅为 AVD profile。设备基线一起传 --width <设备像素宽px> --height <设备像素高px> --density <设备dpi>；px=dp×dpi/160。目标 375×812 dp、320 dpi 应传 --width 750 --height 1624 --density 320，误传 375/812 得到 187.5×406 dp。参考图 1×/2× 导出倍率不决定设备规格，不照抄画板数值或导出图像素，不把长滚动图当屏高。新 AVD 使用规格；已连接设备不匹配只报告，未启动 AVD 不匹配报错且不覆盖。不得改真机分辨率/密度。'
        '缺 SDK 工具、Emulator、镜像和 AVD 均由 Python 下载或创建。新建省略规格默认 API 35/pixel_6，不能代替项目要求。'
        '脚本识别宿主，首版 macOS 使用 launchd 与 caffeinate -i，独立日志及防空闲休眠；'
        '其他系统或调用失败如实记录并继续可控验证，不绕过脚本。'
        '准备默认 1800 秒、启动 180 秒；外层超时至少 3900 秒（含锁等待），工具支持时可异步执行并轮询脚本回执。退出码 0 且 status=ready 后用最终 adb_args 数组或 adb_path 加 -s serial，不复用失效 ID；avd 是名称。记录 device_type、api、screen 的实际规格/字体缩放、target_logical_width_dp/height_dp 请求逻辑尺寸、matches_target/differences/warnings及 selection.fallback_reason。matches_target=false 先核对请求/实际逻辑尺寸及单位，不自动换机或判 UI 失败；true 也不代表视觉通过。失败按 stage/error 和日志处理，serial=null 不继续设备命令。后续 adb 硬超时；Java/许可缺口如实披露，不自行绕过。'
        '禁止直接 emulator/nohup/tee/后台 Shell/子代理启动；返回后不等待模拟器结束，验证后保留实例，'
        '不执行 stop/emu kill/pkill。Code Review 可按增量范围补验，不自行创建 AVD、不修改源码/测试。'
    )


class PipelineTaskMixin:
    def _render_command(self, command_file, **values):
        """Fill a task command for an existing Agent; its role prompt stays intact."""
        from pipeline_skills import command_template_text
        template = command_template_text(self.work_dir, Path(self.command_dir) / command_file)
        try:
            return template.format(**values)
        except KeyError as error:
            raise ValueError(
                f"Command template {command_file} missing placeholder value: {error.args[0]}"
            ) from error

    def _handoff_directory(self, item=None):
        return self._item_paths(item)['workspace'] if item is not None else self.requirements_dir

    def _handoff(self, name, content, item=None):
        return '请读取文档：' + save_handoff(self._handoff_directory(item), name, str(content or ''))

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
            'development': ('requirements_analysis', 'develop', 'code_review', 'bug'),
            'requirements_review': ('requirements', 'requirements_analysis', 'requirements_review'),
            'code_review': ('requirements_analysis', 'develop', 'test', 'code_review', 'bug'),
            'memory_analysis': ('requirements', 'requirements_analysis', 'requirements_review', 'code_review', 'test'),
            'memory_development': ('requirements', 'develop', 'test', 'code_review'),
        }.get(stage, ())
        inputs += list(dict.fromkeys(p[key] for key in input_keys if key in p))
        if stage in {'analysis', 'development', 'requirements_review', 'code_review'} and p.get('requirements'):
            inputs += [str(root / '_figma_inventory.json'),
                       str(Path(p['requirements']).parent / 'figma_assets' / 'asset_manifest.json')]
        elif stage in {'breakdown', 'breakdown_review'}:
            inputs.append(str(root / '_figma_inventory.json'))
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
        instruction += android_device_instruction(stage)
        instruction += ('\n输入清单是可用资料的定位：首轮尚未生成的历史报告不要求存在；'
                        '必需需求来源缺失必须如实处理，不能编造内容。'
                        '执行计划按本项及直接依赖选择相关字段；handoffs/、attempt_history 和会话日志不默认全文读取。'
                        '本轮指定的恢复记录、复审交接及其必要证据必须读取；其他历史仅在定位具体失败、矛盾或缺口时定点追溯。'
                        '完整输出清单按本轮声明执行，报告正文不受回执 2048 字符限制。')
        if stage in {'analysis', 'development', 'requirements_review', 'code_review', 'breakdown', 'breakdown_review'}:
            instruction += ('\n涉及 Figma 时，从 shared_context.md 的物料入口和本项 figma_assets/asset_manifest.json '
                            '读取原件、参考图与 frames[].design_source；清单内路径以本项需求目录为基准。'
                            'schema_version: 3 的 manifest 是物料映射的唯一维护入口，正文只引用，不靠全文搜索找素材。'
                            '无关平台或非 Figma 需求不要求这些文件；新建或补充物料按角色协议准备索引，'
                            '未修改旧版按兼容规则核对，新增或补充物料时合并升级并如实保留缺口，不能仅改版本号，也不能因存在旧审计 passed 就省略设计源检查。')
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
                instruction = ('本轮为回执补正：读取本阶段 pending_receipts 中的待补正回执或旧调用日志：' + correction_source
                               + ' 和已有输出报告，只重发合规 FINAL_ANSWER；不得重新执行开发、测试或审核，不启动模拟器。')
                instruction += f'\n执行计划定位：{rid or "demand"} / pending_receipts.{stage}；截断片段不能作为完成证据。'
                instruction += '\n待修正的校验错误：' + self._correction_error(stage, rid)
        task = TaskMessage(title, inputs, outputs, instruction, statuses,
                           root=self.work_dir, optional_outputs=optional)
        if not reviewing:
            return self._send_producer_task(agent, task, stage, rid, title, inputs, outputs, optional, statuses, item=item)
        for correction in (False, True):
            response = None
            try:
                response = agent.send_message(task)
                decision = parse_final_answer(response)
                if not isinstance(decision.get('status'), str) or decision['status'] not in statuses:
                    raise ReceiptError('审核回执 status 无效')
                self._record_attempt(stage, rid, decision['status'])
                self._save_pending_receipt(stage, rid, None)
                return response
            except RuntimeError as error:
                # The initial review is charged by the caller; charge a local
                # correction separately, without exceeding the review budget.
                kind = failure_kind(error)
                pending = self._record_failure(stage, rid, agent, error, response=response)
                if not correction and self._can_correct_receipt(agent, error, stage, rid):
                    round_number = self.execution_plan.increment_stage_attempt(stage, rid)
                    task = self._receipt_correction_task(task, stage, rid)
                    continue
                raise TaskRetryRequired(
                    f'{rid or "总体需求"} / {stage} 第 {round_number} 次调用失败（{kind}）：'
                    f'{pending["last_error"]}；恢复记录：{self.execution_plan_file}'
                ) from error

    def _can_correct_receipt(self, agent, error, stage, rid):
        exit_code = getattr(getattr(agent, 'last_run_result', None), 'returncode', None)
        return (isinstance(error, ReceiptError) and type(exit_code) is int and exit_code == 0
                and (stage not in REVIEW_STAGES or self.execution_plan.get_stage_attempt(stage, rid) < 10))

    def _receipt_correction_task(self, task, stage, rid):
        print(f'⚠️ {rid or "总体需求"} / {stage}：进程退出码为 0，仅回执不合规；就地补正一次。')
        pending = self._pending_receipt(stage, rid) or {}
        return TaskMessage(
            f'{TITLES[stage]}；回执补正',
            [self.execution_plan_file] + task.outputs
            + [pending[key] for key in ('log_path', 'task_path') if pending.get(key)],
            task.outputs,
            '本轮为回执补正：只读取已有报告并核对必需产物，只重发合规 FINAL_ANSWER；'
            '不得重新执行开发、测试或审核，不启动模拟器，不编造完成状态或证据。'
            f'\n执行计划定位：{rid or "demand"} / pending_receipts.{stage}；截断片段不能作为完成证据。'
            '\n待修正的校验错误：' + self._correction_error(stage, rid),
            task.statuses, root=self.work_dir, optional_outputs=task.optional_outputs)

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

    @staticmethod
    def _bounded_detail(text, limit=1000):
        text = str(text)
        if len(text) <= limit:
            return text
        marker = '\n…[已截断，仅保留首尾]…\n'
        head = (limit - len(marker)) // 2
        return text[:head] + marker + text[-(limit - len(marker) - head):]

    def _record_failure(self, stage, rid, agent, error, *, original_task=None, response=None, item=None):
        pending = self._pending_receipt(stage, rid) or dict(mode='execution')
        if original_task is not None and not pending.get('task_path'):
            pending['task_path'] = save_handoff(self._handoff_directory(item), 'producer-task', str(original_task))
        detail = self._bounded_detail(error)
        pending['last_error'] = detail
        result = getattr(agent, 'last_run_result', None)
        if isinstance(error, ReceiptError):
            pending.update(mode='receipt', receipt_error=detail)
            raw = response if isinstance(response, str) else getattr(result, 'text', None)
            if isinstance(raw, str):
                pending['raw_receipt'] = self._bounded_detail(raw, 4096)
        # A transport failure during receipt correction must not discard the
        # previous receipt/error. Existing log_path/task_path remain readable.
        self._save_pending_receipt(stage, rid, pending)
        self._record_attempt(stage, rid, failure_kind(error), detail,
                             exit_code=getattr(result, 'returncode', None))
        return pending

    def _send_producer_task(self, agent, task, stage, rid, title, inputs, outputs, optional, statuses, item=None):
        pending = self._pending_receipt(stage, rid)
        original_task = task
        if pending:
            # Legacy records without a mode are receipt-only corrections.
            resuming_execution = pending.get('mode') == 'execution'
            instruction = (
                '上次执行失败。读取原始任务和恢复记录，核实已写产物，继续未完成的工作；'
                '原任务要求仍有效，不重复已完成且有有效证据的工作，不凭日志中的完成声明跳过验收。'
                if resuming_execution else
                '仅根据恢复记录（待补正回执或旧调用日志）和已生成报告重发合规 FINAL_ANSWER，不重新执行本轮业务任务。'
                '先核对原始任务与必需输出；不得编造完成状态或证据。'
            )
            instruction += android_device_instruction(stage if resuming_execution else 'receipt')
            task = TaskMessage(title + ('；恢复执行' if resuming_execution else '；回执补正'),
                inputs + [pending[key] for key in ('log_path', 'task_path') if pending.get(key)], outputs,
                instruction + f'\n读取执行计划中 {rid or "demand"} 的 pending_receipts.{stage}；截断片段不能作为完成证据。'
                + '\n上次失败原因：' + str(pending.get('receipt_error') or pending.get('last_error', '见旧调用日志'))[:1000],
                statuses, root=self.work_dir, optional_outputs=optional)
        if not Path(self.execution_plan_file).is_file():
            if hasattr(self, 'user_requirements_file'):
                self._ensure_execution_plan()
            else:
                self._set_demand_status('拆分中')
        attempt = self.execution_plan.increment_stage_attempt(stage, rid)
        normalization_state = self.execution_plan.read() if stage == 'normalize' else None
        for correction in (False, True):
            try:
                response = agent.send_message(task)
                break
            except RuntimeError as error:
                if normalization_state is not None:
                    # The plan is also this stage's output. A malformed receipt
                    # must not undo valid work before receipt-only correction.
                    if self._can_correct_receipt(agent, error, stage, rid):
                        try:
                            self._merge_normalization_metadata(normalization_state)
                        except (ValueError, TypeError, KeyError, OSError):
                            self.execution_plan.write(normalization_state)
                    else:
                        self.execution_plan.write(normalization_state)
                kind = failure_kind(error)
                pending = self._record_failure(stage, rid, agent, error, original_task=original_task, item=item)
                if not correction and self._can_correct_receipt(agent, error, stage, rid):
                    attempt = self.execution_plan.increment_stage_attempt(stage, rid)
                    task = self._receipt_correction_task(task, stage, rid)
                    normalization_state = self.execution_plan.read() if stage == 'normalize' else None
                    continue
                stopped = ReceiptPending if pending.get('mode', 'receipt') == 'receipt' else TaskRetryRequired
                raise stopped(
                    f'{rid or "总体需求"} / {stage} 第 {attempt} 次调用失败（{kind}）；'
                    f'{pending["last_error"]}；恢复记录：{self.execution_plan_file}'
                ) from error
        if normalization_state is not None:
            self._merge_normalization_metadata(normalization_state)
        self._save_pending_receipt(stage, rid, None)
        return response

    def _merge_normalization_metadata(self, state):
        plan = self.execution_plan.read()
        if not isinstance(plan, dict):
            raise ValueError('执行计划必须为 JSON 对象')
        self.execution_plan.normalize_plan(plan, None)
        for field in ('stage_attempts', 'attempt_history', 'pending_receipts'):
            if field in state['demand']:
                plan['demand'][field] = state['demand'][field]
        self.execution_plan.write(plan)

    def _last_attempt(self, stage, rid):
        target = self.execution_plan._agent_session_target(self.execution_plan.read(), rid)
        history = target.get('attempt_history', {}).get(stage, [])
        return history[-1] if history else None

    def _correction_source(self, stage, rid):
        pending = self._pending_receipt(stage, rid)
        if pending and pending.get('mode', 'receipt') == 'receipt':
            return pending.get('log_path') or self.execution_plan_file
        target = self.execution_plan._agent_session_target(self.execution_plan.read(), rid)
        source = None
        for attempt in reversed(target.get('attempt_history', {}).get(stage, [])):
            if attempt['kind'] in {'approved', 'changes_requested', 'requirement_change', 'blocked'}:
                break
            if attempt['kind'] == 'receipt_format_error':
                source = attempt.get('log_path') or self.execution_plan_file
        return source

    def _record_attempt(self, stage, rid, kind, detail='', *, exit_code=None):
        plan = self.execution_plan.read()
        target = self.execution_plan._agent_session_target(plan, rid)
        entry = dict(attempt=target.get('stage_attempts', {}).get(stage, 0), kind=kind)
        if kind not in {'approved', 'changes_requested', 'requirement_change', 'blocked'}:
            entry['error'] = self._bounded_detail(detail)
            if type(exit_code) is int:
                entry['exit_code'] = exit_code
        target.setdefault('attempt_history', {}).setdefault(stage, []).append(entry)
        self.execution_plan.write(plan)

    def _correction_error(self, stage, rid):
        pending = self._pending_receipt(stage, rid)
        if pending and pending.get('receipt_error'):
            return pending['receipt_error']
        target = self.execution_plan._agent_session_target(self.execution_plan.read(), rid)
        for attempt in reversed(target.get('attempt_history', {}).get(stage, [])):
            if attempt['kind'] in {'approved', 'changes_requested', 'requirement_change', 'blocked'}:
                break
            if attempt['kind'] == 'receipt_format_error':
                return attempt.get('receipt_error') or attempt.get('error', '见旧调用日志；按当前回执协议补正')
        return '见原始调用日志；按当前回执协议补正'
