"""Large-requirement breakdown and per-item delivery workflow."""

import os
from dataclasses import dataclass

from agents import Agent
from execution_plan import ExecutionPlanStore
from review_decision import review_passed, structured_review_decision
from workflow import human_gate


BREAK_SYSTEM_PROMPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "break-system-prompt")
BREAKDOWN_APPROVAL = "拆分方案通过"
ITEM_APPROVAL = "任务完成"
REQUIREMENTS_APPROVAL = "同意方案"
VALID_STATUSES = {"待审核", "待需求分析", "待需求评审", "需求返工中", "待需求人工确认", "待实施", "开发中", "待人工确认", "待记忆整理", "记忆整理中", "已完成", "返工中", "阻塞"}


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

    def _create_agent(self, name, prompt_file):
        agent = Agent(name, prompt_file, self.work_dir, add_dirs=None, agent_type="cursor", prompt_dir=self.prompt_dir)
        self.agents[name] = agent
        return agent

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

    def run(self):
        if not os.path.isfile(self.breakdown_approval_file):
            self._run_breakdown()
        if self._run_execution():
            self._run_final_reflection()
            print("\n🎉🎉🎉 【拆分流水线圆满完成】所有小需求均已通过！")

    def _run_breakdown(self):
        print("\n" + "=" * 60 + "\n📋 阶段 1: 大需求拆分\n" + "=" * 60)
        breaker = self._create_agent("需求拆分", "requirement_breaker.md")
        reviewer = self._create_agent("拆分评审", "requirement_break_reviewer.md")
        if os.path.isfile(self.requirements_index_file):
            user_idea = "已有拆分产物；请在不重置已写内容的前提下完成恢复审查。"
        else:
            user_idea = input("\n🎯 请输入总体开发需求描述:\n> ")
            breaker.send_message(self._breakdown_instruction(user_idea))
        while True:
            review = reviewer.send_message(
                f"请审查拆分产物 {self.requirements_index_file} 及目录 {self.requirements_dir}，原始需求：{user_idea}。"
                f"通过时在 FINAL_ANSWER JSON 中输出 status=approved 且 approval_token={BREAKDOWN_APPROVAL}；否则输出 changes_requested 和可执行修改意见。"
            )
            if not self._review_passed(review, BREAKDOWN_APPROVAL):
                breaker.send_message(f"拆分评审意见：{review}\n请更新 {self.requirements_dir}，仅修改拆分产物。")
                continue
            feedback = self._human_gate("1. 大需求拆分", self.requirements_index_file)
            if feedback is None:
                os.makedirs(self.requirements_dir, exist_ok=True)
                with open(self.breakdown_approval_file, "w", encoding="utf-8") as approval_file:
                    approval_file.write("approved\n")
                return
            breaker.send_message(f"人工审核意见：{feedback}\n请更新 {self.requirements_dir}，然后等待重新评审。")

    def _breakdown_instruction(self, user_idea):
        return (
            f"请将以下大需求拆分为简单、可实现、可验证且有依赖顺序的小需求。"
            f"创建 {self.requirements_index_file} 及 {self.requirements_dir}/001-<short-name>.md 等独立文件；"
            f"必须写入状态、前置依赖、范围、验收标准、风险。返回前确认文件存在。原始需求：{user_idea}"
        )

    def _run_execution(self):
        print("\n" + "=" * 60 + "\n💻 阶段 2: 按小需求实施\n" + "=" * 60)
        self._ensure_execution_plan()
        items = self._load_items()
        self._validate_items(items)
        while item := self._next_runnable_item(items):
            item_agents = self._item_agents(item)
            if item.status in {"待需求分析", "待需求评审", "需求返工中"}:
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
            if item.status in {"待记忆整理", "记忆整理中"}:
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
        self._set_status(item.requirement_id, "待需求评审")
        analysis_message = (
            f"只分析当前需求 {item.requirement_id}。阅读 {requirement_file}，补全范围、影响、边界、异常、验收标准、依赖和风险；将分析结果写入 {analysis_report}，不得覆盖拆分需求文件或修改其他需求。"
        )
        feedback = self._pending_requirement_feedback.pop(item.requirement_id, None)
        if feedback:
            analysis_message += f"\n需要处理的需求变更意见：{feedback}"
        analyst.send_message(analysis_message)
        while True:
            review = reviewer.send_message(
                f"只评审当前需求 {item.requirement_id}。阅读 {requirement_file} 和 {analysis_report}，将结论写入 {review_report}。通过时在 FINAL_ANSWER JSON 中输出 status=approved 且 approval_token={REQUIREMENTS_APPROVAL}；否则输出 changes_requested 和具体修改意见。"
            )
            if not self._review_passed(review, REQUIREMENTS_APPROVAL):
                self._set_status(item.requirement_id, "需求返工中")
                analyst.send_message(f"当前需求 {item.requirement_id} 的需求评审意见：{review}\n请仅修订当前需求文档。")
                self._set_status(item.requirement_id, "待需求评审")
                continue
            self._set_status(item.requirement_id, "待需求人工确认")
            feedback = self._human_gate(f"2. 小需求 {item.requirement_id} 需求分析", analysis_report)
            if feedback is None:
                self._set_status(item.requirement_id, "待实施")
                return
            self._set_status(item.requirement_id, "需求返工中")
            analyst.send_message(f"当前需求 {item.requirement_id} 的需求人工审核意见：{feedback}\n请仅修订 {analysis_report}。")
            self._set_status(item.requirement_id, "待需求评审")

    def _resume_requirements_human_gate(self, item):
        feedback = self._human_gate(f"2. 小需求 {item.requirement_id} 需求分析", self._item_paths(item)["requirements_analysis"])
        self._set_status(item.requirement_id, "待实施" if feedback is None else "需求返工中")

    def _run_item(self, item, developer, reviewer):
        paths = self._item_paths(item)
        os.makedirs(paths["workspace"], exist_ok=True)
        requirement_file = paths["requirements"]
        analysis_report = paths["requirements_analysis"]
        develop_report = paths["develop"]
        test_report = paths["test"]
        review_report = paths["code_review"]
        self._set_status(item.requirement_id, "开发中")
        initial_message = (
            f"只实现当前需求 {item.requirement_id}。阅读 {requirement_file} 和 {analysis_report}。"
            f"允许进行必要自测，并将自测命令和结果写入 {develop_report}。完成后写 {develop_report}。"
            "不得实现其他需求，也不要修改 requirements/index.md。"
        )
        feedback = self._pending_human_feedback.pop(item.requirement_id, None)
        if feedback:
            initial_message += f"\n上次人工审核意见：{feedback}\n请仅修正当前项。"
        developer.send_message(initial_message)
        while True:
            review = reviewer.send_message(
                f"只验证并审查当前需求 {item.requirement_id}。阅读 {requirement_file}、{analysis_report}、{develop_report}、当前代码和测试。"
                f"执行必要测试并写 {test_report}；发现缺陷时写 {paths['bug']}。"
                f"将审查结论写入 {review_report}。通过时在 FINAL_ANSWER JSON 中输出 status=approved 且 approval_token={ITEM_APPROVAL}；否则输出 changes_requested 和当前项的具体修改意见。"
            )
            if self._is_requirement_change(review):
                self._set_status(item.requirement_id, "待需求分析")
                self._pending_requirement_feedback[item.requirement_id] = review
                return
            if not self._review_passed(review, ITEM_APPROVAL):
                developer.send_message(f"当前需求 {item.requirement_id} 的代码审查意见：{review}\n请仅修正当前项。")
                continue
            self._set_status(item.requirement_id, "待人工确认")
            feedback = self._human_gate(f"2. 小需求 {item.requirement_id}", requirement_file)
            if feedback is None:
                self._set_status(item.requirement_id, "待记忆整理")
                return
            if self._is_requirement_change(feedback):
                self._set_status(item.requirement_id, "待需求分析")
                self._pending_requirement_feedback[item.requirement_id] = feedback
                return
            self._set_status(item.requirement_id, "返工中")
            developer.send_message(f"当前需求 {item.requirement_id} 的人工审核意见：{feedback}\n请仅修正当前项。")

    def _resume_human_gate(self, item):
        requirement_file = self._item_paths(item)["requirements"]
        feedback = self._human_gate(f"2. 小需求 {item.requirement_id}", requirement_file)
        if feedback is None:
            self._set_status(item.requirement_id, "待记忆整理")
            return
        if self._is_requirement_change(feedback):
            self._set_status(item.requirement_id, "待需求分析")
            self._pending_requirement_feedback[item.requirement_id] = feedback
        else:
            self._set_status(item.requirement_id, "返工中")
            self._pending_human_feedback[item.requirement_id] = feedback

    def _run_item_memory(self, item, item_agents):
        paths = self._item_paths(item)
        self._set_status(item.requirement_id, "记忆整理中")
        report_paths = (
            f"{paths['requirements']}、{paths['requirements_analysis']}、{paths['develop']}、"
            f"{paths['test']}、{paths['code_review']}"
        )
        for role in ("analyst", "requirements_reviewer", "code_reviewer", "developer"):
            message = (
                f"当前需求 {item.requirement_id} 已通过人工审核。请基于你在该需求中的对话和职责，"
                f"阅读需要核验的正式产物：{report_paths}，只将已验证且可复用的结论沉淀到 "
                f"{os.path.join(self.work_dir, 'memory')}。不得修改其他需求、执行计划或源码。"
            )
            if role == "developer":
                message += (
                    f"你负责最后汇总：读取上述产物及已更新的 memory/，"
                    f"将本小需求的沉淀结果、证据来源、更新的 memory 文件、未沉淀原因和后续注意事项写入 {paths['memory_report']}。"
                )
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
        self.execution_plan.validate(plan, VALID_STATUSES, self.execution_plan.index_hash())
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
        self.execution_plan.validate(plan, VALID_STATUSES, expected_source_hash=source_hash)
        self._validate_items_from_plan(plan)
        if previous_plan is not None and self._preserve_unchanged_statuses(previous_plan, plan):
            self.execution_plan.write(plan)

    def _valid_previous_plan(self):
        try:
            plan = self.execution_plan.read()
            self.execution_plan.validate(plan, VALID_STATUSES)
            self._validate_items_from_plan(plan)
        except ValueError:
            return None
        return plan

    @staticmethod
    def _preserve_unchanged_statuses(previous_plan, plan):
        previous_statuses = {
            BreakPipeline._item_identity(item): item["status"]
            for item in previous_plan["items"]
        }
        changed = False
        for item in plan["items"]:
            previous_status = previous_statuses.get(BreakPipeline._item_identity(item))
            if previous_status is not None and item["status"] != previous_status:
                item["status"] = previous_status
                changed = True
        return changed

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
            if os.path.isabs(item.filename) or os.path.normpath(item.filename) != item.filename:
                raise ValueError("需求文件必须使用 requirements 下的规范相对路径。")
            requirement_path = os.path.abspath(os.path.join(self.requirements_dir, item.filename))
            if os.path.commonpath([self.requirements_dir, requirement_path]) != self.requirements_dir:
                raise ValueError("需求文件必须位于 requirements 目录。")
            if os.path.basename(item.filename) != "user_requirements.md" or os.path.dirname(item.filename) in {"", "."}:
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
            if item.status in {"待需求分析", "待需求评审", "需求返工中", "待需求人工确认", "待实施", "返工中", "开发中", "待人工确认", "待记忆整理", "记忆整理中"} and set(item.dependencies) <= completed:
                return item
        return None

    def _mark_blocked_items(self, items):
        completed = {item.requirement_id for item in items if item.status == "已完成"}
        for item in items:
            if item.status in {"待实施", "返工中"} and not set(item.dependencies) <= completed:
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
