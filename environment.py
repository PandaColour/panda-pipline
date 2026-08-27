"""Repository checkout and work-directory setup shared by workflow entry points."""

import os
import shutil
import subprocess


PROJECT_ROOT = r"/Users/panda.colour/Company/android-wwl1b"
REPOS = [
    ("https://gitee.com/pandacolour/aiphone.git", "android-tecp")
]

DEFAULT_MEMORY_FILENAME = "loan_pipeline_default.md"
DEFAULT_MEMORY_SOURCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "default-memory")
DEFAULT_MEMORY_INDEX_DESCRIPTIONS = {
    DEFAULT_MEMORY_FILENAME: "贷款系统开发流水线默认记忆，约束多国家、多端贷款项目的职责边界、通信协议、加解密、配置化、Mock 和验收纪律。",
    "Network/": "App 端网络协议和加解密基础设施 demo，供端侧接入真实协议时参考，不代表真实后端联调已通过。",
}

STATIC_ANALYSIS_TOOLS = ("detekt", "pmd", "checkstyle", "ruff", "swiftlint")
STATIC_ANALYSIS_NPM_TOOLS = ("eslint",)
CODEGRAPH_NPM_PACKAGE = "@colbymchenry/codegraph"


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
        if not _is_git_work_tree(target_path):
            raise RuntimeError(f"目标路径已存在但不是 Git 仓库: {target_path}")
        print(f"  📦 更新仓库: {target_path}")
        _update_repo(target_path, branch)
        return

    parent_path = os.path.dirname(target_path)
    if os.path.exists(parent_path) and _is_matching_git_repo(parent_path, repo_url):
        print(f"  📦 更新仓库: {parent_path}")
        _update_repo(parent_path, branch)
        return

    print(f"  📦 克隆仓库: {repo_url} -> {target_path}")
    subprocess.run(
        ["git", "clone", repo_url, "-b", branch, target_path],
        check=True, capture_output=True, text=True
    )


def _update_repo(repo_path, branch):
    subprocess.run(
        ["git", "-C", repo_path, "checkout", branch],
        check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "-C", repo_path, "pull"],
        check=True, capture_output=True, text=True
    )


def _is_matching_git_repo(path, repo_url):
    return _is_git_work_tree(path) and _remote_origin_url(path).rstrip("/") == repo_url.rstrip("/")


def _is_git_work_tree(path):
    try:
        result = subprocess.run(
            ["git", "-C", path, "rev-parse", "--is-inside-work-tree"],
            check=False, capture_output=True, text=True
        )
    except subprocess.CalledProcessError:
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _remote_origin_url(path):
    try:
        result = subprocess.run(
            ["git", "-C", path, "config", "--get", "remote.origin.url"],
            check=False, capture_output=True, text=True
        )
    except subprocess.CalledProcessError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _ensure_default_memory(work_dir):
    """Initialize target-project default memory without overwriting project edits."""
    memory_dir = os.path.join(work_dir, "memory")
    os.makedirs(memory_dir, exist_ok=True)

    for source_path, relative_path in _iter_default_memory_files():
        target_path = os.path.join(memory_dir, relative_path)
        if os.path.exists(target_path):
            continue
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        shutil.copyfile(source_path, target_path)

    _ensure_memory_index_entry(memory_dir)


def _iter_default_memory_files():
    for root, _dirs, filenames in os.walk(DEFAULT_MEMORY_SOURCE_DIR):
        for filename in filenames:
            source_path = os.path.join(root, filename)
            relative_path = os.path.relpath(source_path, DEFAULT_MEMORY_SOURCE_DIR)
            yield source_path, relative_path


def _ensure_memory_index_entry(memory_dir):
    index_path = os.path.join(memory_dir, "memory_index.md")
    default_entries = _default_memory_index_entries()
    if os.path.exists(index_path):
        with open(index_path, encoding="utf-8") as index_file:
            content = index_file.read()
        separator = "" if content.endswith("\n") else "\n"
        entries_to_add = [
            entry for entry in default_entries
            if _memory_index_entry_key(entry) not in content
        ]
        if not entries_to_add:
            return
        updated_content = f"{content}{separator}{''.join(entries_to_add)}"
    else:
        updated_content = "# Memory 文件目录\n\n" + "".join(default_entries)

    with open(index_path, "w", encoding="utf-8") as index_file:
        index_file.write(updated_content)


