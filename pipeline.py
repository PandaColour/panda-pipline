import os
import shutil

from config import (
    MEMORY_DIR,
    DIR_REQUIREMENTS, DIR_DEVELOPMENT, DIR_TESTING,
    DIR_REQUIREMENTS_REVIEW, DIR_DEVELOPMENT_REVIEW
)
from agent import Agent
from utils import human_gate


class Pipeline:
    """Multi-agent pipeline with feedback loops and human review gates."""

    def __init__(self):
        self.agents = {}

    def _create_agent(self, name, prompt_file, work_dir):
        agent = Agent(name, prompt_file, work_dir)
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

        analyst = self._create_agent("需求分析", "requirements_analyst.md", DIR_REQUIREMENTS)
        reviewer = self._create_agent("需求审查", "requirements_reviewer.md", DIR_REQUIREMENTS_REVIEW)

        user_idea = input("\n🎯 请输入项目的总体开发需求描述:\n> ")

        analyst.send_message(
            f"请根据以下初始想法进行深度需求分析，在当前目录下创建一个 "
            f"user_requirements.md 文件，详细列出功能模块和技术栈选型。"
            f"初始想法：{user_idea}"
        )

        req_file = os.path.join(DIR_REQUIREMENTS, "user_requirements.md")

        while True:
            review_response = reviewer.send_message(
                f"请审查 {DIR_REQUIREMENTS}/user_requirements.md 文件中的需求分析，"
                f"评估其完整性、一致性和可行性。如果满意，请在回复中明确包含「同意方案」。"
                f"如果不满意，请提供具体的修改建议。"
            )

            if review_response and "同意方案" in review_response:
                human_feedback = human_gate("1. 需求分析", req_file)
                if human_feedback is None:
                    break
                analyst.send_message(
                    f"用户审查后提出了修改意见，请根据以下意见调整并更新 "
                    f"user_requirements.md。修改意见：{human_feedback}"
                )
            else:
                analyst.send_message(
                    f"需求审查提出了以下修改意见，请根据意见调整并更新 "
                    f"user_requirements.md。修改意见：{review_response}"
                )

        with open(req_file, 'r', encoding='utf-8') as f:
            self.final_requirements = f.read()

    # ==================== Stage 2: Development ====================

    def _run_stage_2_development(self):
        print("\n" + "=" * 60)
        print("💻 阶段 2: 代码开发")
        print("=" * 60)

        developer = self._create_agent("代码开发", "code_developer.md", DIR_DEVELOPMENT)
        tester = self._create_agent("代码单元测试", "code_tester.md", DIR_TESTING)
        code_reviewer = self._create_agent("代码review", "code_reviewer.md", DIR_DEVELOPMENT_REVIEW)

        while True:
            developer.send_message(
                f"请先阅读 {DIR_REQUIREMENTS}/user_requirements.md 中的需求文档，"
                f"然后在 cloudbank/ 或 qifu-zzbank/cloudbank/ 下编写代码实现。"
                f"注意只修改核心服务和网关代码，不要修改其他项目组的代码。"
                f"开发完成后，输出 develop_report.md。"
                f"不要编写测试代码。\n\n项目需求：\n{self.final_requirements}"
            )

            tester.send_message(
                f"请先阅读 {DIR_DEVELOPMENT}/develop_report.md 了解变更范围，"
                f"然后阅读 {DIR_DEVELOPMENT} 下的源代码，"
                f"在 3_testing 目录下编写单元测试并实际执行测试命令。"
                f"输出 test_report.md，如有 Bug 生成 bug_report.md。"
            )

            review_response = code_reviewer.send_message(
                f"请先阅读 {DIR_REQUIREMENTS}/user_requirements.md、"
                f"{DIR_DEVELOPMENT}/develop_report.md 和 "
                f"{DIR_TESTING}/test_report.md，"
                f"然后审查 {DIR_DEVELOPMENT} 下的代码和 {DIR_TESTING} 下的测试。"
                f"如果所有检查通过，请在回复中明确包含「任务完成」。"
                f"否则请提供具体的修改建议。"
            )

            if review_response and "任务完成" in review_response:
                human_feedback = human_gate("2. 代码开发", DIR_DEVELOPMENT)
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

        reflection_agents = {
            "需求分析": DIR_REQUIREMENTS,
            "代码开发": DIR_DEVELOPMENT,
        }

        for name, work_dir in reflection_agents.items():
            agent = self.agents.get(name)
            if agent is None:
                print(f"⚠️  未找到 Agent [{name}]，跳过。")
                continue
            print(f"\n📤 向 Agent [{name}] 发送记忆总结指令...")
            agent.send_message("根据对话反思和总结你的记忆")

        # Copy updated memory back to source repo
        memory_mappings = [
            (os.path.join(DIR_REQUIREMENTS, "memory", "analysis"), os.path.join(MEMORY_DIR, "analysis")),
            (os.path.join(DIR_DEVELOPMENT, "memory", "develop"), os.path.join(MEMORY_DIR, "develop")),
        ]
        for src, dst in memory_mappings:
            if os.path.exists(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
                print(f"  📋 记忆已回拷: {src} -> {dst}")
            else:
                print(f"  ⚠️  记忆目录不存在，跳过: {src}")

        print("\n✅ 记忆总结完成。")
