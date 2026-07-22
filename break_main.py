"""Entry point for the large-requirement breakdown workflow."""

import argparse
import sys

from break_pipeline import BreakPipeline
from environment import setup_environment

EXIT_COMMANDS = {"q", "quit", "exit"}


def _read_user_requirement(first_round):
    prompt = (
        "\n🎯 请输入总体开发需求描述（输入 q/quit/exit 退出）:\n> "
        if first_round else
        "\n🎯 请输入下一个大需求或补充说明（输入 q/quit/exit 退出）:\n> "
    )
    while True:
        try:
            user_input = input(prompt).strip()
        except EOFError:
            print("\n👋 输入结束，程序退出。")
            return None
        if user_input.lower() in EXIT_COMMANDS:
            return None
        if user_input:
            return user_input
        print("⚠️ 需求不能为空，请重新输入。")
        prompt = "> "


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--skipHuman", action="store_true", help="人工审核卡点自动按 Enter 通过")
    args = parser.parse_args([] if argv is None else argv)
    work_dir = setup_environment()
    print(f"✅ Break Pipeline 工作目录: {work_dir}")
    pipeline_options = {"skip_human": True} if args.skipHuman else {}
    first_round = True
    while True:
        user_idea = _read_user_requirement(first_round)
        if user_idea is None:
            break
        BreakPipeline(work_dir, **pipeline_options).run(user_idea)
        first_round = False


if __name__ == "__main__":
    main(sys.argv[1:])
