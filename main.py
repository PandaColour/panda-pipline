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

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--skipHuman", action="store_true", help="人工审核卡点自动按 Enter 通过")
    args = parser.parse_args([] if argv is None else argv)
    work_dir = setup_environment()
    print(f"✅ Agent 工作目录: {work_dir}")
    pipeline = Pipeline(work_dir, **({"skip_human": True} if args.skipHuman else {}))
    pipeline.run()


if __name__ == "__main__":
    main(sys.argv[1:])