def _default_memory_index_entries():
    if not os.path.isdir(DEFAULT_MEMORY_SOURCE_DIR):
        return []

    entries = []
    for name in sorted(os.listdir(DEFAULT_MEMORY_SOURCE_DIR)):
        source_path = os.path.join(DEFAULT_MEMORY_SOURCE_DIR, name)
        if os.path.isdir(source_path):
            key = f"{name}/"
            description = DEFAULT_MEMORY_INDEX_DESCRIPTIONS.get(
                key,
                "流水线默认记忆目录，包含可复用项目背景、约束或参考资料。",
            )
        elif os.path.isfile(source_path):
            key = name
            description = DEFAULT_MEMORY_INDEX_DESCRIPTIONS.get(key, "流水线默认记忆文件。")
        else:
            continue
        entries.append(f"- `{key}`：{description}\n")
    return entries


def _memory_index_entry_key(entry):
    start = entry.find("`")
    end = entry.find("`", start + 1)
    if start == -1 or end == -1:
        return entry.strip()
    return entry[start + 1:end]


def _install_static_analysis_tools():
    """在环境准备阶段安装多语言静态扫描依赖的全部 CLI 工具。

    覆盖：detekt(Kotlin)/checkstyle(Java)/ruff(Python)/swiftlint(Swift) 经 Homebrew，
    eslint(JS·TS) 经 npm；PMD CPD（代码重复）已含于 pmd。必须在扫描使用前完成安装，
    避免到扫描时才发现缺失。
    """
    missing = [command for command in STATIC_ANALYSIS_TOOLS if shutil.which(command) is None]
    if missing:
        if shutil.which("brew") is None:
            raise RuntimeError(
                "缺少静态扫描工具（" + "、".join(missing) + "），且未找到 Homebrew，无法自动安装。"
                "请先安装 Homebrew 后重试。"
            )
        print(f"  📦 安装静态扫描工具: {'、'.join(missing)}")
        subprocess.run(["brew", "install", *missing], check=True)
    for command in STATIC_ANALYSIS_NPM_TOOLS:
        if shutil.which(command) is not None:
            continue
        if shutil.which("npm") is None:
            print(f"  ⚠️ 未找到 npm，跳过 {command} 安装（JS/TS 静态扫描将降级为提示）。")
            continue
        print(f"  📦 安装静态扫描工具: {command}")
        subprocess.run(["npm", "install", "-g", f"{command}@9"], check=True)
    print("  ✅ 静态扫描工具已就绪: " + "、".join(STATIC_ANALYSIS_TOOLS + STATIC_ANALYSIS_NPM_TOOLS))


def _ensure_codegraph_cli():
    """Return the CodeGraph executable, installing it through npm when absent."""
    codegraph_path = shutil.which("codegraph")
    if codegraph_path is not None:
        return codegraph_path

    npm_path = shutil.which("npm")
    if npm_path is None:
        print("  ⚠️ CodeGraph 安装失败：未找到 npm；跳过代码图准备，继续执行流水线。")
        return None

    try:
        print(f"  📦 安装 CodeGraph: {CODEGRAPH_NPM_PACKAGE}")
        subprocess.run(
            [npm_path, "install", "-g", CODEGRAPH_NPM_PACKAGE],
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"  ⚠️ CodeGraph 安装失败：{error}；跳过代码图准备，继续执行流水线。")
        return None

    codegraph_path = shutil.which("codegraph")
    if codegraph_path is None:
        print("  ⚠️ CodeGraph 安装完成但命令不在 PATH 中；跳过代码图准备，继续执行流水线。")
        return None
    return codegraph_path


def _work_dir_is_empty(work_dir):
    """Treat VCS/index metadata alone as an empty project."""
    if not os.path.isdir(work_dir):
        return True
    return not any(name not in {".git", ".codegraph"} for name in os.listdir(work_dir))


def _prepare_codegraph(work_dir):
    """Initialize or refresh CodeGraph without making it a pipeline prerequisite."""
    codegraph_path = _ensure_codegraph_cli()
    if codegraph_path is None:
        return

    index_path = os.path.join(work_dir, ".codegraph")
    if not os.path.isdir(index_path) and _work_dir_is_empty(work_dir):
        print("  ⚠️ CodeGraph 跳过初始化：工作目录为空；继续执行流水线。")
        return

    try:
        action = "sync" if os.path.isdir(index_path) else "init"
        print(f"  🕸️ CodeGraph {action}: {work_dir}")
        subprocess.run([codegraph_path, action, work_dir], check=True)
        subprocess.run([codegraph_path, "status", work_dir], check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"  ⚠️ CodeGraph 准备失败：{error}；继续执行流水线。")


def setup_environment():
    os.makedirs(PROJECT_ROOT, exist_ok=True)
    _install_static_analysis_tools()
    for repo_url, branch in REPOS:
        _clone_or_pull(repo_url, branch, _repo_target_path(repo_url))
    work_dir = _resolve_agent_work_dir()
    _prepare_codegraph(work_dir)
    _ensure_default_memory(work_dir)
    return work_dir
