import os
import shutil
import subprocess

from config import (
    PROJECT_ROOT, MEMORY_DIR,
    DIR_REQUIREMENTS, DIR_DEVELOPMENT, DIR_TESTING,
    DIR_REQUIREMENTS_REVIEW, DIR_DEVELOPMENT_REVIEW
)
from pipeline import Pipeline


REPOS = [
    ("https://gitlab.daikuan.qihoo.net/qifu-partners/qifu-zzbank.git", "develop"),
    ("https://gitlab.daikuan.qihoo.net/360shuke/cloudbank.git", "develop"),
]


def _clone_or_pull(repo_url, branch, target_path):
    """Clone repo if missing, otherwise checkout branch and pull latest."""
    if os.path.exists(target_path):
        print(f"  📦 更新仓库: {target_path}")
        subprocess.run(
            ["git", "-C", target_path, "checkout", branch],
            check=False, capture_output=True
        )
        subprocess.run(
            ["git", "-C", target_path, "pull"],
            check=False, capture_output=True
        )
    else:
        print(f"  📦 克隆仓库: {repo_url} -> {target_path}")
        subprocess.run(
            ["git", "clone", repo_url, "-b", branch, target_path],
            check=True, capture_output=True
        )


def _copy_memory(src_subdir, dst_parent_dir):
    """Copy memory/<src_subdir> to <dst_parent_dir>/memory/<src_subdir>."""
    src = os.path.join(MEMORY_DIR, src_subdir)
    dst = os.path.join(dst_parent_dir, "memory", src_subdir)
    if os.path.exists(dst):
        shutil.rmtree(dst)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copytree(src, dst)
    print(f"  📋 已拷贝记忆: {src} -> {dst}")


def setup_environment():
    """Initialize workspace dirs, clone repos, and copy memory files."""
    dirs = [
        DIR_REQUIREMENTS,
        DIR_DEVELOPMENT,
        DIR_TESTING,
        DIR_REQUIREMENTS_REVIEW,
        DIR_DEVELOPMENT_REVIEW,
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
    print(f"✅ 项目目录初始化成功，根路径: {PROJECT_ROOT}")

    # Clone/update repos into 1_requirements and 2_development
    for stage_dir in [DIR_REQUIREMENTS, DIR_DEVELOPMENT]:
        stage_name = os.path.basename(stage_dir)
        print(f"📦 处理 {stage_name} 仓库...")
        for repo_url, branch in REPOS:
            repo_name = repo_url.rstrip("/").rsplit("/", 1)[-1].replace(".git", "")
            target_path = os.path.join(stage_dir, repo_name)
            _clone_or_pull(repo_url, branch, target_path)

    # Copy memory/analysis -> 1_requirements/memory/analysis
    _copy_memory("analysis", DIR_REQUIREMENTS)

    # Copy memory/develop -> 2_development/memory/develop
    _copy_memory("develop", DIR_DEVELOPMENT)


def main():
    setup_environment()
    pipeline = Pipeline()
    pipeline.run()


if __name__ == "__main__":
    main()
