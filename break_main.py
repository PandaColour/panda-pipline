"""Entry point for the large-requirement breakdown workflow."""

import argparse
import sys

from break_pipeline import BreakPipeline
from environment import setup_environment


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--skipHuman", action="store_true", help="人工审核卡点自动按 Enter 通过")
    args = parser.parse_args([] if argv is None else argv)
    work_dir = setup_environment()
    print(f"✅ Break Pipeline 工作目录: {work_dir}")
    BreakPipeline(work_dir, **({"skip_human": True} if args.skipHuman else {})).run()


if __name__ == "__main__":
    main(sys.argv[1:])
