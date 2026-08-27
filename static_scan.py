"""多语言静态扫描：供 pipeline.py 与 break_pipeline.py 共用（两模块彼此独立）。

语言与工具：
- Kotlin → detekt（魔法数/复杂度/内聚耦合）+ PMD CPD（代码重复）
- Java   → checkstyle（MagicNumber/复杂度/耦合）+ PMD CPD
- Python → ruff（PLR2004 魔法数 + C901/PLR 复杂度）+ PMD CPD
- JS/TS  → eslint（no-magic-numbers + 复杂度）+ PMD CPD
- Swift  → swiftlint（no_magic_numbers + 复杂度）+ PMD CPD

排除目录：内置默认（build/.gradle/.git/venv/node_modules 等）叠加
static-analysis/scan_config.json 的 exclude_dirs（如 mock-server 这类
流水线自验证/辅助工具目录，不参与项目代码质量扫描）。
所有工具都以“显式文件列表”方式调用，保证排除规则统一生效。
"""

import json
import os
import shutil
import subprocess
import tempfile

from config import DETEKT_CONFIG_PATH, STATIC_ANALYSIS_DIR

SCAN_CONFIG_PATH = os.path.join(STATIC_ANALYSIS_DIR, "scan_config.json")
CHECKSTYLE_CONFIG_PATH = os.path.join(STATIC_ANALYSIS_DIR, "checkstyle-config.xml")
SWIFTLINT_CONFIG_PATH = os.path.join(STATIC_ANALYSIS_DIR, ".swiftlint.yml")
ESLINT_CONFIG_PATH = os.path.join(STATIC_ANALYSIS_DIR, "eslint.config.mjs")

# 工具超时（秒）；大仓库多语言全量扫描可能较慢
TOOL_TIMEOUT_SECONDS = 600

DEFAULT_EXCLUDE_DIRS = {
    "build",
    ".gradle",
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".idea",
    ".kotlin",
    "Pods",
    ".build",
    "dist",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
}

LANGUAGE_EXTENSIONS = {
    "kotlin": (".kt", ".kts"),
    "java": (".java",),
    "python": (".py",),
    "typescript": (".ts", ".tsx"),
    "ecmascript": (".js", ".jsx", ".mjs", ".cjs"),
    "swift": (".swift",),
}

LANGUAGE_LABELS = {
    "kotlin": "Kotlin",
    "java": "Java",
    "python": "Python",
    "typescript": "TypeScript",
    "ecmascript": "JavaScript",
    "swift": "Swift",
}

LANGUAGE_TOOLS = {
    "kotlin": "detekt",
    "java": "checkstyle",
    "python": "ruff",
    "typescript": "eslint",
    "ecmascript": "eslint",
    "swift": "swiftlint",
}

CPD_LANGUAGE = {
    "kotlin": "kotlin",
    "java": "java",
    "python": "python",
    "typescript": "typescript",
    "ecmascript": "ecmascript",
    "swift": "swift",
}


def exclude_dirs():
    """内置默认排除 + scan_config.json 配置的排除目录（如 mock-server）。"""
    configured = []
    try:
        with open(SCAN_CONFIG_PATH, encoding="utf-8") as config_file:
            config = json.load(config_file)
        if isinstance(config, dict) and isinstance(config.get("exclude_dirs"), list):
            configured = [str(item).strip() for item in config["exclude_dirs"] if str(item).strip()]
    except (OSError, ValueError):
        pass
    return DEFAULT_EXCLUDE_DIRS | set(configured)


def resolve_scan_root(work_dir):
    """扫描根为整个项目工作目录（覆盖 安卓 app / iOS / 后端 各子目录），
    具体排除交给 exclude_dirs() 统一处理。"""
    return os.path.abspath(work_dir)


def detect_languages(scan_root, exclusions=None):
    """返回 {language: [绝对文件路径]}，已应用排除目录。"""
    exclusions = exclusions if exclusions is not None else exclude_dirs()
    found = {}
    if not os.path.isdir(scan_root):
        return found
    for root, dirs, files in os.walk(scan_root):
        dirs[:] = [name for name in dirs if name not in exclusions]
        for name in files:
            lower = name.lower()
            for language, extensions in LANGUAGE_EXTENSIONS.items():
                if lower.endswith(extensions):
                    found.setdefault(language, []).append(os.path.join(root, name))
                    break
    return found


