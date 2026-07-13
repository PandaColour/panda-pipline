import os
from agents import Agent
from workflow import human_gate


class Pipeline:
    """Multi-agent pipeline with feedback loops and human review gates."""

    def __init__(self, work_dir):
        self.work_dir = os.path.abspath(work_dir)
        self.user_requirements_file = os.path.join(self.work_dir, "user_requirements.md")
        self.develop_report_file = os.path.join(self.work_dir, "develop_report.md")
        self.test_report_file = os.path.join(self.work_dir, "test_report.md")
        self.agents = {}

    def _create_agent(self, name, prompt_file):
        agent = Agent(
            name,
            prompt_file,
            self.work_dir,
            add_dirs=None,
            agent_type="cursor",
        )
        self.agents[name] = agent
        return agent

    def run(self):
        self._run_stage_1_requirements()
        self._run_stage_2_development()
        self._run_final_reflection()
        print("\n🎉🎉🎉 【全流程圆满完成】所有阶段均已通过！")

    # ==================== Stage 1: Requirements ====================

    def _run_stage_1_requirements(self):
        print("\n" + "=" * 60)
        print("📋 阶段 1: 需求分析")
        print("=" * 60)

        analyst = self._create_agent("需求分析", "requirements_analyst.md")
        reviewer = self._create_agent("需求审查", "requirements_reviewer.md")

        user_idea = input("\n🎯 请输入项目的总体开发需求描述:\n> ")

        analyst.send_message(
            f"请根据以下初始想法进行深度需求分析，创建{self.user_requirements_file},返回前确保文件创建成功"
            f"请详细列出功能模块和技术栈选型。"
            f"初始想法：{user_idea}"
        )

        review_response = reviewer.send_message(
            f"请审查 {self.user_requirements_file} 文件中的需求分析，原始需求: {user_idea}"
            f"评估其完整性、一致性和可行性。如果满意，请在回复中明确包含「同意方案」。"
            f"如果不满意，请提供具体的修改建议。"
        )

        while True:
            if review_response is None or review_response == "":
                review_response = "同意方案"

            if review_response and "同意方案" in review_response[0:50]:
                human_feedback = human_gate("1. 需求分析", self.user_requirements_file)
                if human_feedback is None:
                    break
                analyst.send_message(
                    f"用户审查后提出了修改意见，请根据以下意见调整并更新 "
                    f"{self.user_requirements_file}。修改意见：{human_feedback}"
                )
            else:
                analyst.send_message(
                    f"需求审查提出了以下修改意见，请根据意见调整并更新 "
                    f"{self.user_requirements_file}。修改意见：{review_response}"
                )

            review_response = reviewer.send_message(
                f"请继续审查 {self.user_requirements_file} 文件中的需求分析,分析agent对它进行了一些修改"
                f"评估其完整性、一致性和可行性。如果满意，请在回复中明确包含「同意方案」。"
                f"如果不满意，请提供具体的修改建议。"
            )

    # ==================== Stage 2: Development ====================

    def _run_stage_2_development(self):
        print("\n" + "=" * 60)
        print("💻 阶段 2: 代码开发")
        print("=" * 60)

        developer = self._create_agent("代码开发", "code_developer.md")
        tester = self._create_agent("代码单元测试", "code_tester.md")
        code_reviewer = self._create_agent("代码review", "code_reviewer.md")

        while True:
            developer.send_message(
                f"请先阅读 {self.user_requirements_file} 中的需求文档，"
                f"然后编写代码实现。"
                f"开发完成后，输出 {self.develop_report_file},返回前确保文件创建成功"
                f"不要编写测试代码。"
            )

            tester.send_message(
                f"请先阅读 {self.develop_report_file} 了解变更范围，"
                f"然后阅读 {self.work_dir} 下的源代码，"
                f"在测试目录下编写单元测试并实际执行测试命令。"
                f"输出 {self.test_report_file}，如有 Bug 生成 {self.work_dir}/bug_report.md。"
            )

            review_response = code_reviewer.send_message(
                f"请先阅读 {self.user_requirements_file}、"
                f"{self.develop_report_file} 和 "
                f"{self.test_report_file}，"
                f"然后审查 {self.work_dir} 下的代码和 {self.work_dir} 下的测试。"
                f"如果所有检查通过，请在回复中明确包含「任务完成」。"
                f"否则请提供具体的修改建议。"
            )

            if review_response is None or review_response == "":
                review_response = "任务完成"

            if review_response and "任务完成" in review_response[0:50]:
                human_feedback = human_gate("2. 代码开发", self.work_dir)
                if human_feedback is None:
                    break
                developer.send_message(
                    f"用户审查后提出修改意见：{human_feedback}"
                    f"\n请根据意见修改代码。"
                )
            else:
                developer.send_message(
                    f"代码审查提出修改意见：{review_response}"
                    f"\n请根据意见修改代码。"
                )

    # ==================== Final Stage: Reflection ====================

    def _run_final_reflection(self):
        print("\n" + "=" * 60)
        print("🧠 最终阶段: 记忆总结")
        print("=" * 60)

        for name, work_dir in self.agents.items():
            agent = self.agents.get(name)
            if agent is None:
                print(f"⚠️  未找到 Agent [{name}]，跳过。")
                continue
            print(f"\n📤 向 Agent [{name}] 发送记忆总结指令...")
            agent.send_message("根据对话反思和总结你的记忆")

        print("\n✅ 记忆总结完成。")
