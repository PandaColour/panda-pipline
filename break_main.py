"""Entry point for the large-requirement breakdown workflow."""

from break_pipeline import BreakPipeline
from main import setup_environment


def main():
    work_dir = setup_environment()
    print(f"✅ Break Pipeline 工作目录: {work_dir}")
    BreakPipeline(work_dir).run()


if __name__ == "__main__":
    main()
