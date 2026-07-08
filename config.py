import os

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
    "--sandbox", "workspace-write",
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
