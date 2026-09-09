import json
import os

# Source repo root (where this config lives)
SOURCE_REPO_DIR = os.path.dirname(os.path.abspath(__file__))
SYSTEM_PROMPT_DIR = os.path.join(SOURCE_REPO_DIR, "system-prompt")

# 代码静态扫描（detekt）规则文件：pipeline.py 与 break_pipeline.py 共用同一份配置，
# 两个模块彼此独立，只共同依赖本配置模块。
STATIC_ANALYSIS_DIR = os.path.join(SOURCE_REPO_DIR, "static-analysis")
DETEKT_CONFIG_PATH = os.path.join(STATIC_ANALYSIS_DIR, "detekt.yml")

PIPELINE_CONFIG_PATH = os.path.join(SOURCE_REPO_DIR, "config", "config.json")


def _non_empty_string(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} in config/config.json must be a non-empty string")
    return value


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

    return project_root, repos, agent_types


PROJECT_ROOT, REPOS, AGENT_TYPES = _load_pipeline_config()


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
