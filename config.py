import json
import os
import re

# Source repo root (where this config lives)
SOURCE_REPO_DIR = os.path.dirname(os.path.abspath(__file__))
SYSTEM_PROMPT_DIR = os.path.join(SOURCE_REPO_DIR, "system-prompt")

PIPELINE_CONFIG_PATH = os.path.join(SOURCE_REPO_DIR, "config", "config.json")
EXTERNAL_SKILL_AGENT_NAMES = {
    'codex': 'Codex', 'claude': 'Claude Code', 'cursor': 'Cursor', 'opencode': 'OpenCode',
}


def _non_empty_string(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} in config/config.json must be a non-empty string")
    return value


def _string_array(value, field):
    if not isinstance(value, list) or not value:
        raise ValueError(f'{field} in config/config.json must be a non-empty string array')
    for item in value:
        _non_empty_string(item, field)


def _external_dependencies(runtime_config, key):
    entries = runtime_config.get(key, [])
    if not isinstance(entries, list):
        raise ValueError(f'{key} in config/config.json must be an array')
    seen = set()
    for index, entry in enumerate(entries):
        field = f'{key}[{index}]'
        if not isinstance(entry, dict):
            raise ValueError(f'{field} in config/config.json must be an object')
        if not isinstance(entry.get('enabled', True), bool):
            raise ValueError(f'{field}.enabled must be boolean')
        if key == 'EXTERNAL_CLI_TOOLS':
            identity = _non_empty_string(entry.get('name'), f'{field}.name')
            for command in ('check', 'install'):
                _string_array(entry.get(command), f'{field}.{command}')
            timeout = entry.get('check_timeout', 45)
            if type(timeout) is not int or not 1 <= timeout <= 300:
                raise ValueError(f'{field}.check_timeout must be an integer between 1 and 300')
            path_env = entry.get('path_env')
            if path_env is not None and (not isinstance(path_env, str) or not re.fullmatch(r'PANDA_PIPELINE_[A-Z0-9_]+', path_env)):
                raise ValueError(f'{field}.path_env must use the PANDA_PIPELINE_ prefix')
            checks = entry.get('verify', [])
            if not isinstance(checks, list):
                raise ValueError(f'{field}.verify must be an array')
            for check in checks:
                if not isinstance(check, dict):
                    raise ValueError(f'{field}.verify entries must be objects')
                _string_array(check.get('command'), f'{field}.verify.command')
                _string_array(check.get('contains'), f'{field}.verify.contains')
        else:
            identity = _non_empty_string(entry.get('source'), f'{field}.source')
            if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', identity) or identity.startswith('-'):
                raise ValueError(f'{field}.source must use GitHub owner/repo format')
            _string_array(entry.get('names'), f'{field}.names')
            agents = entry.get('agents', ['codex', 'claude', 'cursor'])
            _string_array(agents, f'{field}.agents')
            if any(agent not in EXTERNAL_SKILL_AGENT_NAMES for agent in agents):
                raise ValueError(f'{field}.agents contains an unsupported agent')
        if identity in seen:
            raise ValueError(f'Duplicate {field}: {identity}')
        seen.add(identity)
    return entries


def _load_pipeline_config():
    with open(PIPELINE_CONFIG_PATH, encoding="utf-8") as config_file:
        runtime_config = json.load(config_file)
    if not isinstance(runtime_config, dict):
        raise ValueError("config/config.json must contain a JSON object")

    project_root = _non_empty_string(
        runtime_config.get("PROJECT_ROOT"),
        "PROJECT_ROOT",
    )

    repos = runtime_config.get("REPOS")
    if not isinstance(repos, list):
        raise ValueError("REPOS in config/config.json must be an array")
    for index, repo in enumerate(repos):
        if not isinstance(repo, dict):
            raise ValueError(f"REPOS[{index}] in config/config.json must be an object")
        _non_empty_string(repo.get("url"), f"REPOS[{index}].url")
        _non_empty_string(repo.get("branch"), f"REPOS[{index}].branch")

    agent_types = runtime_config.get("AGENT_TYPES")
    if not isinstance(agent_types, list):
        raise ValueError("AGENT_TYPES in config/config.json must be an array")
    seen_roles = set()
    for index, agent in enumerate(agent_types):
        if not isinstance(agent, dict):
            raise ValueError(f"AGENT_TYPES[{index}] in config/config.json must be an object")
        role = _non_empty_string(agent.get("role"), f"AGENT_TYPES[{index}].role")
        _non_empty_string(
            agent.get("agent_type"),
            f"AGENT_TYPES[{index}].agent_type",
        )
        if role in seen_roles:
            raise ValueError(
                f"Duplicate Agent role '{role}' in config/config.json AGENT_TYPES"
            )
        seen_roles.add(role)

    return (project_root, repos, agent_types,
            _external_dependencies(runtime_config, 'EXTERNAL_CLI_TOOLS'),
            _external_dependencies(runtime_config, 'EXTERNAL_SKILLS'))


PROJECT_ROOT, REPOS, AGENT_TYPES, EXTERNAL_CLI_TOOLS, EXTERNAL_SKILLS = _load_pipeline_config()


def get_agent_type(role):
    """Return the configured backend for a semantic pipeline role."""
    for agent in AGENT_TYPES:
        if isinstance(agent, dict) and agent.get("role") == role:
            return _non_empty_string(
                agent.get("agent_type"),
                f"Agent role '{role}'",
            )
    raise ValueError(
        f"Missing Agent role '{role}' in config/config.json AGENT_TYPES"
    )
