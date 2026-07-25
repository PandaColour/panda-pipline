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
    pipeline = None
    first_round = True
    execution_plan_file = os.path.join(work_dir, "requirements", "execution_plan.json")
    if os.path.isfile(execution_plan_file):
        pipeline = Pipeline(work_dir, **pipeline_options)
        if pipeline.has_resumable_state():
            pipeline.run(None)
            first_round = False
        else:
            pipeline = None
    while True:
        user_idea = _read_user_requirement(first_round)
        if user_idea is None:
            break
        if pipeline is None:
            pipeline = Pipeline(work_dir, **pipeline_options)
        pipeline.run(user_idea)
        pipeline = None
        first_round = False


if __name__ == "__main__":
    main(sys.argv[1:])
