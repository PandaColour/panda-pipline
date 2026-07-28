"""Large-requirement breakdown and per-item delivery workflow."""

import ntpath
import os
import posixpath
from dataclasses import dataclass

from agents import Agent
from execution_plan import ExecutionPlanStore
from review_decision import review_passed, structured_review_decision
from workflow import human_gate


BREAK_SYSTEM_PROMPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "break-system-prompt")
BREAKDOWN_APPROVAL = "拆分方案通过"
ITEM_APPROVAL = "任务完成"
REQUIREMENTS_APPROVAL = "同意方案"
MAX_REQUIREMENT_REVIEW_ATTEMPTS = 3
VALID_STATUSES = {
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


class BreakPipeline:
    """Break a large request down, then deliver its approved items in order."""

    def __init__(self, work_dir, skip_human=False):
        self.work_dir = os.path.abspath(work_dir)
        self.skip_human = skip_human
        self.requirements_dir = os.path.join(self.work_dir, "requirements")
        self.requirements_index_file = os.path.join(self.requirements_dir, "index.md")
        self.execution_plan = ExecutionPlanStore(self.requirements_dir, self.requirements_index_file)
        self.execution_plan_file = self.execution_plan.plan_file
        self.breakdown_approval_file = os.path.join(self.requirements_dir, ".breakdown-approved")
        self.prompt_dir = BREAK_SYSTEM_PROMPT_DIR
        self.agents = {}
        self._active_item_agents = {}
        self._pending_human_feedback = {}
        self._pending_requirement_feedback = {}

    def _human_gate(self, stage_name, review_file_path=None):
        return human_gate(stage_name, review_file_path, skip_human=self.skip_human)

    def has_resumable_state(self):
        return any(
            os.path.isfile(path)
            for path in (
                self.requirements_index_file,
                self.execution_plan_file,
                self.breakdown_approval_file,
            )
        )

    def _create_agent(self, name, prompt_file):
        agent_type = "cursor"
        session_id = self._agent_session_id(name)
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
        )
        self.agents[name] = agent
        return agent

    def _agent_session_id(self, agent_name):
        try:
            return self.execution_plan.get_agent_session(
                agent_name,
                requirement_id=self._agent_requirement_id(agent_name),
            )
        except ValueError:
            return None

    def _set_agent_session(self, agent_name, prompt_file, agent_type, session_id):
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
        """Create one complete agent set per item and retain it through rework."""
        if item.requirement_id not in self._active_item_agents:
            prefix = item.requirement_id
            self._active_item_agents[item.requirement_id] = {
                "analyst": self._create_agent(f"{prefix} 小需求需求分析", "item_requirements_analyst.md"),
                "requirements_reviewer": self._create_agent(f"{prefix} 小需求需求评审", "item_requirements_reviewer.md"),
                "developer": self._create_agent(f"{prefix} 小需求开发", "item_developer.md"),
                "code_reviewer": self._create_agent(f"{prefix} 小需求验证审查", "item_code_reviewer.md"),
            }
        return self._active_item_agents[item.requirement_id]

    def _release_item_agents(self, requirement_id):
        """Release an item only after its memory organization has completed."""
        item_agents = self._active_item_agents.pop(requirement_id, {})
        for agent in item_agents.values():
            self.agents.pop(agent.name, None)

    def run(self, user_idea=None):
        if user_idea is not None:
            self._run_breakdown(user_idea)
        elif not os.path.isfile(self.breakdown_approval_file):
            self._run_breakdown()
        if self._run_execution():
            if self._active_requirements_complete():
                self._set_demand_status("记忆整理中")
            self._run_final_reflection()
            if self._active_requirements_complete():
                self._set_demand_status("已完成")
                self._archive_completed_requirements()
            print("\n🎉🎉🎉 【拆分流水线圆满完成】所有小需求均已通过！")

    def _run_breakdown(self, user_idea=None):
        print("\n" + "=" * 60 + "\n📋 阶段 1: 大需求拆分\n" + "=" * 60)
        has_existing_index = os.path.isfile(self.requirements_index_file)
        resume_existing_index = user_idea is None and has_existing_index
        initial_breakdown_message = None
        if resume_existing_index:
            user_idea = "已有拆分产物；请在不重置已写内容的前提下完成恢复审查。"
        elif user_idea is None:
            user_idea = input("\n🎯 请输入总体开发需求描述:\n> ")
        if has_existing_index:
            self._set_demand_status("拆分中", source=user_idea)
            if not resume_existing_index:
                initial_breakdown_message = self._breakdown_update_instruction(user_idea)
        else:
            self._set_demand_status("拆分中", source=user_idea)
            initial_breakdown_message = self._breakdown_instruction(user_idea)
        breaker = self._create_agent("需求拆分", "requirement_breaker.md")
        reviewer = self._create_agent("拆分评审", "requirement_break_reviewer.md")
        if initial_breakdown_message:
            breaker.send_message(initial_breakdown_message)
        while True:
            self._set_demand_status("拆分评审中", source=user_idea)
            for attempt in range(1, MAX_REQUIREMENT_REVIEW_ATTEMPTS + 1):
                review = reviewer.send_message(
                    f"请审查拆分产物 {self.requirements_index_file} 及目录 {self.requirements_dir}，原始需求：{user_idea}。"
                    f"通过时在 FINAL_ANSWER JSON 中输出 status=approved 且 approval_token={BREAKDOWN_APPROVAL}；否则输出 changes_requested 和可执行修改意见。"
                )
                if self._review_passed(review, BREAKDOWN_APPROVAL):
                    break
                if attempt >= MAX_REQUIREMENT_REVIEW_ATTEMPTS:
                    print("⚠️ 拆分评审连续 3 次未通过，按策略自动进入人工确认，让后续流程先完成可完成内容。")
                    break
                breaker.send_message(f"拆分评审意见：{review}\n请更新 {self.requirements_dir}，仅修改拆分产物。")
            feedback = self._human_gate("1. 大需求拆分", self.requirements_index_file)
            if feedback is None:
                os.makedirs(self.requirements_dir, exist_ok=True)
                with open(self.breakdown_approval_file, "w", encoding="utf-8") as approval_file:
                    approval_file.write("approved\n")
                self._set_demand_status("开发中", source=user_idea)
                return
            breaker.send_message(f"人工审核意见：{feedback}\n请更新 {self.requirements_dir}，然后等待重新评审。")

    def _breakdown_instruction(self, user_idea):
        return (
            f"请将以下大需求拆分为简单、可实现、可验证且有依赖顺序的小需求。"
            f"创建 {self.requirements_index_file} 及 {self.requirements_dir}/001-<short-name>.md 等独立文件；"
            "必须写入状态、前置依赖、范围、验收标准、风险。"
            "每个小需求的 `user_requirements.md` 都必须包含“全局上下文”小节，"
            "传递客户原始需求摘要、适用业务场景、测试环境、账号、密码、凭据、接口地址、物料/Figma 等跨需求信息；"
            "测试环境、账号、密码等验证信息必须从原始需求保留到需要联调或验证的小需求中，不得只放在父需求或索引里。"
            f"返回前确认文件存在。原始需求：{user_idea}"
        )

    def _breakdown_update_instruction(self, user_idea):
        return (
            f"收到新的需求或补充说明：{user_idea}。"
            f"请阅读并保留现有拆分产物 {self.requirements_index_file} 及 {self.requirements_dir} 下各需求文件，"
            f"只做与本次输入相关的增量调整；必要时新增、拆分或更新小需求，并保持依赖顺序、状态、范围、验收标准和风险一致。"
            "若补充说明包含客户原始需求、测试环境、账号、密码、凭据、接口地址、物料/Figma 等跨需求信息，"
            "必须同步更新每个受影响小需求 `user_requirements.md` 的“全局上下文”小节，不得只写在索引或父级说明中。"
            f"返回前确认 {self.requirements_index_file} 和相关需求文件已更新。"
        )

    def _run_execution(self):
        print("\n" + "=" * 60 + "\n💻 阶段 2: 按小需求实施\n" + "=" * 60)
        self._ensure_execution_plan()
        self._set_demand_status("开发中")
        items = self._load_items()
        self._validate_items(items)
        while item := self._next_runnable_item(items):
            item_agents = self._item_agents(item)
            if item.status in {"需求分析中", "需求评审中"}:
                self._run_item_requirements(item, item_agents["analyst"], item_agents["requirements_reviewer"])
                items = self._load_items()
                self._validate_items(items)
                continue
            if item.status == "待需求人工确认":
                self._resume_requirements_human_gate(item)
                items = self._load_items()
                self._validate_items(items)
                continue
            if item.status == "待人工确认":
                self._resume_human_gate(item)
                items = self._load_items()
                self._validate_items(items)
                continue
            if item.status == "记忆整理中":
                self._run_item_memory(item, item_agents)
                items = self._load_items()
                self._validate_items(items)
                continue
            self._run_item(item, item_agents["developer"], item_agents["code_reviewer"])
            items = self._load_items()
            self._validate_items(items)
        unfinished = [item for item in items if item.status not in {"已完成"}]
        if unfinished:
            self._mark_blocked_items(items)
            items = self._load_items()
            unfinished = [item for item in items if item.status not in {"已完成"}]
            deferred_ids = self._blocked_dependency_chain(items)
            if {item.requirement_id for item in unfinished} <= deferred_ids:
                self._print_deferred_summary(items, deferred_ids)
                return False
            raise RuntimeError("没有可执行的小需求；请检查 requirements/index.md 中的阻塞状态和依赖。")
        return True

    def _run_item_requirements(self, item, analyst, reviewer):
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
                analysis_message += f"\n需要处理的需求变更意见：{feedback}"
            analyst.send_message(analysis_message)
            self._clear_pending_feedback(item.requirement_id)
            self._set_status(item.requirement_id, "需求评审中")
        while True:
            for attempt in range(1, MAX_REQUIREMENT_REVIEW_ATTEMPTS + 1):
                review = reviewer.send_message(
                    f"只评审当前需求 {item.requirement_id}。阅读 {requirement_file} 和 {analysis_report}，将结论写入 {review_report}。通过时在 FINAL_ANSWER JSON 中输出 status=approved 且 approval_token={REQUIREMENTS_APPROVAL}；否则输出 changes_requested 和具体修改意见。"
                )
                if self._review_passed(review, REQUIREMENTS_APPROVAL):
                    break
                if attempt >= MAX_REQUIREMENT_REVIEW_ATTEMPTS:
                    print(f"⚠️ 小需求 {item.requirement_id} 需求评审连续 3 次未通过，按策略自动进入人工确认。")
                    break
                self._set_pending_feedback(item.requirement_id, "requirement_review", "需求评审中", review)
                self._set_status(item.requirement_id, "需求分析中")
                analyst.send_message(f"当前需求 {item.requirement_id} 的需求评审意见：{review}\n请仅修订当前需求文档。")
                self._clear_pending_feedback(item.requirement_id)
                self._set_status(item.requirement_id, "需求评审中")
            self._set_status(item.requirement_id, "待需求人工确认")
            feedback = self._human_gate(f"2. 小需求 {item.requirement_id} 需求分析", analysis_report)
            if feedback is None:
                self._set_status(item.requirement_id, "待开发")
                return
            self._set_pending_feedback(item.requirement_id, "requirements_human", "待需求人工确认", feedback)
            self._set_status(item.requirement_id, "需求分析中")
            analyst.send_message(f"当前需求 {item.requirement_id} 的需求人工审核意见：{feedback}\n请仅修订 {analysis_report}。")
            self._clear_pending_feedback(item.requirement_id)
            self._set_status(item.requirement_id, "需求评审中")

    def _resume_requirements_human_gate(self, item):
        feedback = self._human_gate(f"2. 小需求 {item.requirement_id} 需求分析", self._item_paths(item)["requirements_analysis"])
        if feedback is None:
            self._set_status(item.requirement_id, "待开发")
            return
        self._set_pending_feedback(item.requirement_id, "requirements_human", "待需求人工确认", feedback)
        self._set_status(item.requirement_id, "需求分析中")

    def _run_item(self, item, developer, reviewer):
        paths = self._item_paths(item)
        os.makedirs(paths["workspace"], exist_ok=True)
        requirement_file = paths["requirements"]
        analysis_report = paths["requirements_analysis"]
        develop_report = paths["develop"]
        test_report = paths["test"]
        review_report = paths["code_review"]
        if item.status != "代码评审中":
            self._set_status(item.requirement_id, "开发中")
            initial_message = (
                f"只实现当前需求 {item.requirement_id}。阅读 {requirement_file} 和 {analysis_report}。"
                f"允许进行必要自测，并将自测命令和结果写入 {develop_report}。完成后写 {develop_report}。"
                "不得实现其他需求，也不要修改 requirements/index.md。"
            )
            feedback = self._pending_feedback_message(item.requirement_id)
            if feedback:
                initial_message += f"\n上次反馈意见：{feedback}\n请仅修正当前项。"
            developer.send_message(initial_message)
            self._clear_pending_feedback(item.requirement_id)
            self._set_status(item.requirement_id, "代码评审中")
        while True:
            review = reviewer.send_message(
                f"只验证并审查当前需求 {item.requirement_id}。阅读 {requirement_file}、{analysis_report}、{develop_report}、当前代码和测试。"
                f"执行必要测试并写 {test_report}；发现缺陷时写 {paths['bug']}。"
                f"将审查结论写入 {review_report}。通过时在 FINAL_ANSWER JSON 中输出 status=approved 且 approval_token={ITEM_APPROVAL}；否则输出 changes_requested 和当前项的具体修改意见。"
            )
            if self._is_requirement_change(review):
                self._set_pending_feedback(item.requirement_id, "requirement_change", "代码评审中", review)
                self._set_status(item.requirement_id, "需求分析中")
                return
            if not self._review_passed(review, ITEM_APPROVAL):
                self._set_pending_feedback(item.requirement_id, "code_review", "代码评审中", review)
                self._set_status(item.requirement_id, "开发中")
                developer.send_message(f"当前需求 {item.requirement_id} 的代码审查意见：{review}\n请仅修正当前项。")
                self._clear_pending_feedback(item.requirement_id)
                self._set_status(item.requirement_id, "代码评审中")
                continue
            self._set_status(item.requirement_id, "待人工确认")
            feedback = self._human_gate(f"2. 小需求 {item.requirement_id}", requirement_file)
            if feedback is None:
                self._set_status(item.requirement_id, "记忆整理中")
                return
            if self._is_requirement_change(feedback):
                self._set_pending_feedback(item.requirement_id, "human_requirement_change", "待人工确认", feedback)
                self._set_status(item.requirement_id, "需求分析中")
                return
            self._set_pending_feedback(item.requirement_id, "human", "待人工确认", feedback)
            self._set_status(item.requirement_id, "开发中")
            developer.send_message(f"当前需求 {item.requirement_id} 的人工审核意见：{feedback}\n请仅修正当前项。")
            self._clear_pending_feedback(item.requirement_id)
            self._set_status(item.requirement_id, "代码评审中")

    def _resume_human_gate(self, item):
        requirement_file = self._item_paths(item)["requirements"]
        feedback = self._human_gate(f"2. 小需求 {item.requirement_id}", requirement_file)
        if feedback is None:
            self._set_status(item.requirement_id, "记忆整理中")
            return
        if self._is_requirement_change(feedback):
            self._set_pending_feedback(item.requirement_id, "human_requirement_change", "待人工确认", feedback)
            self._set_status(item.requirement_id, "需求分析中")
        else:
            self._set_pending_feedback(item.requirement_id, "human", "待人工确认", feedback)
            self._set_status(item.requirement_id, "开发中")

    def _run_item_memory(self, item, item_agents):
        paths = self._item_paths(item)
        self._set_status(item.requirement_id, "记忆整理中")
        report_paths = (
            f"{paths['requirements']}、{paths['requirements_analysis']}、{paths['requirements_review']}、"
            f"{paths['develop']}、{paths['test']}、{paths['code_review']}"
        )
        memory_dir = os.path.join(self.work_dir, "memory") + os.sep
        curation_messages = {
            "analyst": (
                f"当前需求 {item.requirement_id} 已通过人工审核，收到记忆整理指令。"
                f"请读取需要核验的正式产物：{report_paths}，只将需求侧事实沉淀到 {memory_dir}："
                "业务规则、状态流转、场景流程、接口约束、UI/Figma 约束、验收规则和待确认边界。"
                "需求评审和代码审查报告只作为证据输入；不得修改其他需求、执行计划或源码。"
            ),
            "developer": (
                f"当前需求 {item.requirement_id} 已通过人工审核，收到记忆整理指令。"
                f"请读取需要核验的正式产物：{report_paths}、当前代码及已更新的 memory/，"
                f"只将实现侧事实沉淀到 {memory_dir}：真实代码路径、接口封装、认证方式、复用方式、模块边界、实现坑点和禁止做法。"
                f"需求评审和代码审查报告只作为证据输入；不得修改其他需求、执行计划或源码。"
                f"最后将本小需求的沉淀结果、证据来源、更新的 memory 文件、未沉淀原因和后续注意事项写入 {paths['memory_report']}。"
            ),
        }
        for role, message in curation_messages.items():
            item_agents[role].send_message(message)
        self._set_status(item.requirement_id, "已完成")
        self._release_item_agents(item.requirement_id)

    @staticmethod
    def _is_requirement_change(feedback):
        if not isinstance(feedback, str):
            return False
        decision = structured_review_decision(feedback)
        if decision is not None:
            return decision.get("status") == "requirement_change"
        return feedback.strip().startswith("需求变更:")

    @staticmethod
    def _review_passed(review_response, approval_token):
        return review_passed(review_response, approval_token)

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
            "memory_report": os.path.join(workspace, "memory_report.md"),
            "bug": os.path.join(workspace, "bug_report.md"),
        }

    def _load_items(self):
        self._ensure_execution_plan()
        plan = self.execution_plan.read()
        statuses_changed = self.execution_plan.normalize_plan(plan, VALID_STATUSES)
        self.execution_plan.validate(plan, VALID_STATUSES, self.execution_plan.index_hash())
        if statuses_changed:
            self.execution_plan.write(plan)
        items = [
            RequirementItem(
                raw_item["order"], raw_item["id"], raw_item["name"], raw_item["status"],
                raw_item["dependencies"], raw_item["requirements_file"], raw_item["acceptance_summary"],
            )
            for raw_item in plan["items"]
        ]
        self._validate_items(items)
        return sorted(items, key=lambda item: item.order)

    def _ensure_execution_plan(self):
        if self.execution_plan.is_current(VALID_STATUSES):
            self._validate_items_from_plan(self.execution_plan.read())
            return
        previous_plan = self._valid_previous_plan()
        source_hash = self.execution_plan.index_hash()
        normalizer = self._create_agent("执行索引规范化", "index_normalizer.md")
        normalizer_response = normalizer.send_message(
            f"请将 {self.requirements_index_file} 规范化为 {self.execution_plan_file}。"
            f"requirements 目录为 {self.requirements_dir}；当前 index.md 的 SHA-256 为 {source_hash}。"
            "只写 execution_plan.json，不得修改 index.md 或任何需求、报告、源码文件。"
        )
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
            )
            for raw_item in plan["items"]
        ])

    def _validate_items(self, items):
        ids = set()
        filenames = set()
        orders = set()
        positions = {item.requirement_id: item.order for item in items}
        for item in items:
            if item.requirement_id in ids:
                raise ValueError(f"重复需求 ID: {item.requirement_id}")
            ids.add(item.requirement_id)
            if item.order in orders:
                raise ValueError(f"重复需求顺序: {item.order}")
            orders.add(item.order)
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
        completed = {item.requirement_id for item in items if item.status == "已完成"}
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

    def _mark_blocked_items(self, items):
        completed = {item.requirement_id for item in items if item.status == "已完成"}
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
            } and not set(item.dependencies) <= completed:
                self._set_status(item.requirement_id, "阻塞")

    @staticmethod
    def _blocked_dependency_chain(items):
        """Return blocked items plus every unfinished item waiting on them."""
        deferred_ids = {item.requirement_id for item in items if item.status == "阻塞"}
        changed = True
        while changed:
            changed = False
            for item in items:
                if item.status != "已完成" and item.requirement_id not in deferred_ids and set(item.dependencies) & deferred_ids:
                    deferred_ids.add(item.requirement_id)
                    changed = True
        return deferred_ids

    @staticmethod
    def _print_deferred_summary(items, deferred_ids):
        blocked = [item for item in items if item.status == "阻塞"]
        waiting = [item for item in items if item.status != "已完成" and item.requirement_id in deferred_ids and item.status != "阻塞"]
        print("\n⚠️ 本期可执行需求已完成；以下需求因阻塞项延后，未执行最终记忆整理：")
        for item in blocked:
            print(f"- {item.requirement_id} {item.name}：阻塞")
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
            breaker = self._create_agent("需求拆分", "requirement_breaker.md")
        items = self._load_items()
        memory_reports = [self._item_paths(item)["memory_report"] for item in items]
        breaker.send_message(
            f"所有小需求已完成。请只进行拆分层面的最终记忆整理：读取 {self.requirements_index_file} 和各项记忆报告 "
            f"{memory_reports}，结合项目 memory/，只沉淀跨需求可复用的拆分、依赖和整体架构结论。"
            "不要重复各项已沉淀的实现细节，不得修改需求、报告、执行计划或源码。"
        )
