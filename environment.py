"""Repository checkout and work-directory setup shared by workflow entry points."""

import os
import subprocess


PROJECT_ROOT = r"/Users/panda.colour/Company/ios"
REPOS = [
    ("https://gitee.com/meiyingda1/ai-test.git", "master")
]


def _repo_name(repo_url):
    return repo_url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")


def _repo_target_path(repo_url):
    return os.path.join(PROJECT_ROOT, _repo_name(repo_url))


def _resolve_agent_work_dir():
    if len(REPOS) == 1:
        return _repo_target_path(REPOS[0][0])
    return PROJECT_ROOT


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


def setup_environment():
    os.makedirs(PROJECT_ROOT, exist_ok=True)
    for repo_url, branch in REPOS:
        _clone_or_pull(repo_url, branch, _repo_target_path(repo_url))
    return _resolve_agent_work_dir()
