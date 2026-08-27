import os
from agents import Agent
from config import SYSTEM_PROMPT_DIR
from execution_plan import ExecutionPlanStore
from review_decision import review_passed, structured_final_answer_decision
from static_scan import resolve_scan_root, run_static_scan
from workflow import human_gate

MAX_REQUIREMENT_REVIEW_ATTEMPTS = 3
MEMORY_CURATION_PROMPT = "memory_curation.md"
VALID_STATUSES = {
    "需求分析中",
    "需求评审中",
    "待需求人工确认",
    "待开发",
    "开发中",
    "静态扫描中",
    "代码评审中",
    "待人工确认",
    "记忆整理中",
    "已完成",
    "阻塞",
}
REQUIREMENT_ID = "R-001"
REQUIREMENT_DIR_NAME = "R-001-main"
REQUIREMENTS_FILE = f"{REQUIREMENT_DIR_NAME}/user_requirements.md"
ACCEPTANCE_SUMMARY = "单需求完成需求分析、开发验证、人工确认和记忆整理"


class Pipeline:
    """Multi-agent pipeline with feedback loops and human review gates."""

    def __init__(self, work_dir, skip_human=False):
        self.work_dir = os.path.abspath(work_dir)
        self.skip_human = skip_human
        self.requirements_dir = os.path.join(self.work_dir, "requirements")
        self.requirements_index_file = os.path.join(self.requirements_dir, "index.md")
        self.requirement_dir = os.path.join(self.requirements_dir, REQUIREMENT_DIR_NAME)
        self.execution_plan = ExecutionPlanStore(self.requirements_dir, self.requirements_index_file)
        self.execution_plan_file = self.execution_plan.plan_file
        self.user_requirements_file = os.path.join(self.requirement_dir, "user_requirements.md")
        self.develop_report_file = os.path.join(self.requirement_dir, "develop_report.md")
        self.test_report_file = os.path.join(self.requirement_dir, "test_report.md")
        self.code_review_file = os.path.join(self.requirement_dir, "code_review.md")
        self.static_scan_report_file = os.path.join(self.requirement_dir, "static_scan_report.md")
        self.bug_report_file = os.path.join(self.requirement_dir, "bug_report.md")
        self.memory_report_file = os.path.join(self.requirement_dir, "memory_report.md")
        self.prompt_dir = SYSTEM_PROMPT_DIR
        self.agents = {}

    def _human_gate(self, stage_name, review_file_path=None, feedback_agent=None):
        gate_options = {"skip_human": self.skip_human}
        if feedback_agent is not None:
            gate_options["feedback_target"] = feedback_agent.display_name
        return human_gate(stage_name, review_file_path, **gate_options)

    @staticmethod
    def _resource_blocker(response):
        """Detect a resource-access blocked response from the analyst."""
        if not isinstance(response, str):
            return None
        decision = structured_final_answer_decision(response, {"blocked"})
        if decision is None:
            return None
        blocker = decision.get("blocker")
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

    def _resolve_resource_blocker(self, analyst, response):
        """Force human intervention for resource access issues (不受 --skipHuman 影响)."""
        while blocker := self._resource_blocker(response):
            summary = blocker.get("summary") or blocker.get("reason") or "需求分析所需资源不可访问"
            print(
                "⚠️ 资源访问阻塞："
                f"资源={blocker.get('resource') or '未提供'}；"
                f"原因={blocker.get('reason') or '未提供'}；"
                f"需要用户处理={blocker.get('required_user_action') or '未提供'}"
            )
            feedback = human_gate(
                f"1. 需求分析资源访问阻塞：{summary}",
                self.user_requirements_file,
                skip_human=False,
                feedback_target=analyst.display_name,
            )
            while feedback is None:
                print("⚠️ 请提供资源处理结果后再继续。")
                feedback = human_gate(
                    f"1. 需求分析资源访问阻塞：{summary}",
                    self.user_requirements_file,
                    skip_human=False,
                    feedback_target=analyst.display_name,
                )
            response = analyst.send_message(
                f"用户已处理资源访问阻塞：{feedback}\n"
                "请重新读取所需文件或物料并更新需求文档；若仍无法读取文件或因权限无法获取物料，"
                "请继续按资源访问阻塞协议报告。"
            )
        return response

    def has_resumable_state(self):
        plan = self._valid_existing_plan()
        if plan is None:
            return False
        return plan["items"][0]["status"] != "已完成"

    def _create_agent(self, name, prompt_file):
        agent = Agent(
            name,
            prompt_file,
            self.work_dir,
            add_dirs=None,
            agent_type="cursor",
            prompt_dir=self.prompt_dir,
            status_provider=self._agent_status,
        )
        self.agents[name] = agent
        return agent

    def _agent_status(self):
        try:
            status = self._item_status()
        except (OSError, ValueError):
            return None
        return status if status in VALID_STATUSES else None

    def _render_system_prompt(self, prompt_file, **values):
        template_path = os.path.join(self.prompt_dir, prompt_file)
        with open(template_path, encoding="utf-8") as template_file:
            template = template_file.read()
        try:
            return template.format(**values)
        except KeyError as error:
            missing_key = error.args[0]
            raise ValueError(f"Prompt template {prompt_file} missing placeholder value: {missing_key}") from error

    def run(self, user_idea=None):
        if self._active_requirements_complete():
            self._archive_completed_requirements()
        self._ensure_execution_plan(user_idea)
        status = self._item_status()
        if status in {"需求分析中", "需求评审中", "待需求人工确认"}:
            self._run_stage_1_requirements()
            status = self._item_status()
        if status in {"待开发", "开发中", "静态扫描中", "代码评审中", "待人工确认"}:
            self._run_stage_2_development()
            status = self._item_status()
        if status == "记忆整理中":
            self._set_demand_status("记忆整理中")
            self._run_final_reflection()
            self._set_status("已完成")
            self._set_demand_status("已完成")
        if self._active_requirements_complete():
            self._archive_completed_requirements()
        print("\n🎉🎉🎉 【全流程圆满完成】所有阶段均已通过！")

    def _ensure_execution_plan(self, user_idea=None):
        os.makedirs(self.requirement_dir, exist_ok=True)
        previous_plan = self._valid_existing_plan()
        source = user_idea
        if source is None and previous_plan is not None:
            source = previous_plan.get("demand", {}).get("source", "")
        if source is None:
            source = ""
        self._write_requirements_index()
        if previous_plan is None:
            self.execution_plan.write(self._new_plan("需求分析中", "需求分析中", source, None))
            return
        item = previous_plan["items"][0]
        demand = previous_plan["demand"]
        plan = self._new_plan(
            item["status"],
            demand["status"],
            source if user_idea is not None else demand.get("source", ""),
            item.get("pending_feedback"),
        )
        self.execution_plan.write(plan)

    def _valid_existing_plan(self):
        try:
            plan = self.execution_plan.read()
            self.execution_plan.normalize_plan(plan, VALID_STATUSES)
            self.execution_plan.validate(plan, VALID_STATUSES)
        except ValueError:
            return None
        if not plan.get("items"):
            return None
        return plan

    def _write_requirements_index(self):
        os.makedirs(self.requirements_dir, exist_ok=True)
        content = (
            "| 顺序 | ID | 名称 | 状态 | 前置依赖 | 文件 | 验收摘要 |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            f"| 1 | {REQUIREMENT_ID} | 主需求 | 需求分析中 | 无 | {REQUIREMENTS_FILE} | {ACCEPTANCE_SUMMARY} |\n"
        )
        with open(self.requirements_index_file, "w", encoding="utf-8") as index_file:
            index_file.write(content)

    def _new_plan(self, item_status, demand_status, source, pending_feedback):
        source_hash = self.execution_plan.index_hash()
        return {
            "demand": {
                "id": "D-001",
                "status": demand_status,
                "source": source,
            },
            "source_index_sha256": source_hash,
            "items": [{
                "order": 1,
                "id": REQUIREMENT_ID,
                "name": "主需求",
                "status": item_status,
                "dependencies": [],
                "requirements_file": REQUIREMENTS_FILE,
                "acceptance_summary": ACCEPTANCE_SUMMARY,
                "acceptance_ids": [],
                "pending_feedback": pending_feedback,
                "artifacts": {
                    "requirements": REQUIREMENTS_FILE,
                    "develop_report": f"{REQUIREMENT_DIR_NAME}/develop_report.md",
                    "test_report": f"{REQUIREMENT_DIR_NAME}/test_report.md",
                    "code_review": f"{REQUIREMENT_DIR_NAME}/code_review.md",
                    "static_scan": f"{REQUIREMENT_DIR_NAME}/static_scan_report.md",
                    "memory_report": f"{REQUIREMENT_DIR_NAME}/memory_report.md",
                },
            }],
        }

    # ==================== Stage 1: Requirements ====================

    def _run_stage_1_requirements(self, user_idea=None):
        print("\n" + "=" * 60)
        print("📋 阶段 1: 需求分析")
        print("=" * 60)
        self._ensure_execution_plan(user_idea)
        self._set_demand_status("需求分析中")

        analyst = self._create_agent("需求分析", "requirements_analyst.md")
        reviewer = self._create_agent("需求审查", "requirements_reviewer.md")

        if user_idea is None:
            user_idea = self._demand_source()
        if not user_idea:
            user_idea = input("\n🎯 请输入项目的总体开发需求描述:\n> ")

        existing_context = ""
        if os.path.isfile(self.user_requirements_file):
            existing_context = (
                f"当前已存在 {self.user_requirements_file}，请结合既有内容和本次输入进行增量更新，"
                f"避免无关重写。"
            )

        status = self._item_status()
        if status == "待需求人工确认":
            human_feedback = self._human_gate("1. 需求分析", self.user_requirements_file, analyst)
            if human_feedback is None:
                self._set_status("待开发")
                return
            self._set_pending_feedback("requirements_human", "待需求人工确认", human_feedback)
            status = "需求分析中"

        if status != "需求评审中":
            self._set_status("需求分析中")
            analysis_prompt = (
                f"请根据以下初始想法进行深度需求分析，创建{self.user_requirements_file},返回前确保文件创建成功"
                f"请详细列出功能模块和技术栈选型。"
                f"{existing_context}"
                f"初始想法：{user_idea}"
            )
            feedback = self._pending_feedback_message()
            if feedback:
                analysis_prompt += f"待处理反馈：{feedback}"
            analyst_response = analyst.send_message(analysis_prompt)
            analyst_response = self._resolve_resource_blocker(analyst, analyst_response)
            self._clear_pending_feedback()
            self._set_status("需求评审中")

        while True:
            self._set_demand_status("需求评审中")
            review_prompt = (
                f"请审查 {self.user_requirements_file} 文件中的需求分析，原始需求: {user_idea}"
                f"评估其完整性、一致性和可行性。如果满意，最终回复按 FINAL_ANSWER JSON 协议输出 status=approved 且 approval_token=同意方案。"
                f"如果不满意，请提供具体的修改建议。"
            )
            for attempt in range(1, MAX_REQUIREMENT_REVIEW_ATTEMPTS + 1):
                review_response = reviewer.send_message(review_prompt)

                if review_passed(review_response, "同意方案"):
                    break
                if attempt >= MAX_REQUIREMENT_REVIEW_ATTEMPTS:
                    print("⚠️ 需求审查连续 3 次未通过，按策略自动进入人工确认，让后续流程先完成可完成内容。")
                    break
                self._set_pending_feedback("requirements_review", "需求评审中", review_response)
                self._set_status("需求分析中")
                analyst.send_message(
                    f"需求审查提出了以下修改意见，请根据意见调整并更新 "
                    f"{self.user_requirements_file}。修改意见：{review_response}"
                )
                self._clear_pending_feedback()
                self._set_status("需求评审中")
                review_prompt = (
                    f"请继续审查 {self.user_requirements_file} 文件中的需求分析,分析agent对它进行了一些修改"
                    f"评估其完整性、一致性和可行性。如果满意，最终回复按 FINAL_ANSWER JSON 协议输出 status=approved 且 approval_token=同意方案。"
                    f"如果不满意，请提供具体的修改建议。"
                )

            self._set_status("待需求人工确认")
            human_feedback = self._human_gate("1. 需求分析", self.user_requirements_file, analyst)
            if human_feedback is None:
                self._set_demand_status("开发中")
                self._set_status("待开发")
                break
            self._set_pending_feedback("requirements_human", "待需求人工确认", human_feedback)
            self._set_status("需求分析中")
            analyst.send_message(
                f"用户审查后提出了修改意见，请根据以下意见调整并更新 "
                f"{self.user_requirements_file}。修改意见：{human_feedback}"
            )
            self._clear_pending_feedback()
            self._set_status("需求评审中")

    # ==================== Stage 2: Development ====================

    def _run_stage_2_development(self):
        print("\n" + "=" * 60)
        print("💻 阶段 2: 代码开发")
        print("=" * 60)
        self._ensure_execution_plan()
        self._set_demand_status("开发中")

        developer = self._create_agent("代码开发", "code_developer.md")
        code_reviewer = self._create_agent("代码验证审查", "code_reviewer.md")

        # 静态扫描拥有独立状态：开发完成后进入“静态扫描中”，扫描完成后再进入“代码评审中”。
        # 重启时若处于“静态扫描中”则续跑扫描；若已处于“代码评审中”且扫描报告存在，
        # 直接进入评审，避免对未变更代码重复扫描；报告缺失（如旧计划升级）则补扫一次。
        current_status = self._item_status()
        scan_pending = current_status == "静态扫描中" or (
            current_status == "代码评审中" and not os.path.isfile(self.static_scan_report_file)
        )

        while True:
            status = self._item_status()
            if status == "待人工确认":
                human_feedback = self._human_gate("2. 代码开发", self.requirement_dir, developer)
                if human_feedback is None:
                    self._set_status("记忆整理中")
                    break
                self._set_pending_feedback("human", "待人工确认", human_feedback)
                self._set_status("开发中")
                continue

            if scan_pending or status == "静态扫描中":
                self._run_static_scan()
                self._set_status("代码评审中")
                scan_pending = False
                continue

            if status != "代码评审中":
                self._set_status("开发中")
                develop_prompt = (
                    f"请先阅读 {self.user_requirements_file} 中的需求文档，"
                    f"然后编写代码实现。"
                    f"允许进行必要自测，并将自测命令和结果写入 {self.develop_report_file}。"
                    f"开发完成后，输出 {self.develop_report_file},返回前确保文件创建成功"
                )
                feedback = self._pending_feedback_message()
                if feedback:
                    develop_prompt += f"\n待处理反馈：{feedback}\n请仅修正当前需求。"
                developer.send_message(develop_prompt)
                self._clear_pending_feedback()
                self._set_status("静态扫描中")
                scan_pending = True
                continue

            review_response = code_reviewer.send_message(
                f"请先阅读 {self.user_requirements_file}、"
                f"{self.develop_report_file}、{self.static_scan_report_file} 和 {self.work_dir} 下的代码、测试。"
                f"执行必要测试，并将测试范围、命令、结果和遗留问题写入 {self.test_report_file}；"
                f"如有 Bug 生成 {self.bug_report_file}。"
                f"然后审查 {self.work_dir} 下的代码和测试。"
                f"将代码审查结论写入 {self.code_review_file}。"
                f"如果所有检查通过，最终回复按 FINAL_ANSWER JSON 协议输出 status=approved 且 approval_token=任务完成。"
                f"否则请提供具体的修改建议。"
            )

            if review_response is None or review_response == "":
                review_response = "任务完成"

            if review_passed(review_response, "任务完成"):
                self._set_status("待人工确认")
                human_feedback = self._human_gate("2. 代码开发", self.requirement_dir, developer)
                if human_feedback is None:
                    self._set_status("记忆整理中")
                    break
                self._set_pending_feedback("human", "待人工确认", human_feedback)
                self._set_status("开发中")
                developer.send_message(
                    f"用户审查后提出修改意见：{human_feedback}"
                    f"\n请根据意见修改代码。"
                )
                self._clear_pending_feedback()
                self._set_status("静态扫描中")
                scan_pending = True
            else:
                self._set_pending_feedback("code_review", "代码评审中", review_response)
                self._set_status("开发中")
                developer.send_message(
                    f"代码审查提出修改意见：{review_response}"
                    f"\n请根据意见修改代码。"
                )
                self._clear_pending_feedback()
                self._set_status("静态扫描中")
                scan_pending = True

    # ==================== Static code scan ====================

    def _run_static_scan(self):
        """多语言静态扫描（Kotlin/Java/Python/JS/TS/Swift），结果写入 static_scan_report.md。

        具体实现见 static_scan 模块（pipeline.py 与 break_pipeline.py 共用，彼此独立）。
        """
        run_static_scan(resolve_scan_root(self.work_dir), self.static_scan_report_file)

    def _item_status(self):
        plan = self.execution_plan.read()
        self.execution_plan.normalize_plan(plan, VALID_STATUSES)
        self.execution_plan.validate(plan, VALID_STATUSES, self.execution_plan.index_hash())
        return plan["items"][0]["status"]

    def _demand_source(self):
        try:
            plan = self.execution_plan.read()
            self.execution_plan.normalize_plan(plan, VALID_STATUSES)
            return plan.get("demand", {}).get("source", "")
        except ValueError:
            return ""

    def _set_status(self, status):
        self.execution_plan.set_status(
            REQUIREMENT_ID,
            status,
            VALID_STATUSES,
            expected_source_hash=self.execution_plan.index_hash(),
        )

    def _set_demand_status(self, status):
        self.execution_plan.set_demand_status(status)

    def _set_pending_feedback(self, kind, source_status, message):
        self.execution_plan.set_pending_feedback(
            REQUIREMENT_ID,
            kind=kind,
            source_status=source_status,
            message=message,
        )

    def _clear_pending_feedback(self):
        self.execution_plan.clear_pending_feedback(REQUIREMENT_ID)

    def _pending_feedback_message(self):
        feedback = self.execution_plan.get_pending_feedback(REQUIREMENT_ID)
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

    # ==================== Final Stage: Reflection ====================

    def _run_final_reflection(self):
        print("\n" + "=" * 60)
        print("🧠 最终阶段: 记忆总结")
        print("=" * 60)

        memory_dir = os.path.join(self.work_dir, "memory") + os.sep
        report_paths = (
            f"{self.user_requirements_file}、{self.develop_report_file}、"
            f"{self.test_report_file}、{self.code_review_file}、{self.static_scan_report_file}"
        )
        curation_messages = {
            "需求分析": self._render_system_prompt(
                MEMORY_CURATION_PROMPT,
                opening="收到记忆整理指令。",
                read_instruction=f"请读取已验证产物：{report_paths}。",
                curation_scope=(
                    f"只将需求侧事实沉淀到 {memory_dir}："
                    "业务规则、状态流转、场景流程、接口约束、UI/Figma 约束、验收规则和待确认边界。"
                ),
                execution_plan_file=self.execution_plan_file,
                closing_instruction="审查报告只作为证据输入；不得修改需求、报告、执行计划或源码。",
            ),
            "代码开发": self._render_system_prompt(
                MEMORY_CURATION_PROMPT,
                opening="收到记忆整理指令。",
                read_instruction=f"请读取已验证产物：{report_paths} 以及当前代码。",
                curation_scope=(
                    f"只将实现侧事实沉淀到 {memory_dir}："
                    "真实代码路径、接口封装、认证方式、复用方式、模块边界、实现坑点和禁止做法。"
                ),
                execution_plan_file=self.execution_plan_file,
                closing_instruction=(
                    "审查报告只作为证据输入；不得修改需求、报告、执行计划或源码。"
                    f"最后将沉淀结果、证据来源、更新的 memory 文件和后续注意事项写入 {self.memory_report_file}。"
                ),
            ),
        }

        for name, message in curation_messages.items():
            agent = self.agents.get(name)
            if agent is None:
                print(f"⚠️  未找到角色为 {name} 的 Agent，跳过。")
                continue
            print(f"\n📤 向 {agent.display_name} 发送记忆总结指令...")
            agent.send_message(message)

        print("\n✅ 记忆总结完成。")
