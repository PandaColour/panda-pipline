import os
import shutil

# Source repo root (where this config lives)
SOURCE_REPO_DIR = os.path.dirname(os.path.abspath(__file__))
SYSTEM_PROMPT_DIR = os.path.join(SOURCE_REPO_DIR, "system-prompt")

# Claude CLI base command (flags added dynamically by Agent)
CLAUDE_BASE_CMD = [
    "claude",
    "--permission-mode", "bypassPermissions",
    "--output-format=stream-json",
    "--verbose"
]

# Codex CLI base command (flags added dynamically by runner)
CODEX_BASE_CMD = [
    "codex", "exec",
    "-c", "shell_environment_policy.inherit=all",
    "--sandbox", "danger-full-access",
    "--json"
]

# Cursor Agent CLI base command (flags added dynamically by runner)
CURSOR_BASE_CMD = [
    "agent",
    "-p",
    "--force",
    "--output-format", "stream-json",
    "--stream-partial-output"
]

_DEFAULT_CLI_SEARCH_DIRS = [
    os.path.expanduser("~/.local/bin"),
    "/usr/local/bin",
    "/opt/homebrew/bin",
]


def _extended_path():
    path_parts = _DEFAULT_CLI_SEARCH_DIRS + os.environ.get("PATH", "").split(os.pathsep)
    return os.pathsep.join(dict.fromkeys(p for p in path_parts if p))


def resolve_cli_binary(name, *, env_var=None):
    """Resolve a CLI binary to an absolute path, including common install dirs."""
    if env_var:
        override = os.environ.get(env_var)
        if override:
            override = os.path.expanduser(override)
            if os.path.isfile(override) and os.access(override, os.X_OK):
                return override
            raise FileNotFoundError(
                f"{env_var} is set to '{override}', but the file is missing or not executable."
            )

    found = shutil.which(name, path=_extended_path())
    if found:
        return found

    raise FileNotFoundError(
        f"Cannot find '{name}' CLI. Install it or set {env_var or 'PATH'} "
        f"to include its directory (e.g. ~/.local/bin)."
    )


def build_cursor_base_cmd():
    """Return Cursor Agent CLI command with a resolved binary path."""
    cmd = CURSOR_BASE_CMD.copy()
    cmd[0] = resolve_cli_binary("agent", env_var="CURSOR_AGENT_BIN")
    return cmd


def subprocess_env():
    """Environment for child CLI processes with common install dirs on PATH."""
    env = os.environ.copy()
    env["PATH"] = _extended_path()
    return env
