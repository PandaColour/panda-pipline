import os
import sys


_INVISIBLE_INPUT_CHARS = "\u200b\u200c\u200d\ufeff"


def normalize_human_input(value):
    """Treat whitespace and terminal-invisible characters as empty input."""
    return value.strip().strip(_INVISIBLE_INPUT_CHARS).strip()


def human_gate(stage_name, review_file_path=None, skip_human=False):
    """Request human approval or feedback before the next pipeline stage."""
    print("\n" + "=" * 50)
    print(f"🛑 【人工确认卡点】{stage_name} 阶段已完成！")
    if review_file_path and os.path.exists(review_file_path):
        print(f"📝 请前去审查该文件: {review_file_path}")
    print("=" * 50)

    if skip_human:
        print(f"⏭️  --skipHuman：阶段 {stage_name} 自动按 Enter 通过。")
        return None

    while True:
        user_input = normalize_human_input(
            input("\n👉 请输入指令 [ Enter 键通过 / 输入修改意见让 AI 重做 / 输入 'exit' 退出 ]: ")
        )
        if user_input.lower() == "exit":
            print("👋 流程被人工终止。")
            sys.exit(0)
        if not user_input:
            print(f"💚 阶段 {stage_name} 已人工确认通过，准备进入下一阶段...")
            return None
        print("🔄 收到反馈意见，正在指示 Claude 重新调整...")
        return user_input
