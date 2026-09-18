from pipeline_tasks import PipelineTaskMixin, CALL_FAILURE
import os
import subprocess
import sys
from agents import Agent
from config import SOURCE_REPO_DIR, SYSTEM_PROMPT_DIR, get_agent_type
from execution_plan import ExecutionPlanStore
from review_decision import review_passed, structured_final_answer_decision
from workflow import human_gate
from task_protocol import read_resource_blocker

MAX_REQUIREMENT_REVIEW_ATTEMPTS = 10
SYSTEM_COMMAND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "system-command")
MEMORY_CURATION_COMMAND = "memory_curation.md"
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
    "未通过，跳过执行",
}
REQUIREMENT_ID = "R-001"
REQUIREMENT_DIR_NAME = "R-001-main"
REQUIREMENTS_FILE = f"{REQUIREMENT_DIR_NAME}/user_requirements.md"
ACCEPTANCE_SUMMARY = "单需求完成需求分析、开发验证、人工确认和记忆整理"


class Pipeline(PipelineTaskMixin):
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
        self.command_dir = SYSTEM_COMMAND_DIR
        self.agents = {}

    def _human_gate(self, stage_name, review_file_path=None, feedback_agent=None):
        gate_options = {"skip_human": self.skip_human}
        if feedback_agent is not None:
            gate_options["feedback_target"] = feedback_agent.display_name
        return human_gate(stage_name, review_file_path, **gate_options)

    @staticmethod
    def _resource_blocker(response, work_dir=None):
        """Detect a resource-access blocked response from the analyst."""
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

    def _resolve_resource_blocker(self, analyst, response):
        """Force human intervention for resource access issues (不受 --skipHuman 影响)."""
        while blocker := self._resource_blocker(response, self.work_dir):
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
            response = self._send_task(analyst, f"用户已处理资源访问阻塞：{self._handoff('feedback', feedback)}\n"
                "请重新读取所需文件或物料并更新需求文档；若仍无法读取文件或因权限无法获取物料，"
                "请继续按资源访问阻塞协议报告。", 'analysis')
        return response

    def has_resumable_state(self):
        plan = self._valid_existing_plan()
        if plan is None:
            return False
        return plan["items"][0]["status"] != "已完成"

    def _create_agent(self, name, prompt_file, role):
        agent = Agent(
            name,
            prompt_file,
            self.work_dir,
            add_dirs=None,
            agent_type=get_agent_type(role),
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

    def run(self, user_idea=None):
        if self._active_requirements_complete():
            self._archive_completed_requirements()
        self._ensure_execution_plan(user_idea)
        status = self._item_status()
        if status == '未通过，跳过执行':
            return False
        if status in {"需求分析中", "需求评审中", "待需求人工确认"}:
            if self._run_stage_1_requirements() is False:
                return False
            status = self._item_status()
        if status in {"待开发", "开发中", "静态扫描中", "代码评审中", "待人工确认"}:
            if self._run_stage_2_development() is False:
                return False
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
        for key in ('stage_attempts', 'attempt_history', 'review_outcomes', 'agent_sessions'):
            if key in item:
                plan['items'][0][key] = item[key]
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

        analyst = self._create_agent(
            "需求分析",
            "requirements_analyst.md",
            "requirements_analyst",
        )
        reviewer = self._create_agent(
            "需求审查",
            "requirements_reviewer.md",
            "requirements_reviewer",
        )

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
                "AC 仅分逻辑/UI；混合要求在本需求内拆成独立编号的两类 AC，保留原始来源、页面/状态和优先级，不拆成两个开发阶段。增量调整保留未受影响编号，拆开既有项须记录旧新编号映射。"
                "在既有 AC 描述或引用章节明确前置条件/状态、验证动作、观察对象与预期结果、基准定位及失败事实，不能只写截图对比或功能测试；共享步骤与基准可准确引用。"
                f"{existing_context}"
                f"初始想法：{self._handoff('user_idea', user_idea)}"
            )
            feedback = self._pending_feedback_message()
            if feedback:
                analysis_prompt += f"待处理反馈：{self._handoff('feedback', feedback)}"
            analyst_response = self._send_task(analyst, analysis_prompt, 'analysis')
            analyst_response = self._resolve_resource_blocker(analyst, analyst_response)
            self._clear_pending_feedback()
            self._set_status("需求评审中")

        while True:
            self._set_demand_status("需求评审中")
            review_prompt = (
                f"请审查 {self.user_requirements_file} 文件中的需求分析，原始需求: {self._handoff('user_idea', user_idea)}"
                f"评估其完整性、一致性和可行性。如果满意，最终回复按 FINAL_ANSWER JSON 协议输出 status=approved。"
                "检查逻辑/UI 分类与实际断言一致，混合要求按角色规则拆开并保留来源和范围，两类安排独立验证。"
                f"如果不满意，请提供具体的修改建议。"
            )
            for attempt in range(1, MAX_REQUIREMENT_REVIEW_ATTEMPTS + 1):
                review_response = self._send_task(reviewer, review_prompt, 'requirements_review')

                if review_response.startswith(CALL_FAILURE):
                    if self.execution_plan.get_stage_attempt('requirements_review', REQUIREMENT_ID) >= 10:
                        return self._stop_review('requirements_review')
                    continue
                if review_passed(review_response):
                    break
                if self.execution_plan.get_stage_attempt('requirements_review', REQUIREMENT_ID) >= MAX_REQUIREMENT_REVIEW_ATTEMPTS:
                    return self._stop_review('requirements_review')
                self._set_pending_feedback("requirements_review", "需求评审中", review_response)
                self._set_status("需求分析中")
                self._send_task(analyst, f"需求审查提出了以下修改意见，请根据意见调整并更新 "
                    f"{self.user_requirements_file}。修改意见：{self._handoff('review_response', review_response)}", 'analysis')
                self._clear_pending_feedback()
                self._set_status("需求评审中")
                review_prompt = (
                    f"请继续审查 {self.user_requirements_file} 文件中的需求分析,分析agent对它进行了一些修改"
                    f"评估其完整性、一致性和可行性。如果满意，最终回复按 FINAL_ANSWER JSON 协议输出 status=approved。"
                    "在既有问题及直接影响项内检查逻辑/UI 分类与断言一致，混合要求按角色规则拆开并保留来源和范围，两类安排独立验证。"
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
            self._send_task(analyst, f"用户审查后提出了修改意见，请根据以下意见调整并更新 "
                f"{self.user_requirements_file}。修改意见：{self._handoff('human_feedback', human_feedback)}", 'analysis')
            self._clear_pending_feedback()
            self._set_status("需求评审中")

    # ==================== Stage 2: Development ====================

    def _run_stage_2_development(self):
        print("\n" + "=" * 60)
        print("💻 阶段 2: 代码开发")
        print("=" * 60)
        self._ensure_execution_plan()
        self._set_demand_status("开发中")

        developer = self._create_agent(
            "代码开发",
            "code_developer.md",
            "developer",
        )
        code_reviewer = self._create_agent(
            "代码验证审查",
            "code_reviewer.md",
            "code_reviewer",
        )

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
                    "按逻辑/UI AC 分别实现和验证，报告保留编号、类型、证据和逐条结论；逻辑按需验证实际交互，UI 实际查看设计与运行图，不能相互代替。"
                    f"允许进行必要自测，并将自测命令和结果写入 {self.develop_report_file}。"
                    f"开发完成后，输出 {self.develop_report_file},返回前确保文件创建成功"
                )
                feedback = self._pending_feedback_message()
                if feedback:
                    develop_prompt += f"\n待处理反馈：{self._handoff('feedback', feedback)}\n请仅修正当前需求。"
                self._send_task(developer, develop_prompt, 'development')
                self._clear_pending_feedback()
                self._set_status("静态扫描中")
                scan_pending = True
                continue

            review_response = self._send_task(code_reviewer, f"请先阅读 {self.user_requirements_file}、"
                f"{self.develop_report_file}、{self.static_scan_report_file} 和 {self.work_dir} 下的代码、测试。"
                f"执行必要测试，并将测试范围、命令、结果和遗留问题写入 {self.test_report_file}；"
                f"如有 Bug 生成 {self.bug_report_file}。"
                f"然后审查 {self.work_dir} 下的代码和测试。"
                "按逻辑/UI AC 独立核验证据及结论；历史混合项在原编号下分记两类结果，不能以逻辑通过代替视觉通过。复审仅重验既有问题、直接回归和失效证据，保留其他有效结论。"
                f"将代码审查结论写入 {self.code_review_file}。"
                f"如果所有检查通过，最终回复按 FINAL_ANSWER JSON 协议输出 status=approved。"
                f"否则请提供具体的修改建议。", 'code_review')

            if review_response.startswith(CALL_FAILURE):
                if self.execution_plan.get_stage_attempt('code_review', REQUIREMENT_ID) >= 10:
                    return self._stop_review('code_review')
                continue
            if not review_passed(review_response) and self.execution_plan.get_stage_attempt('code_review', REQUIREMENT_ID) >= 10:
                return self._stop_review('code_review')

            if review_passed(review_response):
                self._set_status("待人工确认")
                human_feedback = self._human_gate("2. 代码开发", self.requirement_dir, developer)
                if human_feedback is None:
                    self._set_status("记忆整理中")
                    break
                self._set_pending_feedback("human", "待人工确认", human_feedback)
                self._set_status("开发中")
                self._send_task(developer, f"用户审查后提出修改意见：{self._handoff('human_feedback', human_feedback)}"
                    f"\n请根据意见修改代码。", 'development')
                self._clear_pending_feedback()
                self._set_status("静态扫描中")
                scan_pending = True
            else:
                self._set_pending_feedback("code_review", "代码评审中", review_response)
                self._set_status("开发中")
                self._send_task(developer, f"代码审查提出修改意见：{self._handoff('review_response', review_response)}"
                    f"\n请根据意见修改代码。", 'development')
                self._clear_pending_feedback()
                self._set_status("静态扫描中")
                scan_pending = True

    # ==================== Static code scan ====================

    def _stop_review(self, stage):
        self.execution_plan.record_review_limit(REQUIREMENT_ID,
            '需求评审中' if stage == 'requirements_review' else '代码评审中',
            str(self._last_attempt(stage, REQUIREMENT_ID)))
        self._set_status('未通过，跳过执行')
        self._set_demand_status('执行结束（有未通过项）')
        print('⚠️ 审核累计 10 次已耗尽；详见 execution_plan.json 的 attempt_history。')
        return False

    def _run_static_scan(self):
        """通过 skill 内的独立 CLI 生成扫描报告，不导入工具实现。"""
        skill_dir = os.path.join(SOURCE_REPO_DIR, 'skills', 'panda-pipeline-static-analysis')
        subprocess.run(
            [sys.executable, os.path.join(skill_dir, 'scripts', 'static_scan.py'),
             '--work-dir', self.work_dir, '--report', self.static_scan_report_file],
            cwd=skill_dir, check=True,
        )

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
            "需求分析": self._render_command(
                MEMORY_CURATION_COMMAND,
                opening="收到记忆整理指令。",
                read_instruction=f"请读取已验证产物：{report_paths}。",
                curation_scope=(
                    f"只将需求侧事实沉淀到 {memory_dir}："
                    "业务规则、状态流转、场景流程、接口约束、UI/Figma 约束、验收规则和待确认边界。"
                ),
                execution_plan_file=self.execution_plan_file,
                closing_instruction="审查报告只作为证据输入；只可写调用指定的记忆文档与记忆报告；不得修改需求、既有审核报告、执行计划或源码。",
            ),
            "代码开发": self._render_command(
                MEMORY_CURATION_COMMAND,
                opening="收到记忆整理指令。",
                read_instruction=f"请读取已验证产物：{report_paths} 以及当前代码。",
                curation_scope=(
                    f"只将实现侧事实沉淀到 {memory_dir}："
                    "真实代码路径、接口封装、认证方式、复用方式、模块边界、实现坑点和禁止做法。"
                ),
                execution_plan_file=self.execution_plan_file,
                closing_instruction=(
                    "审查报告只作为证据输入；只可写调用指定的记忆文档与记忆报告；不得修改需求、既有审核报告、执行计划或源码。"
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
            self._send_task(agent, message, 'memory_analysis' if name == '需求分析' else 'memory_development')

        print("\n✅ 记忆总结完成。")