def source_file_count(scan_root, exclusions=None):
    return sum(len(files) for files in detect_languages(scan_root, exclusions).values())


def run_static_scan(scan_root, report_path):
    """主入口：扫描 scan_root，多语言结果写入 report_path。"""
    exclusions = exclude_dirs()
    languages = detect_languages(scan_root, exclusions)
    sections = [
        "# 代码静态扫描报告",
        "",
        f"- 扫描范围: {scan_root}",
        "- 扫描工具: detekt(Kotlin)/checkstyle(Java)/ruff(Python)/eslint(JS·TS)/swiftlint(Swift)/PMD CPD(代码重复)",
        f"- 排除目录: {', '.join(sorted(exclusions))}",
    ]
    if not languages:
        sections.append("")
        sections.append("未发现可静态扫描的 Kotlin/Java/Python/JS/TS/Swift 源码文件，跳过静态扫描。")
        _write_report(report_path, sections)
        return
    sections.append(f"- 源码文件数: {source_file_count(scan_root, exclusions)}")
    for language in sorted(languages):
        sections.append("")
        sections.append(f"## {LANGUAGE_LABELS[language]} 规则扫描（{LANGUAGE_TOOLS[language]}）")
        sections.append("")
        sections.append(_run_language_rules(language, languages[language], scan_root))
    sections.append("")
    sections.append("## 代码重复（PMD CPD）")
    sections.append("")
    cpd_parts = []
    for language in sorted(languages):
        output = _run_cpd(language, languages[language])
        if output:
            cpd_parts.append(f"### {LANGUAGE_LABELS[language]}\n\n{output}")
    sections.append("\n\n".join(cpd_parts) if cpd_parts else "✅ 未发现代码重复。")
    _write_report(report_path, sections)


def _run_language_rules(language, files, scan_root):
    runners = {
        "kotlin": _run_detekt,
        "java": _run_checkstyle,
        "python": _run_ruff,
        "typescript": lambda f: _run_eslint(f, scan_root),
        "ecmascript": lambda f: _run_eslint(f, scan_root),
        "swift": _run_swiftlint,
    }
    return runners[language](files)


def _run_detekt(files):
    if shutil.which("detekt") is None:
        return "⚠️ 未安装 detekt，跳过 Kotlin 规则扫描。"
    config_args = ["--config", DETEKT_CONFIG_PATH] if os.path.isfile(DETEKT_CONFIG_PATH) else []
    with tempfile.TemporaryDirectory() as tmp_dir:
        report_file = os.path.join(tmp_dir, "detekt.txt")
        command = ["detekt", "--input", ",".join(files), *config_args, "--report", f"txt:{report_file}"]
        try:
            subprocess.run(command, check=False, capture_output=True, text=True, timeout=TOOL_TIMEOUT_SECONDS)
        except (OSError, subprocess.TimeoutExpired) as error:
            return f"⚠️ detekt 执行失败: {error}"
        try:
            with open(report_file, encoding="utf-8") as handle:
                content = handle.read().strip()
        except OSError:
            content = ""
    if not content:
        return "✅ detekt 未发现问题。"
    return content


def _run_checkstyle(files):
    if shutil.which("checkstyle") is None:
        return "⚠️ 未安装 checkstyle，跳过 Java 规则扫描。"
    command = ["checkstyle", "-c", CHECKSTYLE_CONFIG_PATH, "-f", "plain", *files]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT_SECONDS,
            env=_java21_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"⚠️ checkstyle 执行失败: {error}"
    output = _strip_checkstyle_noise((result.stdout or "") + (result.stderr or ""))
    if not output:
        return "✅ checkstyle 未发现问题。"
    return output


def _java21_env():
    env = dict(os.environ)
    java_home = "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
    if os.path.isdir(java_home):
        env["JAVA_HOME"] = java_home
    return env


