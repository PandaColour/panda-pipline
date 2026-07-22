import argparse
import os
import subprocess
import sys

from environment import (
    PROJECT_ROOT,
    REPOS,
    _clone_or_pull,
    _repo_name,
    _repo_target_path,
    _resolve_agent_work_dir,
    setup_environment,
)
from pipeline import Pipeline

EXIT_COMMANDS = {"q", "quit", "exit"}


def _read_user_requirement(first_round):
    prompt = (
        "\n🎯 请输入项目的总体开发需求描述（输入 q/quit/exit 退出）:\n> "
        if first_round else
        "\n🎯 请输入下一个需求或补充说明（输入 q/quit/exit 退出）:\n> "
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
    print(f"✅ Agent 工作目录: {work_dir}")
    pipeline_options = {"skip_human": True} if args.skipHuman else {}
    first_round = True
    while True:
        user_idea = _read_user_requirement(first_round)
        if user_idea is None:
            break
        Pipeline(work_dir, **pipeline_options).run(user_idea)
        first_round = False


if __name__ == "__main__":
    main(sys.argv[1:])
