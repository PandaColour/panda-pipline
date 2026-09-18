"""Repository checkout and work-directory setup shared by workflow entry points."""

import os
import json
import re
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import PROJECT_ROOT, REPOS, EXTERNAL_CLI_TOOLS, EXTERNAL_SKILLS, EXTERNAL_SKILL_AGENT_NAMES
from pipeline_skills import prepare_pipeline_skills


DEFAULT_MEMORY_FILENAME = "loan_pipeline_default.md"
DEFAULT_MEMORY_SOURCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "default-memory")
DEFAULT_MEMORY_INDEX_DESCRIPTIONS = {
    DEFAULT_MEMORY_FILENAME: "贷款系统开发流水线默认记忆，约束多国家、多端贷款项目的职责边界、通信协议、加解密、配置化、Mock 和验收纪律。",
    "Network/": "App 端网络协议和加解密基础设施 demo，供端侧接入真实协议时参考，不代表真实后端联调已通过。",
}

STATIC_ANALYSIS_TOOLS = ("detekt", "pmd", "checkstyle", "ruff", "swiftlint")
STATIC_ANALYSIS_NPM_TOOLS = ("eslint",)
CODEGRAPH_NPM_PACKAGE = "@colbymchenry/codegraph"
FIGMA_MCP_NAME = "figma-android-mcp"
FIGMA_MCP_TOOLS = {"get_figma_node", "get_skill", "download_figma_images"}
MCP_CHECK_TIMEOUT = 45


def _external_executable(command):
    expanded = os.path.expanduser(command)
    return shutil.which(expanded) or expanded


def _external_command(command, work_dir, timeout=45):
    executable = _external_executable(command[0])
    return subprocess.run(
        [executable, *command[1:]], cwd=work_dir, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=timeout,
    )


def _external_skill_inventory(work_dir):
    result = _external_command(['npx', '--yes', 'skills', 'ls', '-g', '--json'], work_dir)
    if result.returncode:
        raise RuntimeError('skills 清单查询失败')
    inventory = json.loads(result.stdout)
    if not isinstance(inventory, list) or any(
        not isinstance(row, dict) or not isinstance(row.get('name'), str)
        or not isinstance(row.get('agents'), list)
        or any(not isinstance(agent, str) for agent in row['agents']) or 'source' not in row
        for row in inventory
    ):
        raise ValueError('skills JSON 清单格式不兼容')
    return inventory


def _external_skills_ready(entry, inventory):
    agents = entry.get('agents', ['codex', 'claude', 'cursor'])
    required_agents = {EXTERNAL_SKILL_AGENT_NAMES[agent] for agent in agents}
    return all(any(
        row['name'] == name and row.get('source') == entry['source']
        and row.get('scope') == 'global' and required_agents.issubset(row['agents'])
        for row in inventory
    ) for name in entry['names'])


def _prepare_external_dependencies(work_dir):
    """Check configured global tools/skills; install missing entries once, then verify."""
    for entry in EXTERNAL_CLI_TOOLS:
        path_env = entry.get('path_env')
        if path_env:
            os.environ[path_env] = ''
        if not entry.get('enabled', True):
            continue
        name = entry['name']
        try:
            try:
                ready = _external_command(entry['check'], work_dir, entry.get('check_timeout', 45)).returncode == 0
            except FileNotFoundError:
                ready = False
            if not ready:
                print(f'  📦 安装外部 CLI: {name}')
                result = _external_command(entry['install'], work_dir, timeout=300)
                if result.returncode or _external_command(entry['check'], work_dir, entry.get('check_timeout', 45)).returncode:
                    raise RuntimeError('安装后检查未通过')
            for check in entry.get('verify', []):
                result = _external_command(check['command'], work_dir, timeout=15)
                if result.returncode or any(text not in result.stdout + result.stderr for text in check['contains']):
                    raise RuntimeError('能力检查未通过')
            if path_env:
                executable = _external_executable(entry['check'][0])
                os.environ[path_env] = str((Path(work_dir) / executable).resolve())
            print(f'  ✅ 外部 CLI 已就绪: {name}')
        except (OSError, subprocess.SubprocessError, RuntimeError) as error:
            print(f'  ⚠️ 外部 CLI {name} 未就绪（{type(error).__name__}）；继续流水线。')

    entries = [entry for entry in EXTERNAL_SKILLS if entry.get('enabled', True)]
    if not entries:
        return
    try:
        inventory = _external_skill_inventory(work_dir)
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as error:
        print(f'  ⚠️ 外部 skills 清单未确认（{type(error).__name__}）；本轮不安装，继续流水线。')
        return
    for entry in entries:
        try:
            if not _external_skills_ready(entry, inventory):
                print(f'  📦 安装外部 skills: {entry["source"]}')
                # The skills CLI uses claude-code; pipeline configuration uses claude.
                agents = ['claude-code' if agent == 'claude' else agent
                          for agent in entry.get('agents', ['codex', 'claude', 'cursor'])]
                command = ['npx', '--yes', 'skills', 'add', entry['source'], '-y', '-g',
                           '--agent', *agents]
                result = _external_command(command, work_dir, timeout=300)
                if result.returncode:
                    raise RuntimeError('skills 安装失败')
                inventory = _external_skill_inventory(work_dir)
                if not _external_skills_ready(entry, inventory):
                    raise RuntimeError('安装后检查未通过')
            print(f'  ✅ 外部 skills 必需项已就绪: {entry["source"]}')
        except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as error:
            reason = str(error) if isinstance(error, RuntimeError) else type(error).__name__
            print(f'  ⚠️ 外部 skills {entry["source"]} 未就绪（{reason}）；继续流水线。')
            # A failed install/query may have changed the inventory; do not reuse stale data.
            return


