from pipeline_tasks import PipelineTaskMixin, CALL_FAILURE
"""Large-requirement breakdown and per-item delivery workflow."""

import ntpath
import json
import os
import posixpath
from dataclasses import dataclass
from datetime import datetime

from agents import Agent
from config import get_agent_type
from execution_plan import ExecutionPlanStore
from review_decision import review_passed, structured_final_answer_decision, structured_review_decision
from review_context import CodeReviewContext, DEVELOPMENT_HANDOFF
from workflow import human_gate
from task_protocol import read_resource_blocker
from workflow_blockers import (
    REVIEW_EXHAUSTED, SUSPENDED_STATUSES,
    STAGE_RESULT_INSTRUCTION, external_blocker,
)


BREAK_SYSTEM_PROMPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "break-system-prompt")
MEMORY_CURATION_PROMPT = "memory_curation.md"
REQUIREMENT_SUMMARY_PROMPT = "requirement_summary.md"
MAX_STAGE_ATTEMPTS = 10
ITEM_AGENT_BATCH_SIZE = 5
VALID_STATUSES = SUSPENDED_STATUSES | {
    "待审核",
    "需求分析中",
    "需求评审中",
    "待需求人工确认",
    "待开发",
    "开发中",
    "代码评审中",
    "待人工确认",
    "记忆整理中",
    "已完成",
    "阻塞",
}


@dataclass
class RequirementItem:
    order: int
    requirement_id: str
    name: str
    status: str
    dependencies: list[str]
    filename: str
    acceptance: str
    execution_sequence: int | None = None


