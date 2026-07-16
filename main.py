import os
import subprocess

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

def main():
    work_dir = setup_environment()
    print(f"✅ Agent 工作目录: {work_dir}")
    pipeline = Pipeline(work_dir)
    pipeline.run()


if __name__ == "__main__":
    main()
