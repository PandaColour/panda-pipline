import os
import sys


def human_gate(stage_name, review_file_path=None):
    """Request human approval or feedback before the next pipeline stage."""
    print("\n" + "=" * 50)
    print(f"🛑 【人工确认卡点】{stage_name} 阶段已完成！")
    if review_file_path and os.path.exists(review_file_path):
        print(f"📝 请前去审查该文件: {review_file_path}")
    print("=" * 50)

    while True:
        user_input = input("\n👉 请输入指令 [ Enter 键通过 / 输入修改意见让 AI 重做 / 输入 'exit' 退出 ]: ").strip()
        if user_input.lower() == "exit":
            print("👋 流程被人工终止。")
            sys.exit(0)
        if not user_input:
            print(f"💚 阶段 {stage_name} 已人工确认通过，准备进入下一阶段...")
            return None
        print("🔄 收到反馈意见，正在指示 Claude 重新调整...")
        return user_input