class BreakPipeline(PipelineTaskMixin):
    """Break a large request down, then deliver its approved items in order."""

    def __init__(self, work_dir, skip_human=False):
        self.work_dir = os.path.abspath(work_dir)
        self.skip_human = skip_human
        self.requirements_dir = os.path.join(self.work_dir, "requirements")
        self.requirements_index_file = os.path.join(self.requirements_dir, "index.md")
        self.execution_plan = ExecutionPlanStore(self.requirements_dir, self.requirements_index_file)
        self.execution_plan_file = self.execution_plan.plan_file
        self.breakdown_approval_file = os.path.join(self.requirements_dir, ".breakdown-approved")
        self.requirement_summary_file = os.path.join(self.requirements_dir, "requirement_summary.md")
        self.prompt_dir = BREAK_SYSTEM_PROMPT_DIR
        self.agents = {}
        self._active_item_agents = {}
        self._active_agent_requirements = {}
        self._pending_human_feedback = {}
        self._pending_requirement_feedback = {}
        self._logged_item_starts = set()
        self._logged_item_completions = set()

    def _human_gate(self, stage_name, review_file_path=None, feedback_agent=None):
        gate_options = {"skip_human": self.skip_human}
        if feedback_agent is not None:
            gate_options["feedback_target"] = feedback_agent.display_name
        return human_gate(stage_name, review_file_path, **gate_options)

    def has_resumable_state(self):
        return any(
            os.path.isfile(path)
            for path in (
                self.requirements_index_file,
                self.execution_plan_file,
                self.breakdown_approval_file,
            )
        )

    def _create_agent(self, name, prompt_file, role):
        agent_type = get_agent_type(role)
        session_id = self._agent_session_id(name, agent_type)
        agent = Agent(
            name,
            prompt_file,
            self.work_dir,
            add_dirs=None,
            agent_type=agent_type,
            prompt_dir=self.prompt_dir,
            session_id=session_id,
            session_update_callback=lambda new_session_id: self._set_agent_session(
                name,
                prompt_file,
                agent_type,
                new_session_id,
            ),
            status_provider=lambda: self._agent_status(name),
            call_scope_provider=lambda: self._active_agent_requirements.get(name),
        )
        self.agents[name] = agent
        return agent

    def _agent_status(self, agent_name):
        try:
            plan = self.execution_plan.read()
        except (OSError, ValueError):
            return None

        requirement_id = self._active_agent_requirements.get(agent_name)
        requirement_id = requirement_id or self._agent_requirement_id(agent_name)
        if requirement_id:
            status = next(
                (
                    item.get("status")
                    for item in plan.get("items", [])
                    if isinstance(item, dict) and item.get("id") == requirement_id
                ),
                None,
            )
        else:
            status = plan.get("demand", {}).get("status")

        status = ExecutionPlanStore.normalize_status(status, VALID_STATUSES)
        if status not in VALID_STATUSES:
            return None
        return f"{requirement_id} · {status}" if requirement_id else status

    def _render_break_prompt(self, prompt_file, **values):
        template_path = os.path.join(self.prompt_dir, prompt_file)
        with open(template_path, encoding="utf-8") as template_file:
            template = template_file.read()
        try:
            return template.format(**values)
        except KeyError as error:
            missing_key = error.args[0]
            raise ValueError(f"Prompt template {prompt_file} missing placeholder value: {missing_key}") from error

    def _agent_session_id(self, agent_name, agent_type):
        try:
            return self.execution_plan.get_agent_session(
                agent_name,
                requirement_id=self._agent_requirement_id(agent_name),
                agent_type=agent_type,
            )
        except ValueError:
            return None

    def _set_agent_session(self, agent_name, prompt_file, agent_type, session_id):
        if session_id is None:
            self.execution_plan.clear_agent_session(
                agent_name, requirement_id=self._agent_requirement_id(agent_name)
            )
            return
        try:
            self.execution_plan.set_agent_session(
                agent_name,
                session_id=session_id,
                prompt_file=prompt_file,
                agent_type=agent_type,
                requirement_id=self._agent_requirement_id(agent_name),
            )
        except ValueError:
            return

    @staticmethod
    def _agent_requirement_id(agent_name):
        if not isinstance(agent_name, str):
            return None
        requirement_id = agent_name.split(" ", 1)[0]
        return requirement_id if requirement_id.startswith("R-") else None

    def _item_agents(self, item):
        """Reuse one complete four-agent set for each five-item batch."""
        batch_key = self._item_agent_batch_key(item)
        if batch_key not in self._active_item_agents:
            prefix = batch_key
            self._active_item_agents[batch_key] = {
                "analyst": self._create_agent(
                    f"{prefix} 小需求需求分析",
                    "item_requirements_analyst.md",
                    "requirements_analyst",
                ),
                "requirements_reviewer": self._create_agent(
                    f"{prefix} 小需求需求评审",
                    "item_requirements_reviewer.md",
                    "requirements_reviewer",
                ),
                "developer": self._create_agent(
                    f"{prefix} 小需求开发",
                    "item_developer.md",
                    "developer",
                ),
                "code_reviewer": self._create_agent(
                    f"{prefix} 小需求验证审查",
                    "item_code_reviewer.md",
                    "code_reviewer",
                ),
            }
        return self._active_item_agents[batch_key]

    @staticmethod
    def _item_agent_batch_key(item):
        if item.execution_sequence is None:
            raise ValueError(f"需求 {item.requirement_id} 尚未分配实际执行序号。")
        batch_start = (
            (item.execution_sequence - 1) // ITEM_AGENT_BATCH_SIZE
        ) * ITEM_AGENT_BATCH_SIZE + 1
        return f"批次-{batch_start:03d}"

    def _release_item_agents(self, batch_key):
        """Release a five-item agent batch after its final memory checkpoint."""
        item_agents = self._active_item_agents.pop(batch_key, {})
        for agent in item_agents.values():
            self._active_agent_requirements.pop(agent.name, None)
            self.agents.pop(agent.name, None)

    def _bind_item_agents(self, item, item_agents):
        for agent in item_agents.values():
            self._active_agent_requirements[agent.name] = item.requirement_id

    @staticmethod
    def _log_current_item(item):
        execution_sequence = item.execution_sequence or "未分配"
        print(
            f"\n📌 当前处理小需求: {item.requirement_id} {item.name}"
            f"（拆分顺序 {item.order}，实际执行序号 {execution_sequence}）"
            f"— 当前阶段: {item.status}"
        )

    @staticmethod
    def _current_timestamp():
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _format_duration(started_at, completed_at):
        total_seconds = max(
            0,
            int((datetime.fromisoformat(completed_at) - datetime.fromisoformat(started_at)).total_seconds()),
        )
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        prefix = f"{days}天 " if days else ""
        return f"{prefix}{hours:02d}小时 {minutes:02d}分 {seconds:02d}秒"

    def _start_item(self, item):
        if item.requirement_id in self._logged_item_starts:
            return
        started_at = self.execution_plan.set_item_started(
            item.requirement_id,
            self._current_timestamp(),
        )
        self._logged_item_starts.add(item.requirement_id)
        separator = "=" * 60
        print(
            f"\n{separator}\n"
            f"🚀 【小需求开始】{item.requirement_id} {item.name}"
            f"（拆分顺序 {item.order}，实际执行序号 {item.execution_sequence}）\n"
            f"开始时间: {started_at}\n"
            f"{separator}"
        )

    def _complete_item(self, item):
        if item.requirement_id in self._logged_item_completions:
            return
        started_at, completed_at = self.execution_plan.complete_item(
            item.requirement_id,
            self._current_timestamp(),
            VALID_STATUSES,
        )
        self._logged_item_completions.add(item.requirement_id)
        separator = "=" * 60
        print(
            f"\n{separator}\n"
            f"✅ 【小需求结束】{item.requirement_id} {item.name}"
            f"（拆分顺序 {item.order}，实际执行序号 {item.execution_sequence}）\n"
            f"开始时间: {started_at}\n"
            f"完成时间: {completed_at}\n"
            f"耗时: {self._format_duration(started_at, completed_at)}\n"
            f"{separator}"
        )

    def run(self, user_idea=None):
        if os.path.isfile(self.execution_plan_file):
            demand = self.execution_plan.read().get('demand', {})
            if demand.get('status') == REVIEW_EXHAUSTED:
                print('⚠️ 拆分评审未通过且已达上限；保持暂停，不使用旧批准进入开发。')
                return False
        if user_idea is not None:
            if self._run_breakdown(user_idea) is False:
                return False
        elif not os.path.isfile(self.breakdown_approval_file):
            if self._run_breakdown() is False:
                return False
        if self._run_execution():
            if self._active_requirements_complete():
                self._set_demand_status("记忆整理中")
            self._run_final_reflection()
            if self._active_requirements_complete():
                self._validate_requirement_summary()
                self._set_demand_status("已完成")
                self._archive_completed_requirements()
            print("\n🎉🎉🎉 【拆分流水线圆满完成】所有小需求均已通过！")
            return True
        return False

    def _normalize_item_response(self, item, stage, response):
        details = external_blocker(response)
        if details is None:
            return response
        self.execution_plan.record_continuation(item.requirement_id, stage, response, details)
        print(f"⚠️ {item.requirement_id} 返回旧 blocked；记录缺口，按降级策略继续，不挂起。")
        return 'FINAL_ANSWER ' + json.dumps(dict(
            status='changes_requested', approval_token='',
            summary='小需求不能 blocked，请按降级策略完成可控实现/验证并记录剩余缺口。原反馈已保存到 continuation_notes。'),
            ensure_ascii=False)

    def _continuation_context(self, item):
        records = self.execution_plan.read().get('items', [])
        selected = [record for record in records if record['id'] in {item.requirement_id, *item.dependencies}]
        context = []
        for record in selected:
            details = {key: record[key] for key in ('review_outcomes', 'continuation_notes', 'suspension_history', 'suspension')
                       if record.get(key)}
            if details:
                context.append(dict(id=record['id'], status=record['status'], details=details))
        if not context:
            return ''
        return ('\n当前项/上游未决事实（调度放行不等于验收通过）：' + self._handoff('continuation-context', json.dumps(context, ensure_ascii=False))
                + '\n检查上游已有代码、接口和报告，按已有降级策略与可替换边界推进；不得盲目信任上游已通过或伪造真实结果。')

    def _exhaust_stage(self, requirement_id, stage, response='已达到累计 10 次上限'):
        key = {'拆分评审中': 'breakdown_review', '需求评审中': 'requirements_review', '代码评审中': 'code_review'}[stage]
        history = self.execution_plan._agent_session_target(self.execution_plan.read(), requirement_id).get('attempt_history', {}).get(key, [])
        if history:
            counts = {}
            for entry in history:
                counts[entry['kind']] = counts.get(entry['kind'], 0) + 1
            response = json.dumps(dict(counts=counts, last_attempt=history[-1]), ensure_ascii=False)
        if requirement_id is None:
            self.execution_plan.suspend(None, REVIEW_EXHAUSTED, stage,
                                        dict(reason='达到 10 次上限，仍未通过', last_feedback=str(response)))
            print('⚠️ 大需求拆分未通过：暂停拆分，不批准进入开发。')
            return
        self.execution_plan.record_review_limit(requirement_id, stage, response)
        print(f"⚠️ {requirement_id} {stage}达到上限：记录未通过，继续下一阶段/需求，不伪造批准。")

    @staticmethod
    def _breakdown_resource_blocker(response, work_dir=None):
        if not isinstance(response, str):
            return None
        decision = structured_final_answer_decision(response, {"blocked"})
        if decision is None:
            return None
        blocker = decision.get("blocker")
        if blocker is None and work_dir:
            blocker = read_resource_blocker(decision, work_dir)
        if not isinstance(blocker, dict):
            return None
        if blocker.get("kind") not in {"file_unreadable", "material_permission_denied"}:
            return None
        if not all(
            isinstance(blocker.get(field), str) and blocker[field].strip()
            for field in ("resource", "reason", "required_user_action")
        ):
            return None
        return {**blocker, "summary": decision.get("summary")}

    def _resolve_breakdown_resource_blocker(self, breaker, response):
        while blocker := self._breakdown_resource_blocker(response, self.work_dir):
            summary = blocker.get("summary") or blocker.get("reason") or "拆分所需资源不可访问"
            print(
                "⚠️ 拆分资源访问阻塞："
                f"资源={blocker.get('resource') or '未提供'}；"
                f"原因={blocker.get('reason') or '未提供'}；"
                f"需要用户处理={blocker.get('required_user_action') or '未提供'}"
            )
            feedback = human_gate(
                f"1. 大需求拆分资源访问阻塞：{summary}",
                self.requirements_index_file,
                skip_human=False,
                feedback_target=breaker.display_name,
            )
            while feedback is None:
                print("⚠️ 请提供资源处理结果后再继续拆分。")
                feedback = human_gate(
                    f"1. 大需求拆分资源访问阻塞：{summary}",
                    self.requirements_index_file,
                    skip_human=False,
                    feedback_target=breaker.display_name,
                )
            response = self._send_task(breaker, f"用户已处理资源访问阻塞：{self._handoff('feedback', feedback)}\n"
                "请重新读取所需文件或物料并更新拆分产物；若仍无法读取文件或因权限无法获取物料，"
                "请继续按资源访问阻塞协议报告。", 'breakdown')
        return response

    def _run_breakdown(self, user_idea=None):
        print("\n" + "=" * 60 + "\n📋 阶段 1: 大需求拆分\n" + "=" * 60)
        has_existing_index = os.path.isfile(self.requirements_index_file)
        resume_existing_index = user_idea is None and has_existing_index
        initial_breakdown_message = None
        if resume_existing_index:
            user_idea = "已有拆分产物；请在不重置已写内容的前提下完成恢复审查。"
            if self._pending_receipt('breakdown', None):
                initial_breakdown_message = '恢复拆分阶段待补正的回执。'
        elif user_idea is None:
            user_idea = input("\n🎯 请输入总体开发需求描述:\n> ")
        if has_existing_index:
            self._set_demand_status("拆分中", source=user_idea)
            if not resume_existing_index:
                initial_breakdown_message = self._breakdown_update_instruction(user_idea)
        else:
            self._set_demand_status("拆分中", source=user_idea)
            initial_breakdown_message = self._breakdown_instruction(user_idea)
        breaker = self._create_agent(
            "需求拆分",
            "requirement_breaker.md",
            "requirement_breaker",
        )
        reviewer = self._create_agent(
            "拆分评审",
            "requirement_break_reviewer.md",
            "breakdown_reviewer",
        )
        if initial_breakdown_message:
            response = self._send_task(breaker, initial_breakdown_message, 'breakdown')
            self._resolve_breakdown_resource_blocker(breaker, response)
        while True:
            self._set_demand_status("拆分评审中", source=user_idea)
            for _attempt in range(MAX_STAGE_ATTEMPTS):
                if self.execution_plan.get_stage_attempt("breakdown_review") >= MAX_STAGE_ATTEMPTS:
                    self._exhaust_stage(None, '拆分评审中')
                    return False
                attempt = self.execution_plan.increment_stage_attempt("breakdown_review")
                review = self._send_task(reviewer, f"请审查拆分产物 {self.requirements_index_file} 及目录 {self.requirements_dir}，原始需求：{self._handoff('user_idea', user_idea)}。"
                    f"通过时在 FINAL_ANSWER JSON 中输出 status=approved；否则输出 changes_requested 和可执行修改意见。"
                    f"本阶段最多评审 {MAX_STAGE_ATTEMPTS} 次；达到上限仍未通过则暂停，不批准拆分。", 'breakdown_review')
                if review.startswith(CALL_FAILURE):
                    if attempt >= MAX_STAGE_ATTEMPTS:
                        self._exhaust_stage(None, '拆分评审中', review)
                        return False
                    continue
                if self._review_passed(review):
                    break
                if attempt >= MAX_STAGE_ATTEMPTS:
                    self._exhaust_stage(None, '拆分评审中', review)
                    return False
                response = self._send_task(breaker, f"拆分评审意见：{self._handoff('review', review)}\n请更新 {self.requirements_dir}，仅修改拆分产物。", 'breakdown')
                self._resolve_breakdown_resource_blocker(breaker, response)
            feedback = self._human_gate("1. 大需求拆分", self.requirements_index_file, breaker)
            if feedback is None:
                os.makedirs(self.requirements_dir, exist_ok=True)
                with open(self.breakdown_approval_file, "w", encoding="utf-8") as approval_file:
                    approval_file.write("approved\n")
                self._set_demand_status("开发中", source=user_idea)
                return
            response = self._send_task(breaker, f"人工审核意见：{self._handoff('feedback', feedback)}\n请更新 {self.requirements_dir}，然后等待重新评审。", 'breakdown')
            self._resolve_breakdown_resource_blocker(breaker, response)

    def _breakdown_instruction(self, user_idea):
        return (
            f"请将以下大需求拆分为简单、可实现、可验证且有依赖顺序的小需求。"
            f"创建 {self.requirements_index_file} 及 {self.requirements_dir}/001-<short-name>.md 等独立文件；"
            "必须写入状态、前置依赖、范围、验收标准、风险。"
            "每个小需求的 `user_requirements.md` 都必须包含“全局上下文”小节，"
            "传递客户原始需求摘要、适用业务场景、测试环境、账号、密码、凭据、接口地址、物料/Figma 等跨需求信息；"
            "测试环境、账号、密码等验证信息必须从原始需求保留到需要联调或验证的小需求中，不得只放在父需求或索引里。"
            f"返回前确认文件存在。原始需求：{self._handoff('user_idea', user_idea)}"
        )

    def _breakdown_update_instruction(self, user_idea):
        return (
            f"收到新的需求或补充说明：{self._handoff('user_idea', user_idea)}。"
            f"请阅读并保留现有拆分产物 {self.requirements_index_file} 及 {self.requirements_dir} 下各需求文件，"
            f"只做与本次输入相关的增量调整；必要时新增、拆分或更新小需求，并保持依赖顺序、状态、范围、验收标准和风险一致。"
            "若补充说明包含客户原始需求、测试环境、账号、密码、凭据、接口地址、物料/Figma 等跨需求信息，"
            "必须同步更新每个受影响小需求 `user_requirements.md` 的“全局上下文”小节，不得只写在索引或父级说明中。"
            f"返回前确认 {self.requirements_index_file} 和相关需求文件已更新。"
        )

    def _run_execution(self):
        print("\n" + "=" * 60 + "\n💻 阶段 2: 按小需求实施\n" + "=" * 60)
        self._logged_item_starts = set()
        self._logged_item_completions = set()
        self._ensure_execution_plan()
        self._set_demand_status("开发中")
        items = self._load_items()
        self._validate_items(items)
        while item := self._next_runnable_item(items):
            self._ensure_item_execution_sequence(item)
            self._start_item(item)
            item_agents = self._item_agents(item)
            self._bind_item_agents(item, item_agents)
            self._log_current_item(item)
            if item.status in {"需求分析中", "需求评审中"}:
                self._run_item_requirements(item, item_agents["analyst"], item_agents["requirements_reviewer"])
                items = self._load_items()
                self._validate_items(items)
                continue
            if item.status == "待需求人工确认":
                self._resume_requirements_human_gate(item, item_agents["analyst"])
                items = self._load_items()
                self._validate_items(items)
                continue
            if item.status == "待人工确认":
                self._resume_human_gate(item, item_agents["developer"])
                items = self._load_items()
                self._validate_items(items)
                continue
            if item.status == "记忆整理中":
                if self._should_save_item_memory(item, items):
                    self._run_item_memory(
                        item,
                        item_agents,
                        memory_items=self._memory_checkpoint_items(item, items),
                        release_agents=self._should_release_item_agents(item, items),
                    )
                else:
                    self._complete_item(item)
                items = self._load_items()
                self._validate_items(items)
                continue
            self._run_item(item, item_agents["developer"], item_agents["code_reviewer"])
            items = self._load_items()
            self._validate_items(items)
            completed_item = next(
                candidate
                for candidate in items
                if candidate.requirement_id == item.requirement_id
            )
            if (
                completed_item.status == "记忆整理中"
                and not self._should_save_item_memory(completed_item, items)
            ):
                self._complete_item(completed_item)
                items = self._load_items()
                self._validate_items(items)
        unfinished = [item for item in items if item.status not in {"已完成"}]
        outcomes = [record for record in self.execution_plan.read()['items'] if record.get('review_outcomes')]
        if all(item.status in {'已完成', REVIEW_EXHAUSTED} for item in items) and (unfinished or outcomes):
            self._set_demand_status('执行结束（有未通过项）')
            print('\n⚠️ 所有小需求执行回合已结束，但存在未通过项；未归档，不宣称全部验收完成。')
            for record in self.execution_plan.read()['items']:
                if record.get('review_outcomes') or record['status'] == REVIEW_EXHAUSTED:
                    print(f"- {record['id']}：{json.dumps(record.get('review_outcomes') or record.get('suspension'), ensure_ascii=False)}")
            return False
        if unfinished:
            deferred_ids = self._blocked_dependency_chain(items)
            if {item.requirement_id for item in unfinished} <= deferred_ids:
                self._set_demand_status('阻塞')
                self._print_deferred_summary(items, deferred_ids)
                return False
            raise RuntimeError("没有可执行的小需求；请检查 requirements/index.md 中的阻塞状态和依赖。")
        return True

    def _run_item_requirements(self, item, analyst, reviewer):
        if self.execution_plan.get_stage_attempt('requirements_review', item.requirement_id) >= MAX_STAGE_ATTEMPTS:
            self._exhaust_stage(item.requirement_id, '需求评审中')
            return
        paths = self._item_paths(item)
        os.makedirs(paths["workspace"], exist_ok=True)
        requirement_file = paths["requirements"]
        analysis_report = paths["requirements_analysis"]
        review_report = paths["requirements_review"]
        if item.status != "需求评审中":
            self._set_status(item.requirement_id, "需求分析中")
            analysis_message = (
                f"只分析当前需求 {item.requirement_id}。阅读 {requirement_file}，补全范围、影响、边界、异常、验收标准、依赖和风险；将分析结果写入 {analysis_report}，不得覆盖拆分需求文件或修改其他需求。"
            )
            feedback = self._pending_feedback_message(item.requirement_id)
            if feedback:
                analysis_message += f"\n需要处理的需求变更意见：{self._handoff('feedback', feedback)}"
            response = self._send_task(analyst, analysis_message + self._continuation_context(item) + STAGE_RESULT_INSTRUCTION, 'analysis', item)
            response = self._normalize_item_response(item, '需求分析中', response)
            self._clear_pending_feedback(item.requirement_id)
            self._set_status(item.requirement_id, "需求评审中")
        while True:
            for _attempt in range(MAX_STAGE_ATTEMPTS):
                if self.execution_plan.get_stage_attempt("requirements_review", item.requirement_id) >= MAX_STAGE_ATTEMPTS:
                    self._exhaust_stage(item.requirement_id, '需求评审中')
                    return
                attempt = self.execution_plan.increment_stage_attempt(
                    "requirements_review", item.requirement_id
                )
                review = self._send_task(reviewer, f"只评审当前需求 {item.requirement_id}。阅读 {requirement_file} 和 {analysis_report}，将结论写入 {review_report}。通过时在 FINAL_ANSWER JSON 中输出 status=approved；否则输出 changes_requested 和具体修改意见。"
                    + self._continuation_context(item) + STAGE_RESULT_INSTRUCTION, 'requirements_review', item)
                if review.startswith(CALL_FAILURE):
                    if attempt >= MAX_STAGE_ATTEMPTS:
                        self._exhaust_stage(item.requirement_id, '需求评审中', review)
                        return
                    continue
                review = self._normalize_item_response(item, '需求评审中', review)
                if self._review_passed(review):
                    break
                if attempt >= MAX_STAGE_ATTEMPTS:
                    self._exhaust_stage(item.requirement_id, '需求评审中', review)
                    return
                self._set_pending_feedback(item.requirement_id, "requirement_review", "需求评审中", review)
                self._set_status(item.requirement_id, "需求分析中")
                response = self._send_task(analyst, f"当前需求 {item.requirement_id} 的需求评审意见：{self._handoff('review', review)}\n请仅修订当前需求文档。" + self._continuation_context(item) + STAGE_RESULT_INSTRUCTION, 'analysis', item)
                response = self._normalize_item_response(item, '需求分析中', response)
                self._clear_pending_feedback(item.requirement_id)
                self._set_status(item.requirement_id, "需求评审中")
            self._set_status(item.requirement_id, "待需求人工确认")
            feedback = self._human_gate(
                f"2. 小需求 {item.requirement_id} 需求分析",
                analysis_report,
                analyst,
            )
            if feedback is None:
                self._set_status(item.requirement_id, "待开发")
                return
            self._set_pending_feedback(item.requirement_id, "requirements_human", "待需求人工确认", feedback)
            self._set_status(item.requirement_id, "需求分析中")
            response = self._send_task(analyst, f"当前需求 {item.requirement_id} 的需求人工审核意见：{self._handoff('feedback', feedback)}\n请仅修订 {analysis_report}。" + self._continuation_context(item) + STAGE_RESULT_INSTRUCTION, 'analysis', item)
            response = self._normalize_item_response(item, '需求分析中', response)
            self._clear_pending_feedback(item.requirement_id)
            self._set_status(item.requirement_id, "需求评审中")

    def _resume_requirements_human_gate(self, item, analyst):
        feedback = self._human_gate(
            f"2. 小需求 {item.requirement_id} 需求分析",
            self._item_paths(item)["requirements_analysis"],
            analyst,
        )
        if feedback is None:
            self._set_status(item.requirement_id, "待开发")
            return
        self._set_pending_feedback(item.requirement_id, "requirements_human", "待需求人工确认", feedback)
        self._set_status(item.requirement_id, "需求分析中")

    def _run_item(self, item, developer, reviewer):
        if self.execution_plan.get_stage_attempt('code_review', item.requirement_id) >= MAX_STAGE_ATTEMPTS:
            self._exhaust_stage(item.requirement_id, '代码评审中')
            return
        paths = self._item_paths(item)
        os.makedirs(paths["workspace"], exist_ok=True)
        requirement_file = paths["requirements"]
        analysis_report = paths["requirements_analysis"]
        develop_report = paths["develop"]
        test_report = paths["test"]
        review_report = paths["code_review"]
        review_context = CodeReviewContext(
            item.requirement_id, paths,
            self.execution_plan.get_stage_attempt('code_review', item.requirement_id),
        )
        pending_feedback = self._pending_feedback_message(item.requirement_id)
        if pending_feedback:
            review_context.record_feedback(pending_feedback)
        # 静态扫描不再由流水线强制插入；由拆分阶段编排的「静态扫描」小需求
        # 在开发回合内由开发 Agent 自行调用 static_scan.py 完成。
        if item.status != "代码评审中":
            self._set_status(item.requirement_id, "开发中")
            initial_message = (
                f"只实现当前需求 {item.requirement_id}。阅读 {requirement_file} 和 {analysis_report}。"
                f"允许进行必要自测，并将自测命令和结果写入 {develop_report}。完成后写 {develop_report}。"
                "不得实现其他需求，也不要修改 requirements/index.md。"
            )
            feedback = self._pending_feedback_message(item.requirement_id)
            if feedback:
                initial_message += f"\n上次反馈意见：{self._handoff('feedback', feedback)}\n请仅修正当前项。"
            response = self._send_task(developer, initial_message + DEVELOPMENT_HANDOFF + self._continuation_context(item) + STAGE_RESULT_INSTRUCTION, 'development', item)
            response = self._normalize_item_response(item, '开发中', response)
            review_context.record_development(response)
            self._clear_pending_feedback(item.requirement_id)
            self._set_status(item.requirement_id, "代码评审中")
        while True:
            if self.execution_plan.get_stage_attempt("code_review", item.requirement_id) >= MAX_STAGE_ATTEMPTS:
                self._exhaust_stage(item.requirement_id, '代码评审中')
                return
            else:
                attempt = self.execution_plan.increment_stage_attempt("code_review", item.requirement_id)
                review = self._send_task(reviewer, f"只验证并审查当前需求 {item.requirement_id}。按本轮调度模式核对 {requirement_file}、{analysis_report}、{develop_report} 和相关代码、测试。"
                    f"在本轮范围内执行必要测试并写 {test_report}；发现缺陷时写 {paths['bug']}。"
                    f"将审查结论写入 {review_report}。通过时在 FINAL_ANSWER JSON 中输出 status=approved；否则输出 changes_requested 和当前项的具体修改意见。"
                    "若目标为 android:runnable，核对 Developer 的实际设备验证、AVD 准备尝试、硬超时及启停清理证据；缺口交回 Developer 补验，不能只因 adb 列表为空判不可用。"
                    + review_context.render()
                    + self._continuation_context(item) + STAGE_RESULT_INSTRUCTION, 'code_review', item)
            if review.startswith(CALL_FAILURE):
                if attempt >= MAX_STAGE_ATTEMPTS:
                    self._exhaust_stage(item.requirement_id, '代码评审中', review)
                    return
                continue
            review = self._normalize_item_response(item, '代码评审中', review)
            review_context.record_review(review)
            if self._is_requirement_change(review) and attempt < MAX_STAGE_ATTEMPTS:
                self._set_pending_feedback(item.requirement_id, "requirement_change", "代码评审中", review)
                self._set_status(item.requirement_id, "需求分析中")
                return
            if attempt >= MAX_STAGE_ATTEMPTS and not self._review_passed(review):
                self._exhaust_stage(item.requirement_id, '代码评审中', review)
                return
            if not self._review_passed(review):
                self._set_pending_feedback(item.requirement_id, "code_review", "代码评审中", review)
                self._set_status(item.requirement_id, "开发中")
                response = self._send_task(developer, f"当前需求 {item.requirement_id} 的代码审查意见：{self._handoff('review', review)}\n请仅修正当前项。" + DEVELOPMENT_HANDOFF + self._continuation_context(item) + STAGE_RESULT_INSTRUCTION, 'development', item)
                response = self._normalize_item_response(item, '开发中', response)
                review_context.record_development(response)
                self._clear_pending_feedback(item.requirement_id)
                self._set_status(item.requirement_id, "代码评审中")
                continue
            self._set_status(item.requirement_id, "待人工确认")
            feedback = self._human_gate(f"2. 小需求 {item.requirement_id}", requirement_file, developer)
            if feedback is None:
                self._set_status(item.requirement_id, "记忆整理中")
                return
            if self._is_requirement_change(feedback):
                self._set_pending_feedback(item.requirement_id, "human_requirement_change", "待人工确认", feedback)
                self._set_status(item.requirement_id, "需求分析中")
                return
            self._set_pending_feedback(item.requirement_id, "human", "待人工确认", feedback)
            review_context.record_feedback(feedback)
            self._set_status(item.requirement_id, "开发中")
            response = self._send_task(developer, f"当前需求 {item.requirement_id} 的人工审核意见：{self._handoff('feedback', feedback)}\n请仅修正当前项。" + DEVELOPMENT_HANDOFF + self._continuation_context(item) + STAGE_RESULT_INSTRUCTION, 'development', item)
            response = self._normalize_item_response(item, '开发中', response)
            review_context.record_development(response)
            self._clear_pending_feedback(item.requirement_id)
            self._set_status(item.requirement_id, "代码评审中")

    def _resume_human_gate(self, item, developer):
        requirement_file = self._item_paths(item)["requirements"]
        feedback = self._human_gate(f"2. 小需求 {item.requirement_id}", requirement_file, developer)
        if feedback is None:
            self._set_status(item.requirement_id, "记忆整理中")
            return
        if self._is_requirement_change(feedback):
            self._set_pending_feedback(item.requirement_id, "human_requirement_change", "待人工确认", feedback)
            self._set_status(item.requirement_id, "需求分析中")
        else:
            self._set_pending_feedback(item.requirement_id, "human", "待人工确认", feedback)
            self._set_status(item.requirement_id, "开发中")

    @staticmethod
    def _item_position(item, items):
        if item.execution_sequence is None:
            raise ValueError(f"需求 {item.requirement_id} 尚未分配实际执行序号。")
        return item.execution_sequence

    @staticmethod
    def _is_final_executed_item(item, items):
        assigned_sequences = [
            candidate.execution_sequence
            for candidate in items
            if candidate.execution_sequence is not None
        ]
        return (
            len(assigned_sequences) == len(items)
            and item.execution_sequence == max(assigned_sequences)
        )

    @classmethod
    def _should_save_item_memory(cls, item, items):
        position = cls._item_position(item, items)
        return (
            position == 1
            or position % ITEM_AGENT_BATCH_SIZE == 0
            or cls._is_final_executed_item(item, items)
        )

    @classmethod
    def _should_release_item_agents(cls, item, items):
        position = cls._item_position(item, items)
        return (
            position % ITEM_AGENT_BATCH_SIZE == 0
            or cls._is_final_executed_item(item, items)
        )

    @classmethod
    def _memory_checkpoint_items(cls, item, items):
        position = cls._item_position(item, items)
        if position == 1:
            previous_checkpoint = 0
        elif position <= ITEM_AGENT_BATCH_SIZE:
            previous_checkpoint = 1
        else:
            previous_checkpoint = ((position - 1) // ITEM_AGENT_BATCH_SIZE) * ITEM_AGENT_BATCH_SIZE
        return sorted(
            (
                candidate
                for candidate in items
                if candidate.execution_sequence is not None
                and previous_checkpoint < candidate.execution_sequence <= position
            ),
            key=lambda candidate: candidate.execution_sequence,
        )

    def _run_item_memory(self, item, item_agents, memory_items=None, release_agents=True):
        paths = self._item_paths(item)
        self._set_status(item.requirement_id, "记忆整理中")
        memory_items = memory_items or [item]
        report_paths = "；".join(
            "、".join(
                (
                    item_paths["requirements"],
                    item_paths["requirements_analysis"],
                    item_paths["requirements_review"],
                    item_paths["develop"],
                    item_paths["test"],
                    item_paths["code_review"],
                    item_paths["static_scan"],
                )
            )
            for item_paths in (self._item_paths(memory_item) for memory_item in memory_items)
        )
        memory_dir = os.path.join(self.work_dir, "memory") + os.sep
        curation_messages = {
            "analyst": self._render_break_prompt(
                MEMORY_CURATION_PROMPT,
                opening="调用消息指定的小需求已通过人工审核，收到记忆整理指令。",
                read_instruction=f"请读取需要核验的正式产物：{report_paths}。",
                curation_scope=(
                    f"只将需求侧事实沉淀到 {memory_dir}："
                    "业务规则、状态流转、场景流程、接口约束、UI/Figma 约束、验收规则和待确认边界。"
                ),
                execution_plan_file=self.execution_plan_file,
                closing_instruction="需求评审和代码审查报告只作为证据输入；不得修改其他需求、执行计划或源码。",
            ),
            "developer": self._render_break_prompt(
                MEMORY_CURATION_PROMPT,
                opening="调用消息指定的小需求已通过人工审核，收到记忆整理指令。",
                read_instruction=f"请读取需要核验的正式产物：{report_paths}、当前代码及已更新的 memory/。",
                curation_scope=(
                    f"只将实现侧事实沉淀到 {memory_dir}："
                    "真实代码路径、接口封装、认证方式、复用方式、模块边界、实现坑点和禁止做法。"
                ),
                execution_plan_file=self.execution_plan_file,
                closing_instruction=(
                    "需求评审和代码审查报告只作为证据输入；不得修改其他需求、执行计划或源码。"
                    f"最后将本小需求的沉淀结果、证据来源、更新的 memory 文件、未沉淀原因和后续注意事项写入 {paths['memory_report']}。"
                ),
            ),
        }
        for role, message in curation_messages.items():
            self._send_task(item_agents[role], message, 'memory_analysis' if role == 'analyst' else 'memory_development', item)
        self._complete_item(item)
        if release_agents:
            self._release_item_agents(self._item_agent_batch_key(item))

    @staticmethod
    def _is_requirement_change(feedback):
        if not isinstance(feedback, str):
            return False
        decision = structured_review_decision(feedback)
        if decision is not None:
            return decision.get("status") == "requirement_change"
        return feedback.strip().startswith("需求变更:")

    @staticmethod
    def _review_passed(review_response):
        return review_passed(review_response)

    def _item_paths(self, item):
        requirements_file = os.path.abspath(os.path.join(self.requirements_dir, item.filename))
        workspace = os.path.dirname(requirements_file)
        return {
            "workspace": workspace,
            "requirements": requirements_file,
            "requirements_analysis": os.path.join(workspace, "requirements_analysis.md"),
            "requirements_review": os.path.join(workspace, "requirement_review.md"),
            "develop": os.path.join(workspace, "develop_report.md"),
            "test": os.path.join(workspace, "test_report.md"),
            "code_review": os.path.join(workspace, "code_review.md"),
            "static_scan": os.path.join(workspace, "static_scan_report.md"),
            "memory_report": os.path.join(workspace, "memory_report.md"),
            "bug": os.path.join(workspace, "bug_report.md"),
        }

    def _load_items(self):
        self._ensure_execution_plan()
        migrated = self.execution_plan.migrate_item_stops()
        if migrated:
            print(f"ℹ️ 迁移旧小需求挂起状态：{', '.join(migrated)}；保留证据与累计次数，继续执行。")
        plan = self.execution_plan.read()
        statuses_changed = self.execution_plan.normalize_plan(plan, VALID_STATUSES)
        self.execution_plan.validate(plan, VALID_STATUSES, self.execution_plan.index_hash())
        if statuses_changed:
            self.execution_plan.write(plan)
        items = [
            RequirementItem(
                raw_item["order"], raw_item["id"], raw_item["name"], raw_item["status"],
                raw_item["dependencies"], raw_item["requirements_file"], raw_item["acceptance_summary"],
                raw_item.get("execution_sequence"),
            )
            for raw_item in plan["items"]
        ]
        self._validate_items(items)
        return sorted(items, key=lambda item: item.order)

    def _ensure_item_execution_sequence(self, item):
        if item.execution_sequence is not None:
            return item.execution_sequence
        plan = self.execution_plan.read()
        self.execution_plan.normalize_plan(plan, VALID_STATUSES)
        self.execution_plan.validate(plan, VALID_STATUSES, self.execution_plan.index_hash())
        assigned_sequences = {
            raw_item.get("execution_sequence")
            for raw_item in plan["items"]
            if isinstance(raw_item.get("execution_sequence"), int)
        }
        next_sequence = max(assigned_sequences, default=0) + 1

        # Old plans did not persist actual execution order. Preserve their completed
        # work deterministically before assigning the next live item.
        for raw_item in sorted(plan["items"], key=lambda candidate: candidate["order"]):
            if raw_item["status"] == "已完成" and raw_item.get("execution_sequence") is None:
                raw_item["execution_sequence"] = next_sequence
                next_sequence += 1

        for raw_item in plan["items"]:
            if raw_item["id"] == item.requirement_id:
                if raw_item.get("execution_sequence") is None:
                    raw_item["execution_sequence"] = next_sequence
                item.execution_sequence = raw_item["execution_sequence"]
                self.execution_plan.write(plan)
                return item.execution_sequence
        raise ValueError(f"找不到需求 ID: {item.requirement_id}")

    def _ensure_execution_plan(self):
        if self.execution_plan.is_current(VALID_STATUSES) and not self._pending_receipt('normalize', None):
            self._validate_items_from_plan(self.execution_plan.read())
            return
        previous_plan = self._valid_previous_plan()
        source_hash = self.execution_plan.index_hash()
        normalizer = self._create_agent(
            "执行索引规范化",
            "index_normalizer.md",
            "requirement_breaker",
        )
        normalizer_response = self._send_task(normalizer, f"请将 {self.requirements_index_file} 规范化为 {self.execution_plan_file}。"
            f"requirements 目录为 {self.requirements_dir}；当前 index.md 的 SHA-256 为 {source_hash}。"
            "只写 execution_plan.json，不得修改 index.md 或任何需求、报告、源码文件。", 'normalize')
        if previous_plan is not None:
            # This receipt was just recovered; do not resurrect it while
            # preserving unrelated progress from before normalization.
            previous_plan.get('demand', {}).get('pending_receipts', {}).pop('normalize', None)
        try:
            plan = self.execution_plan.read()
        except ValueError as error:
            if isinstance(normalizer_response, str) and normalizer_response.strip():
                raise ValueError(f"执行索引规范化未生成计划：{normalizer_response.strip()}") from error
            raise
        statuses_changed = self.execution_plan.normalize_plan(plan, VALID_STATUSES)
        self.execution_plan.validate(plan, VALID_STATUSES, expected_source_hash=source_hash)
        self._validate_items_from_plan(plan)
        preserve_changed = previous_plan is not None and self._preserve_unchanged_statuses(previous_plan, plan)
        if statuses_changed or preserve_changed:
            self.execution_plan.write(plan)

    def _valid_previous_plan(self):
        try:
            plan = self.execution_plan.read()
            self.execution_plan.normalize_plan(plan, VALID_STATUSES)
            self.execution_plan.validate_demand(plan)
        except ValueError:
            return None
        try:
            self.execution_plan.validate(plan, VALID_STATUSES)
            self._validate_items_from_plan(plan)
        except ValueError:
            plan["items"] = []
        return plan

    @staticmethod
    def _preserve_unchanged_statuses(previous_plan, plan):
        previous_items = {
            BreakPipeline._item_identity(item): item
            for item in previous_plan.get("items", [])
            if BreakPipeline._has_item_identity(item)
        }
        changed = False
        previous_demand = previous_plan.get("demand", {})
        demand = plan.setdefault("demand", {})
        for field in ('stage_attempts', 'attempt_history', 'pending_receipts', 'suspension', 'suspension_history', 'review_outcomes', 'continuation_notes'):
            if field in previous_demand and demand.get(field) != previous_demand[field]:
                demand[field] = previous_demand[field]
                changed = True
        if previous_demand.get("status") and demand.get("status") != previous_demand.get("status"):
            demand["status"] = previous_demand.get("status")
            changed = True
        if previous_demand.get("source") and demand.get("source") != previous_demand.get("source"):
            demand["source"] = previous_demand.get("source")
            changed = True
        previous_demand_sessions = previous_demand.get("agent_sessions")
        if isinstance(previous_demand_sessions, dict):
            demand_sessions = demand.setdefault("agent_sessions", {})
            for agent_name, session_record in previous_demand_sessions.items():
                if demand_sessions.get(agent_name) != session_record:
                    demand_sessions[agent_name] = session_record
                    changed = True
        for item in plan["items"]:
            previous_item = previous_items.get(BreakPipeline._item_identity(item))
            if previous_item is None:
                continue
            if item["status"] != previous_item["status"]:
                item["status"] = previous_item["status"]
                changed = True
            if item.get("pending_feedback") != previous_item.get("pending_feedback"):
                item["pending_feedback"] = previous_item.get("pending_feedback")
                changed = True
            if item.get("agent_sessions") != previous_item.get("agent_sessions"):
                if "agent_sessions" in previous_item:
                    item["agent_sessions"] = previous_item.get("agent_sessions")
                else:
                    item.pop("agent_sessions", None)
                changed = True
            if item.get("execution_sequence") != previous_item.get("execution_sequence"):
                if "execution_sequence" in previous_item:
                    item["execution_sequence"] = previous_item.get("execution_sequence")
                else:
                    item.pop("execution_sequence", None)
                changed = True
            for field in ("started_at", "completed_at", "stage_attempts", "attempt_history", "pending_receipts", "suspension", "suspension_history", "review_outcomes", "continuation_notes"):
                if item.get(field) != previous_item.get(field):
                    if field in previous_item:
                        item[field] = previous_item[field]
                    else:
                        item.pop(field, None)
                    changed = True
            if item.get("acceptance_ids") != previous_item.get("acceptance_ids"):
                if "acceptance_ids" in previous_item:
                    item["acceptance_ids"] = previous_item.get("acceptance_ids")
                else:
                    item.pop("acceptance_ids", None)
                changed = True
        return changed

    @staticmethod
    def _has_item_identity(item):
        return (
            isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("requirements_file"), str)
        )

    @staticmethod
    def _item_identity(item):
        return (
            item["id"],
            item["name"],
            tuple(item["dependencies"]),
            item["requirements_file"],
            item["acceptance_summary"],
        )

    def _validate_items_from_plan(self, plan):
        self._validate_items([
            RequirementItem(
                raw_item["order"], raw_item["id"], raw_item["name"], raw_item["status"],
                raw_item["dependencies"], raw_item["requirements_file"], raw_item["acceptance_summary"],
                raw_item.get("execution_sequence"),
            )
            for raw_item in plan["items"]
        ])

    def _validate_items(self, items):
        ids = set()
        filenames = set()
        orders = set()
        execution_sequences = set()
        positions = {item.requirement_id: item.order for item in items}
        for item in items:
            if item.requirement_id in ids:
                raise ValueError(f"重复需求 ID: {item.requirement_id}")
            ids.add(item.requirement_id)
            if item.order in orders:
                raise ValueError(f"重复需求顺序: {item.order}")
            orders.add(item.order)
            if item.execution_sequence is not None:
                if item.execution_sequence < 1:
                    raise ValueError(f"实际执行序号无效: {item.requirement_id}")
                if item.execution_sequence in execution_sequences:
                    raise ValueError(f"重复实际执行序号: {item.execution_sequence}")
                execution_sequences.add(item.execution_sequence)
            if item.status not in VALID_STATUSES:
                raise ValueError(f"未知需求状态: {item.status}")
            if (
                    os.path.isabs(item.filename)
                    or ntpath.isabs(item.filename)
                    or posixpath.isabs(item.filename)
                    or "\\" in item.filename
                    or posixpath.normpath(item.filename) != item.filename
            ):
                raise ValueError("需求文件必须使用 requirements 下的规范相对路径。")
            requirement_path = os.path.abspath(os.path.join(self.requirements_dir, item.filename))
            if os.path.commonpath([self.requirements_dir, requirement_path]) != self.requirements_dir:
                raise ValueError("需求文件必须位于 requirements 目录。")
            if posixpath.basename(item.filename) != "user_requirements.md" or posixpath.dirname(item.filename) in {"", "."}:
                raise ValueError("需求文件必须是独立小需求目录中的 user_requirements.md。")
            if item.filename in filenames:
                raise ValueError(f"重复需求文件: {item.filename}")
            filenames.add(item.filename)
            if not os.path.isfile(requirement_path):
                raise ValueError(f"缺少需求文件: {item.filename}")
            for dependency in item.dependencies:
                if dependency not in positions:
                    raise ValueError(f"未知前置依赖: {dependency}")
                if positions[dependency] >= item.order:
                    raise ValueError(f"依赖顺序无效: {item.requirement_id} 依赖 {dependency}")

    @staticmethod
    def _next_runnable_item(items):
        completed = {item.requirement_id for item in items if item.status in {"已完成", REVIEW_EXHAUSTED}}
        for item in items:
            if item.status in {
                "需求分析中",
                "需求评审中",
                "待需求人工确认",
                "待开发",
                "开发中",
                "代码评审中",
                "待人工确认",
                "记忆整理中",
            } and set(item.dependencies) <= completed:
                return item
        return None

    @staticmethod
    def _blocked_dependency_chain(items):
        """Return blocked items plus every unfinished item waiting on them."""
        deferred_ids = {item.requirement_id for item in items if item.status in SUSPENDED_STATUSES | {'阻塞'}}
        changed = True
        while changed:
            changed = False
            for item in items:
                if item.status != "已完成" and item.requirement_id not in deferred_ids and set(item.dependencies) & deferred_ids:
                    deferred_ids.add(item.requirement_id)
                    changed = True
        return deferred_ids

    def _print_deferred_summary(self, items, deferred_ids):
        stopped = SUSPENDED_STATUSES | {'阻塞'}
        blocked = [item for item in items if item.status in stopped]
        waiting = [item for item in items if item.status != "已完成" and item.requirement_id in deferred_ids and item.status not in stopped]
        records = {record['id']: record for record in self.execution_plan.read()['items']}
        print("\n⚠️ 当前无可执行需求，仍有历史/人工阻塞项；不是全部验收完成，未执行最终记忆整理：")
        for item in blocked:
            details = records[item.requirement_id].get('suspension', {})
            print(f"- {item.requirement_id} {item.name}：{item.status}；{details.get('reason', '')}；恢复条件：{details.get('resume_condition', '需明确处理未通过项')}")
        for item in waiting:
            blockers = [dependency for dependency in item.dependencies if dependency in deferred_ids]
            print(f"- {item.requirement_id} {item.name}：等待 {', '.join(blockers)}")

    def _set_status(self, requirement_id, status):
        self._ensure_execution_plan()
        self.execution_plan.set_status(
            requirement_id,
            status,
            VALID_STATUSES,
            expected_source_hash=self.execution_plan.index_hash(),
        )

    def _set_demand_status(self, status, source=None):
        self.execution_plan.set_demand_status(status, source=source)

    def _set_pending_feedback(self, requirement_id, kind, source_status, message):
        self.execution_plan.set_pending_feedback(
            requirement_id,
            kind=kind,
            source_status=source_status,
            message=message,
        )

    def _clear_pending_feedback(self, requirement_id):
        self.execution_plan.clear_pending_feedback(requirement_id)

    def _pending_feedback_message(self, requirement_id):
        feedback = self.execution_plan.get_pending_feedback(requirement_id)
        if isinstance(feedback, dict):
            return feedback.get("message")
        return None

    def _active_requirements_complete(self):
        try:
            plan = self.execution_plan.read()
            self.execution_plan.normalize_plan(plan, VALID_STATUSES)
            self.execution_plan.validate(plan, VALID_STATUSES, self.execution_plan.index_hash())
        except ValueError:
            return False
        return bool(plan["items"]) and all(item["status"] == "已完成" for item in plan["items"])

    def _archive_completed_requirements(self):
        if not os.path.isdir(self.requirements_dir):
            return None
        archive_dir = self._next_requirements_archive_dir()
        os.rename(self.requirements_dir, archive_dir)
        return archive_dir

    def _validate_requirement_summary(self):
        if not os.path.isfile(self.requirement_summary_file):
            raise ValueError(
                f"需求总结未生成：缺少 {self.requirement_summary_file}。"
            )
        with open(self.requirement_summary_file, encoding="utf-8") as summary_file:
            summary = summary_file.read()
        required_sections = (
            "## 需求实现情况",
            "## 文档冲突与缺失",
            "## Agent 自主决策",
            "## 来源与 UI 验证",
            "## 未完成与风险",
        )
        missing_sections = [section for section in required_sections if section not in summary]
        if missing_sections:
            raise ValueError(
                f"需求总结不完整：缺少章节 {', '.join(missing_sections)}。"
            )
        item_ids = [item.requirement_id for item in self._load_items()]
        missing_items = [requirement_id for requirement_id in item_ids if requirement_id not in summary]
        if missing_items:
            raise ValueError(
                f"需求总结不完整：缺少需求 {', '.join(missing_items)}。"
            )

    def _next_requirements_archive_dir(self):
        index = 1
        while True:
            candidate = os.path.join(self.work_dir, f"requirements-{index:03d}")
            if not os.path.exists(candidate):
                return candidate
            index += 1

    def _run_final_reflection(self):
        breaker = self.agents.get("需求拆分")
        if breaker is None:
            breaker = self._create_agent(
                "需求拆分",
                "requirement_breaker.md",
                "requirement_breaker",
            )
        self._send_task(breaker, self._render_break_prompt(
                REQUIREMENT_SUMMARY_PROMPT,
                opening="所有小需求已完成，收到最终记忆整理命令，请进入需求总结模式。",
                read_instruction=(
                    f"请扫描整个 {self.requirements_dir}/，包括 index.md、shared_context.md、"
                    f"{self.execution_plan_file}、所有小需求工作日志、Agent 会话证据和当前源码。"
                ),
                curation_scope=(
                    f"请重建并校验 {self.requirement_summary_file}，"
                    "完整总结每个需求、每条 AC、文档冲突、文档缺失、Agent 自主决策、"
                    "实现证据和未验证范围。"
                ),
                execution_plan_file=self.execution_plan_file,
                closing_instruction=(
                    "不得修改 memory/、memory_curation.md、需求文件、其他报告、源码或执行计划；"
                    "完成后返回报告路径和扫描范围。"
                ),
            ), 'summary')