def _mcp_config(path):
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        data = tomllib.loads(text) if path.suffix == ".toml" else json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("expected object")
        return data
    except (OSError, ValueError):
        # Parser errors can include the line containing a credential.
        raise RuntimeError(f"MCP 配置无法读取或解析：{path}") from None


def _write_private_config(path, text):
    """Atomic local settings update; never expose the contents on stdout."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _trust_codex_project(config_path, work_dir):
    """Trust this workspace before Codex resolves project MCP configuration."""
    project = str(Path(work_dir).resolve())
    data = _mcp_config(config_path)
    if data.get("projects", {}).get(project, {}).get("trust_level") == "trusted":
        return
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    # Locate the standard projects.<path> table by parsing its header, not by
    # assuming quote style or treating Windows paths as regexes.
    headers = list(re.finditer(r"(?m)^\s*\[([^\n]+)\][ \t]*(?:#[^\n]*)?$", text))
    for index, header in enumerate(headers):
        try:
            table = tomllib.loads(header.group(0)).get("projects", {})
        except ValueError:
            continue
        if table.get(project) != {}:
            continue
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        body = text[header.end():end]
        if re.search(r'(?m)^[ \t]*trust_level[ \t]*=', body):
            body = re.sub(r'(?m)^([ \t]*trust_level[ \t]*=)[^\n]*',
                          r'\1 "trusted"', body, count=1)
        else:
            body = '\ntrust_level = "trusted"\n' + body
        text = text[:header.end()] + body + text[end:]
        break
    else:
        text += f'\n[projects.{json.dumps(project, ensure_ascii=False)}]\ntrust_level = "trusted"\n'
    try:
        updated = tomllib.loads(text)
        assert updated["projects"][project]["trust_level"] == "trusted"
    except (ValueError, KeyError, AssertionError):
        raise RuntimeError("Codex 项目信任配置格式不支持自动更新；原配置未修改") from None
    _write_private_config(config_path, text)
    print("  ✅ Codex：当前项目已设为 trusted")


def _mcp_command(command, work_dir):
    try:
        result = subprocess.run(command, cwd=work_dir, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, encoding="utf-8",
                                timeout=MCP_CHECK_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        raise RuntimeError("MCP 客户端检查超时") from None
    except OSError:
        raise RuntimeError("MCP 客户端命令无法启动") from None
    if result.returncode:
        raise RuntimeError("MCP 客户端命令失败（检查客户端配置、权限及服务连接）")
    # Native `get` output can contain tokens: only callers inspect it in memory.
    return result.stdout


def _expand_mcp_env(value):
    if not isinstance(value, str):
        return ""
    def expand(match):
        key = match.group(1).removeprefix("env:")
        name, sep, default = key.partition(":-")
        return os.environ.get(name, default if sep else "")
    return re.sub(r"\$\{([^}]+)\}", expand, value).strip()


def _figma_credential(server):
    transport = server.get("transport", server)
    if transport.get("url"):
        headers = {k.lower(): _expand_mcp_env(v) for k, v in
                   (transport.get("headers") or transport.get("http_headers") or {}).items()}
        for key, variable in (transport.get("env_http_headers") or {}).items():
            headers[key.lower()] = os.environ.get(variable, "").strip()
        token = headers.get("x-figma-token", "")
        if not token:
            raise RuntimeError("HTTP MCP 缺少 X-Figma-Token；启动环境变量不会自动变成请求头")
        return "X-Figma-Token", token
    variables = dict(os.environ)
    variables.update(transport.get("env") or {})
    token = _expand_mcp_env(variables.get("FIGMA_API_KEY"))
    if token:
        return "X-Figma-Token", token
    oauth = _expand_mcp_env(variables.get("FIGMA_OAUTH_TOKEN"))
    if oauth:
        return "Authorization", "Bearer " + oauth
    raise RuntimeError("stdio MCP 缺少 FIGMA_API_KEY / FIGMA_OAUTH_TOKEN")


def _check_figma_token(header, token):
    """Check identity, not file access or image quota. Never log user data."""
    request = Request("https://api.figma.com/v1/me", headers={header: token})
    try:
        with urlopen(request, timeout=10):
            return "valid"
    except HTTPError as error:
        try:
            if error.code == 429:
                return "rate_limited"
            if error.code == 401:
                return "invalid"
            if error.code == 403:
                body = error.read(4096).decode("utf-8", errors="replace").lower()
                # /me has a separate current_user:read scope. A file-reading
                # token lacking that scope is not necessarily expired/invalid.
                return "scope" if "scope" in body else "invalid"
            return "unverified"
        finally:
            error.close()
    except (URLError, OSError, ValueError):
        return "unverified"


def _approve_cursor_project_mcps(work_dir):
    """Approve every project-configured service in this Cursor workspace."""
    servers = _mcp_config(Path(work_dir) / '.cursor/mcp.json').get('mcpServers', {})
    if not isinstance(servers, dict):
        raise RuntimeError('Cursor 项目 mcpServers 配置必须为对象')
    if not servers:
        return set()
    from agents.cursor import build_cursor_base_cmd
    try:
        executable = build_cursor_base_cmd()[0]
    except FileNotFoundError:
        print('  ⚠️ Cursor 已配置项目 MCP，但未安装客户端，跳过批准')
        return set()
    approved, errors = set(), []
    for name in servers:
        try:
            _mcp_command([executable, 'mcp', 'enable', name], work_dir)
            approved.add(name)
        except RuntimeError as error:
            errors.append(f'{name}: {error}')
    if errors:
        raise RuntimeError('Cursor 项目 MCP 批准失败：' + '；'.join(errors))
    print(f'  ✅ Cursor：当前项目全部 {len(approved)} 个 MCP 服务已批准')
    return approved


def _approve_claude_project_mcps(work_dir):
    """The pipeline authorizes all project MCPs, not shell/file permissions."""
    if not shutil.which("claude") or not _mcp_config(Path(work_dir) / ".mcp.json").get("mcpServers"):
        return
    path = Path(work_dir) / ".claude/settings.local.json"
    data = _mcp_config(path)
    disabled = data.get("disabledMcpjsonServers", [])
    if not isinstance(disabled, list):
        raise RuntimeError("Claude MCP 批准列表格式无效")
    if data.get("enableAllProjectMcpServers") is True and not disabled:
        return
    data["enableAllProjectMcpServers"] = True
    if disabled:
        data["disabledMcpjsonServers"] = []
    _write_private_config(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print("  ✅ Claude：当前项目全部 MCP 服务已批准")


def _configured_figma_clients(work_dir):
    """Return configured clients only. Keep credentials in memory."""
    home, work = Path.home(), Path(work_dir)
    cursor_home = Path(os.environ.get("CURSOR_CONFIG_DIR") or
                       (str(Path(os.environ["XDG_CONFIG_HOME"]) / "cursor")
                        if os.environ.get("XDG_CONFIG_HOME") else str(home / ".cursor")))
    cursor = _mcp_config(cursor_home / "mcp.json").get("mcpServers", {})
    cursor.update(_mcp_config(work / ".cursor/mcp.json").get("mcpServers", {}))
    if FIGMA_MCP_NAME in cursor:
        yield "Cursor", "agent", cursor[FIGMA_MCP_NAME], None

    claude_home = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(home / ".claude")))
    claude_path = claude_home / ".claude.json" if os.environ.get("CLAUDE_CONFIG_DIR") else home / ".claude.json"
    claude = _mcp_config(claude_path)
    project_servers = _mcp_config(work / ".mcp.json").get("mcpServers", {})
    local_servers = claude.get("projects", {}).get(str(work.resolve()), {}).get("mcpServers", {})
    servers = {**claude.get("mcpServers", {}), **project_servers, **local_servers}
    if FIGMA_MCP_NAME in servers:
        yield "Claude", "claude", servers[FIGMA_MCP_NAME], None

    codex_path = Path(os.environ.get("CODEX_HOME", str(home / ".codex"))) / "config.toml"
    codex = _mcp_config(codex_path).get("mcp_servers", {})
    codex.update(_mcp_config(work / ".codex/config.toml").get("mcp_servers", {}))
    if FIGMA_MCP_NAME in codex:
        yield "Codex", "codex", codex[FIGMA_MCP_NAME], codex_path


def _prepare_figma_mcp(work_dir):
    """Approve project MCPs, then validate configured Figma clients at startup."""
    cursor_approved = _approve_cursor_project_mcps(work_dir)
    _approve_claude_project_mcps(work_dir)
    checked_tokens, errors = {}, []
    for client, binary, server, extra in _configured_figma_clients(work_dir):
        executable = shutil.which(binary)
        if client == "Cursor":
            from agents.cursor import build_cursor_base_cmd
            try:
                executable = build_cursor_base_cmd()[0]
            except FileNotFoundError:
                executable = None
        if executable is None:
            print(f"  ⚠️ {client} 已配置 Figma MCP，但未安装客户端，跳过检查")
            continue
        try:
            if client == "Codex":
                _trust_codex_project(extra, work_dir)
                server = json.loads(_mcp_command(
                    [executable, "mcp", "get", FIGMA_MCP_NAME, "--json"], work_dir))
                if not server.get("enabled", True):
                    raise RuntimeError("Codex Figma MCP 被 disabled/策略禁用")
                disabled = set(server.get("disabled_tools") or [])
                allowed = server.get("enabled_tools")
                missing = FIGMA_MCP_TOOLS & disabled
                if allowed is not None:
                    missing |= FIGMA_MCP_TOOLS - set(allowed)
                if missing:
                    raise RuntimeError("Codex Figma 工具被过滤：" + ", ".join(sorted(missing)))
            credential = _figma_credential(server)
            if credential not in checked_tokens:
                checked_tokens[credential] = _check_figma_token(*credential)
            state = checked_tokens[credential]
            if state == "invalid":
                raise RuntimeError("Figma Token 无效或身份接口拒绝访问，请检查 Token/权限")
            if state == "valid":
                print(f"  ✅ {client} Figma Token 有效（身份校验；不代表文件权限/下载配额）")
            else:
                reason = {"rate_limited": "429 限流，不重复探测", "scope": "缺少 current_user:read 校验权限",
                          "unverified": "网络/服务异常"}[state]
                print(f"  ⚠️ {client} Figma Token 未验证：{reason}；继续现有物料降级流程")
            if client == "Cursor":
                if FIGMA_MCP_NAME not in cursor_approved:
                    _mcp_command([executable, "mcp", "enable", FIGMA_MCP_NAME], work_dir)
                tools = _mcp_command([executable, "mcp", "list-tools", FIGMA_MCP_NAME], work_dir)
                if not FIGMA_MCP_TOOLS.issubset(set(re.findall(r"\b[a-z_]+\b", tools))):
                    raise RuntimeError("Cursor Figma 工具列表不完整")
                print("  ✅ Cursor：Figma MCP 已批准，三个工具可发现")
            elif client == "Claude":
                status = _mcp_command([executable, "mcp", "get", FIGMA_MCP_NAME], work_dir)
                if not re.search(r"Status:\s*[✓✔]\s*Connected\b", status):
                    raise RuntimeError("Claude Figma MCP 未连接或仍需批准，请检查服务/托管策略")
                print("  ✅ Claude：Figma MCP 已连接")
            else:
                print("  ✅ Codex：项目已信任，Figma MCP 已启用且必要工具未被过滤（连接由启动时建立）")
        except (RuntimeError, ValueError, OSError) as error:
            # Never echo CLI stderr, JSON/TOML parse errors or credential values.
            message = str(error) if isinstance(error, RuntimeError) else "配置格式或本地文件操作失败"
            errors.append(f"{client}: {message}")
    if errors:
        raise RuntimeError("Figma MCP 环境准备失败：" + "；".join(errors)) from None


def _repo_name(repo_url):
    return repo_url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")


def _repo_target_path(repo_url):
    return os.path.join(PROJECT_ROOT, _repo_name(repo_url))


def _resolve_agent_work_dir():
    if len(REPOS) == 1:
        return _repo_target_path(REPOS[0]["url"])
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
    for repo in REPOS:
        repo_url = repo["url"]
        branch = repo["branch"]
        _clone_or_pull(repo_url, branch, _repo_target_path(repo_url))
    work_dir = _resolve_agent_work_dir()
    _prepare_external_dependencies(work_dir)
    prepare_pipeline_skills(work_dir)
    _prepare_figma_mcp(work_dir)
    _prepare_codegraph(work_dir)
    _ensure_default_memory(work_dir)
    return work_dir