def _strip_checkstyle_noise(text):
    noise_prefixes = ("开始检查", "检查完成", "Checkstyle以", "ERROR: 无法初始化", "Exception", "at ")
    lines = [
        line
        for line in text.splitlines()
        if line.strip() and not any(line.strip().startswith(prefix) for prefix in noise_prefixes)
    ]
    return "\n".join(lines)


def _run_ruff(files):
    if shutil.which("ruff") is None:
        return "⚠️ 未安装 ruff，跳过 Python 规则扫描。"
    command = [
        "ruff", "check", *files,
        "--select", "PLR2004,C901,PLR0911,PLR0912,PLR0913,PLR0915",
        "--output-format", "concise",
        "--no-cache",
    ]
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=TOOL_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"⚠️ ruff 执行失败: {error}"
    output = (result.stdout or "").strip()
    if not output:
        return "✅ ruff 未发现问题。"
    return output


def _run_eslint(files, scan_root):
    if shutil.which("eslint") is None:
        return "⚠️ 未安装 eslint，跳过 JS/TS 规则扫描。"
    # eslint 9 的 flat config 以项目目录为基准：必须用相对路径并在 scan_root 下运行
    relative_files = [os.path.relpath(file, scan_root) for file in files]
    command = ["eslint", "--config", ESLINT_CONFIG_PATH, "--no-warn-ignored", *relative_files]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT_SECONDS,
            cwd=scan_root,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"⚠️ eslint 执行失败: {error}"
    output = (result.stdout or "").strip()
    if not output:
        return "✅ eslint 未发现问题。"
    return output


def _run_swiftlint(files):
    if shutil.which("swiftlint") is None:
        return "⚠️ 未安装 swiftlint，跳过 Swift 规则扫描。"
    env = dict(os.environ)
    # SwiftLint 需要加载 sourcekitdInProc.framework（CommandLineTools）
    env.setdefault("DYLD_FRAMEWORK_PATH", "/Library/Developer/CommandLineTools/usr/lib")
    command = ["swiftlint", "lint", "--config", SWIFTLINT_CONFIG_PATH, "--quiet", *files]
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=TOOL_TIMEOUT_SECONDS, env=env)
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"⚠️ swiftlint 执行失败: {error}"
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    if not output:
        return "✅ swiftlint 未发现问题。"
    return output


def _run_cpd(language, files):
    if shutil.which("pmd") is None:
        return "⚠️ 未安装 pmd，跳过代码重复扫描。"
    command = [
        "pmd", "cpd",
        "-d", ",".join(files),
        "--language", CPD_LANGUAGE[language],
        "--minimum-tokens", "60",
        "--format", "text",
        "--no-fail-on-violation",
        "--no-fail-on-error",
    ]
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=TOOL_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"⚠️ PMD CPD 执行失败: {error}"
    output = (result.stdout or "").strip()
    if not output:
        return ""
    # 只保留重复定位摘要（重复块 + 出现文件/行号），丢弃大段重复代码正文，
    # 让审查 Agent 快速聚焦“哪里重复”，需要看正文时自行打开源码。
    summary_lines = [
        line
        for line in output.splitlines()
        if line.startswith("Found a ") or line.startswith("Starting at line ")
    ]
    if not summary_lines:
        return output
    return "\n".join(summary_lines)


def _write_report(report_path, sections):
    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as report_file:
        report_file.write("\n".join(sections) + "\n")


def main(argv=None):
    """CLI：供静态扫描小需求的开发 Agent 调用。"""
    import argparse

    parser = argparse.ArgumentParser(description="多语言代码静态扫描")
    parser.add_argument(
        "--work-dir",
        default=".",
        help="项目工作目录（扫描根经 resolve_scan_root 解析）",
    )
    parser.add_argument(
        "--report",
        required=True,
        help="输出报告路径，例如 requirements/R-00x-static-scan/static_scan_report.md",
    )
    args = parser.parse_args(argv)
    run_static_scan(resolve_scan_root(args.work_dir), os.path.abspath(args.report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
