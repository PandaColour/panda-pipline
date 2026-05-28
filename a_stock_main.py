import os

from agent import Agent


WORK_DIR = r"D:\github\a-share-agent"
REVIEW_DIR = os.path.join(WORK_DIR, "_review")

TASK = (
    "在保持a-share-agent功能不变的前提下，优化代码逻辑, 减少重复"
)


def setup_environment():
    """Initialize workspace directories."""
    os.makedirs(REVIEW_DIR, exist_ok=True)
    print(f"✅ 工作目录初始化成功: {WORK_DIR}")


def run_pipeline():
    """Run the Python dev → code review feedback loop."""
    developer = Agent("Python开发", "python_developer.md", WORK_DIR)
    reviewer = Agent("代码Review", "code_reviewer_a_stock.md", REVIEW_DIR)

    print("\n" + "=" * 60)
    print("💻 阶段 1: Python 开发")
    print("=" * 60)

    print("\n📤 发送任务给 Python 开发 Agent...")
    dev_response = developer.send_message(
        f"请完成以下开发任务：\n{TASK}\n\n"
        f"请先阅读项目代码理解现有逻辑，再进行修改。修改完成后输出简短的修改总结。"
    )
    print(f"\n📥 Python 开发返回结果:\n{dev_response[:500]}{'...' if len(dev_response or '') > 500 else ''}")

    print("\n" + "=" * 60)
    print("🔍 阶段 2: 代码审核")
    print("=" * 60)

    round_count = 0
    while True:
        round_count += 1
        print(f"\n--- 审核轮次 {round_count} ---")

        print("\n📤 将开发结果发送给代码 Review Agent...")
        review_response = reviewer.send_message(
            f"请审查以下开发任务的完成情况：\n\n"
            f"【任务描述】\n{TASK}\n\n"
            f"【Python 开发的修改总结】\n{dev_response}\n\n"
            f"请检查当前项目代码，验证修改是否正确。\n"
            f"如果审核通过，请在回复中明确包含「审核通过」。\n"
            f"如果不通过，请提供具体的修改建议。"
        )
        print(f"\n📥 代码 Review 返回结果:\n{review_response[:500]}{'...' if len(review_response or '') > 500 else ''}")

        if review_response and "审核通过" in review_response:
            print("\n" + "=" * 60)
            print("✅ 审核通过")
            print("=" * 60)
            break

        print("\n⚠️ 审核不通过，将 Review 意见返回给 Python 开发修改...")
        print("\n📤 发送 Review 意见给 Python 开发 Agent...")
        dev_response = developer.send_message(
            f"代码审核提出了以下修改意见，请根据意见调整代码。\n\n"
            f"【审核意见】\n{review_response}\n\n"
            f"请逐条处理审核意见，修改完成后输出修改总结。"
        )
        print(f"\n📥 Python 开发返回结果:\n{dev_response[:500]}{'...' if len(dev_response or '') > 500 else ''}")


def main():
    setup_environment()
    run_pipeline()


if __name__ == "__main__":
    main()
