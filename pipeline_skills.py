"""Render prompts and skills to fixed paths and overwrite project installations."""

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from config import SOURCE_REPO_DIR

SOURCE_ROOT = Path(SOURCE_REPO_DIR)
_PREPARED_ROOTS = {}
NATIVE_ROOTS = ('.agents/skills', '.claude/skills')


def _files(root):
    if root.is_symlink():
        raise RuntimeError(f'不覆盖符号链接：{root}')
    result = {}
    for path in sorted(root.rglob('*')):
        # Executing packaged Python helpers may create bytecode caches. These
        # are runtime output, not authored bundle contents or local edits.
        if '__pycache__' in path.relative_to(root).parts:
            continue
        if path.is_symlink():
            raise RuntimeError(f'不处理 skill 符号链接：{path}')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def _validate_skill(path):
    if not re.fullmatch(r'panda-pipeline-[a-z0-9-]+', path.name):
        raise RuntimeError(f'skill 名称必须以 panda-pipeline- 开头：{path.name}')
    files = _files(path)
    if 'bundle.json' in files:
        raise RuntimeError('不支持 bundle.json；脚本及依赖必须直接放在 skill 目录内')
    entry = files.get('SKILL.md', b'').decode('utf-8')
    front = re.match(r'\A---\s*\n(.*?)\n---(?:\n|$)', entry, re.S)
    if not front or not re.search(r'^name: ' + re.escape(path.name) + r'\s*$', front[1], re.M):
        raise RuntimeError(f'skill name 与目录名称不一致：{path.name}')
    if not re.search(r'^description: \S', front[1], re.M):
        raise RuntimeError(f'skill description 缺失：{path.name}')
    # Validate authored local Markdown links; HTTP links are documentation only.
    for name, raw in files.items():
        if not name.endswith('.md'):
            continue
        for link in re.findall(r'\]\(([^)]+)\)', raw.decode('utf-8')):
            if '://' in link or link.startswith('#'):
                continue
            target = (path / name).parent / link.split('#', 1)[0]
            if (not target.resolve().is_relative_to(path.resolve())
                    or target.resolve().relative_to(path.resolve()).as_posix() not in files):
                raise RuntimeError(f'skill 引用缺失或越界：{path.name}/{name}: {link}')
    return files


def _command(*args):
    values = [str(arg) for arg in args]
    return subprocess.list2cmdline(values) if os.name == 'nt' else shlex.join(values)


def _installed_skills_root(work, agent_type=None):
    location = '.claude/skills' if agent_type == 'claude' else '.agents/skills'
    return work / location


def _render_values(work):
    return {
        '__PANDA_WORK_DIR__': str(work),
        '__PANDA_WORK_DIR_ARG__': _command(work),
        '__PANDA_SKILLS_ROOT__': str(_installed_skills_root(work)),
        '__PANDA_PYTHON__': _command(sys.executable),
        '__PANDA_FIGMA_AUDIT_COMMAND__': 'python3 scripts/figma_asset_audit.py',
        '__PANDA_STATIC_SCAN_COMMAND__': 'python3 scripts/static_scan.py',
        '__ANDROID_EMULATOR_COMMAND__': 'python3 scripts/android_emulator.py',
    }


def _render(text, values):
    # Only explicit runtime tokens. JSON braces and task .format placeholders
    # belong to other protocols and must survive this pass unchanged.
    pattern = r'__PANDA_[A-Z_]+__|__ANDROID_EMULATOR_COMMAND__'
    def substitute(match):
        key = match[0]
        if key not in values:
            raise RuntimeError(f'未知动态渲染占位符：{key}')
        return values[key]
    return re.sub(pattern, substitute, text)


def render_source_prompt(text, work_dir):
    """Compatibility for callers that construct an Agent without environment setup."""
    values = _render_values(Path(work_dir).resolve())
    return _render(text, values)


def _safe_target(work, relative):
    path = work / relative
    for part in (path, *path.parents):
        if part == work:
            break
        if part.is_symlink():
            raise RuntimeError(f'skill 安装目录冲突：{part} 是符号链接')
    return path


def _exclude_local_installation(work):
    """Keep machine-rendered rules out of business commits without editing .gitignore."""
    if not (work / '.git').exists():
        return
    result = subprocess.run(['git', 'rev-parse', '--git-path', 'info/exclude'],
                            cwd=work, capture_output=True, text=True, timeout=10, check=True)
    exclude = Path(result.stdout.strip())
    if not exclude.is_absolute():
        exclude = work / exclude
    patterns = ('/.panda-pipeline/', '/.agents/skills/panda-pipeline-*/',
                '/.claude/skills/panda-pipeline-*/')
    existing = exclude.read_text(encoding='utf-8') if exclude.exists() else ''
    missing = [entry for entry in patterns if entry not in existing.splitlines()]
    if missing:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open('a', encoding='utf-8') as stream:
            stream.write(('\n' if existing and not existing.endswith('\n') else '')
                         + '\n'.join(missing) + '\n')


