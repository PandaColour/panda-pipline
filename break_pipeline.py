"""Large-requirement breakdown and per-item delivery workflow."""

import os
from dataclasses import dataclass

from agents import Agent
from workflow import human_gate


BREAK_SYSTEM_PROMPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "break-system-prompt")
BREAKDOWN_APPROVAL = "拆分方案通过"
ITEM_APPROVAL = "任务完成"
REQUIREMENTS_APPROVAL = "同意方案"
VALID_STATUSES = {"待审核", "待需求分析", "待需求评审", "需求返工中", "待需求人工确认", "待实施", "开发中", "待人工确认", "已完成", "返工中", "阻塞"}


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

    def __init__(self, work_dir):
        self.work_dir = os.path.abspath(work_dir)
        self.requirements_dir = os.path.join(self.work_dir, "requirements")
        self.requirements_index_file = os.path.join(self.requirements_dir, "index.md")
        self.breakdown_approval_file = os.path.join(self.requirements_dir, ".breakdown-approved")
        self.prompt_dir = BREAK_SYSTEM_PROMPT_DIR
        self.agents = {}
        self._pending_human_feedback = {}
        self._pending_requirement_feedback = {}

    def _create_agent(self, name, prompt_file):
        agent = Agent(name, prompt_file, self.work_dir, add_dirs=None, agent_type="cursor", prompt_dir=self.prompt_dir)
        self.agents[name] = agent
        return agent

    def run(self):
        if not os.path.isfile(self.breakdown_approval_file):
            self._run_breakdown()
        self._run_execution()
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
                f"通过时必须包含「{BREAKDOWN_APPROVAL}」，否则给出可执行修改意见。"
            )
            if not review or not review.strip():
                raise RuntimeError("拆分评审未返回结论，流程已停止。")
            if BREAKDOWN_APPROVAL not in review:
                breaker.send_message(f"拆分评审意见：{review}\n请更新 {self.requirements_dir}，仅修改拆分产物。")
                continue
            feedback = human_gate("1. 大需求拆分", self.requirements_index_file)
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
        items = self._load_items()
        self._validate_items(items)
        requirements_analyst = self._create_agent("小需求需求分析", "item_requirements_analyst.md")
        requirements_reviewer = self._create_agent("小需求需求评审", "item_requirements_reviewer.md")
        developer = self._create_agent("小需求开发", "item_developer.md")
        tester = self._create_agent("小需求测试", "item_tester.md")
        reviewer = self._create_agent("小需求代码审查", "item_code_reviewer.md")
        while item := self._next_runnable_item(items):
            if item.status in {"待需求分析", "待需求评审", "需求返工中"}:
                self._run_item_requirements(item, requirements_analyst, requirements_reviewer)
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
            self._run_item(item, developer, tester, reviewer)
            items = self._load_items()
            self._validate_items(items)
        unfinished = [item for item in items if item.status not in {"已完成"}]
        if unfinished:
            self._mark_blocked_items(items)
            raise RuntimeError("没有可执行的小需求；请检查 requirements/index.md 中的阻塞状态和依赖。")

    def _run_item_requirements(self, item, analyst, reviewer):
        paths = self._item_paths(item)
        os.makedirs(paths["workspace"], exist_ok=True)
        requirement_file = paths["requirements"]
        analysis_report = paths["requirements_analysis"]
        review_report = paths["requirements_review"]
        self._set_status(item.requirement_id, "待需求评审")
        analysis_message = (
            f"只分析当前需求 {item.requirement_id}。阅读并完善 {requirement_file}，补全范围、影响、边界、异常、验收标准、依赖和风险；写 {analysis_report}。不得修改其他需求。"
        )
        feedback = self._pending_requirement_feedback.pop(item.requirement_id, None)
        if feedback:
            analysis_message += f"\n需要处理的需求变更意见：{feedback}"
        analyst.send_message(analysis_message)
        while True:
            review = reviewer.send_message(
                f"只评审当前需求 {item.requirement_id}。阅读 {requirement_file} 和 {analysis_report}，将结论写入 {review_report}。通过时必须包含「{REQUIREMENTS_APPROVAL}」，否则给出具体修改意见。"
            )
            if not review or not review.strip():
                raise RuntimeError(f"需求 {item.requirement_id} 的需求评审未返回结论。")
            if REQUIREMENTS_APPROVAL not in review:
                self._set_status(item.requirement_id, "需求返工中")
                analyst.send_message(f"当前需求 {item.requirement_id} 的需求评审意见：{review}\n请仅修订当前需求文档。")
                self._set_status(item.requirement_id, "待需求评审")
                continue
            self._set_status(item.requirement_id, "待需求人工确认")
            feedback = human_gate(f"2. 小需求 {item.requirement_id} 需求分析", requirement_file)
            if feedback is None:
                self._set_status(item.requirement_id, "待实施")
                return
            self._set_status(item.requirement_id, "需求返工中")
            analyst.send_message(f"当前需求 {item.requirement_id} 的需求人工审核意见：{feedback}\n请仅修订当前需求文档。")
            self._set_status(item.requirement_id, "待需求评审")

    def _resume_requirements_human_gate(self, item):
        feedback = human_gate(f"2. 小需求 {item.requirement_id} 需求分析", self._item_paths(item)["requirements"])
        self._set_status(item.requirement_id, "待实施" if feedback is None else "需求返工中")

    def _run_item(self, item, developer, tester, reviewer):
        paths = self._item_paths(item)
        os.makedirs(paths["workspace"], exist_ok=True)
        requirement_file = paths["requirements"]
        develop_report = paths["develop"]
        test_report = paths["test"]
        review_report = paths["code_review"]
        self._set_status(item.requirement_id, "开发中")
        initial_message = (
            f"只实现当前需求 {item.requirement_id}。阅读 {requirement_file}，完成后写 {develop_report}。"
            "不得实现其他需求，也不要修改 requirements/index.md。"
        )
        feedback = self._pending_human_feedback.pop(item.requirement_id, None)
        if feedback:
            initial_message += f"\n上次人工审核意见：{feedback}\n请仅修正当前项。"
        developer.send_message(initial_message)
        while True:
            tester.send_message(
                f"只测试当前需求 {item.requirement_id}。阅读 {requirement_file} 和 {develop_report}，"
                f"执行必要测试并写 {test_report}。不得实现其他需求。"
            )
            review = reviewer.send_message(
                f"只审查当前需求 {item.requirement_id}。阅读 {requirement_file}、{develop_report}、{test_report}。"
                f"将审查结论写入 {review_report}。通过时必须包含「{ITEM_APPROVAL}」，否则给出当前项的具体修改意见。"
            )
            if not review or not review.strip():
                raise RuntimeError(f"需求 {item.requirement_id} 的代码审查未返回结论。")
            if self._is_requirement_change(review):
                self._set_status(item.requirement_id, "待需求分析")
                self._pending_requirement_feedback[item.requirement_id] = review
                return
            if ITEM_APPROVAL not in review:
                developer.send_message(f"当前需求 {item.requirement_id} 的代码审查意见：{review}\n请仅修正当前项。")
                continue
            self._set_status(item.requirement_id, "待人工确认")
            feedback = human_gate(f"2. 小需求 {item.requirement_id}", requirement_file)
            if feedback is None:
                self._set_status(item.requirement_id, "已完成")
                return
            if self._is_requirement_change(feedback):
                self._set_status(item.requirement_id, "待需求分析")
                self._pending_requirement_feedback[item.requirement_id] = feedback
                return
            self._set_status(item.requirement_id, "返工中")
            developer.send_message(f"当前需求 {item.requirement_id} 的人工审核意见：{feedback}\n请仅修正当前项。")

    def _resume_human_gate(self, item):
        requirement_file = self._item_paths(item)["requirements"]
        feedback = human_gate(f"2. 小需求 {item.requirement_id}", requirement_file)
        if feedback is None:
            self._set_status(item.requirement_id, "已完成")
            return
        if self._is_requirement_change(feedback):
            self._set_status(item.requirement_id, "待需求分析")
            self._pending_requirement_feedback[item.requirement_id] = feedback
        else:
            self._set_status(item.requirement_id, "返工中")
            self._pending_human_feedback[item.requirement_id] = feedback

    @staticmethod
    def _is_requirement_change(feedback):
        return isinstance(feedback, str) and feedback.strip().startswith("需求变更:")

    def _item_paths(self, item):
        requirements_file = os.path.abspath(os.path.join(self.requirements_dir, item.filename))
        workspace = os.path.dirname(requirements_file)
        return {
            "workspace": workspace,
            "requirements": requirements_file,
            "requirements_analysis": requirements_file,
            "requirements_review": os.path.join(workspace, "requirement_review.md"),
            "develop": os.path.join(workspace, "develop_report.md"),
            "test": os.path.join(workspace, "test_report.md"),
            "code_review": os.path.join(workspace, "code_review.md"),
            "bug": os.path.join(workspace, "bug_report.md"),
        }

    def _load_items(self):
        try:
            with open(self.requirements_index_file, encoding="utf-8") as index_file:
                lines = index_file.read().splitlines()
        except FileNotFoundError as error:
            raise ValueError(f"缺少需求索引: {self.requirements_index_file}") from error
        if len(lines) < 2:
            raise ValueError("需求索引缺少表头。")
        expected_header = ["顺序", "ID", "名称", "状态", "前置依赖", "文件", "验收摘要"]
        header = self._parse_table_row(lines[0])
        separator = self._parse_table_row(lines[1])
        if header != expected_header or len(separator) != len(expected_header) or not all(
            cell and set(cell) == {"-"} for cell in separator
        ):
            raise ValueError("索引表头不符合约定。")
        items = []
        for line in lines[2:]:
            if not line.strip():
                continue
            cells = self._parse_table_row(line)
            if cells is None or len(cells) != 7:
                raise ValueError(f"无效索引行: {line}")
            try:
                order = int(cells[0])
            except ValueError as error:
                raise ValueError(f"无效需求顺序: {cells[0]}") from error
            dependencies = [] if cells[4] in {"", "无", "-"} else [value.strip() for value in cells[4].split(",")]
            items.append(RequirementItem(order, cells[1], cells[2], cells[3], dependencies, cells[5], cells[6]))
        if not items:
            raise ValueError("需求索引没有可执行条目。")
        return sorted(items, key=lambda item: item.order)

    @staticmethod
    def _parse_table_row(line):
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            return None
        return [cell.strip() for cell in stripped[1:-1].split("|")]

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
            if item.status in {"待需求分析", "待需求评审", "需求返工中", "待需求人工确认", "待实施", "返工中", "开发中", "待人工确认"} and set(item.dependencies) <= completed:
                return item
        return None

    def _mark_blocked_items(self, items):
        completed = {item.requirement_id for item in items if item.status == "已完成"}
        for item in items:
            if item.status in {"待实施", "返工中"} and not set(item.dependencies) <= completed:
                self._set_status(item.requirement_id, "阻塞")

    def _set_status(self, requirement_id, status):
        with open(self.requirements_index_file, encoding="utf-8") as index_file:
            lines = index_file.read().splitlines()
        updated = []
        for line in lines:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) == 7 and cells[1] == requirement_id:
                cells[3] = status
                line = "| " + " | ".join(cells) + " |"
            updated.append(line)
        with open(self.requirements_index_file, "w", encoding="utf-8") as index_file:
            index_file.write("\n".join(updated) + "\n")

    def _run_final_reflection(self):
        for agent in self.agents.values():
            agent.send_message("根据对话反思和总结你的记忆")