def _overwrite_files(target, files):
    if target.exists():
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    target.mkdir(parents=True, exist_ok=True)
    for relative, raw in files.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)


def render_pipeline_prompts_and_skills(work_dir):
    """Overwrite generated rules under the pipeline source directory."""
    work = Path(work_dir).resolve()
    skills = SOURCE_ROOT / 'skills'
    packages = {p.name: _validate_skill(p) for p in sorted(skills.iterdir()) if p.is_dir()}
    if not packages:
        raise RuntimeError('流水线 skill 源目录为空')
    root = _safe_target(SOURCE_ROOT.resolve(), 'temp-prompt-skills')
    values = _render_values(work)
    prompts = {}
    for family in ('system-prompt', 'break-system-prompt'):
        for path in sorted((SOURCE_ROOT / family).glob('*.md')):
            prompts[f'{family}/{path.name}'] = _render(path.read_text(encoding='utf-8'), values).encode('utf-8')
    commands = {}
    for family in ('system-command', 'break-command'):
        for path in sorted((SOURCE_ROOT / family).glob('*.md')):
            commands[f'{family}/{path.name}'] = _render(path.read_text(encoding='utf-8'), values).encode('utf-8')
    packages = {name: {file: _render(raw.decode('utf-8'), values).encode('utf-8')
                       if file.endswith('.md') else raw for file, raw in content.items()}
                for name, content in packages.items()}
    # Validate inputs and target paths before replacing any generated files.
    prompt_target = _safe_target(root, 'prompts')
    command_target = _safe_target(root, 'commands')
    skill_target = _safe_target(root, 'skills')
    _overwrite_files(prompt_target, prompts)
    _overwrite_files(command_target, commands)
    _overwrite_files(skill_target, {f'{name}/{file}': raw
                                   for name, content in packages.items() for file, raw in content.items()})
    # Remove only the obsolete generated version directories.
    for old in root.iterdir():
        if re.fullmatch(r'[0-9a-f]{64}', old.name) and old.is_dir() and not old.is_symlink():
            shutil.rmtree(old)
    _PREPARED_ROOTS[str(work)] = root
    return root


def prepare_pipeline_skills(work_dir):
    """Render every startup, then overwrite the project's same-named skills."""
    work = Path(work_dir).resolve()
    root = render_pipeline_prompts_and_skills(work_dir)
    packages = {path.name: _files(path) for path in sorted((root / 'skills').iterdir())}
    targets = [(name, _safe_target(work, f'{location}/{name}'))
               for location in NATIVE_ROOTS for name in packages]
    for name, target in targets:
        _overwrite_files(target, packages[name])
    _safe_target(work, '.panda-pipeline/skills-install.json').unlink(missing_ok=True)
    _exclude_local_installation(work)
    print(f'  ✅ 流水线 prompt/skills 已渲染，覆盖安装 {len(packages)} 项 skills')
    return root


def role_prompt_path(work_dir, source):
    source = Path(source)
    root = _PREPARED_ROOTS.get(str(Path(work_dir).resolve()))
    if root:
        try:
            relative = source.resolve().relative_to(SOURCE_ROOT.resolve())
        except ValueError:
            pass
        else:
            frozen = root / 'prompts' / relative
            if relative.parts[0] in ('system-prompt', 'break-system-prompt'):
                if not frozen.is_file():
                    raise RuntimeError(f'本轮固定角色 prompt 缺失：{frozen}')
                return frozen
    return source


def role_prompt_text(work_dir, source):
    return role_prompt_path(work_dir, source).read_text(encoding='utf-8')


def command_template_text(work_dir, source):
    """Read a task template from the command bundle, never the role prompt bundle."""
    source = Path(source)
    root = _PREPARED_ROOTS.get(str(Path(work_dir).resolve()))
    if root:
        try:
            relative = source.resolve().relative_to(SOURCE_ROOT.resolve())
        except ValueError:
            pass
        else:
            if relative.parts[0] in ('system-command', 'break-command'):
                rendered = root / 'commands' / relative
                if not rendered.is_file():
                    raise RuntimeError(f'本轮命令模板缺失：{rendered}')
                return rendered.read_text(encoding='utf-8')
    return render_source_prompt(source.read_text(encoding='utf-8'), work_dir)


def skill_context(work_dir, agent_type=None):
    work = Path(work_dir).resolve()
    if str(work) not in _PREPARED_ROOTS:
        return ''
    installed = _installed_skills_root(work, agent_type)
    return (
        '\n[流水线 skill 入口]\n'
        f'项目已安装 skills 目录（绝对路径）：{installed}。'
        '按当前角色 prompt 的触发条件读取 <安装目录>/<skill名>/SKILL.md 及指定引用。'
        '规则文件不可读须报告入口错误，不静默跳过；不因本提示触发无关 skill。\n'
    )
