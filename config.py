import os

# Output workspace root
PROJECT_ROOT = r"D:\company\pipline"

# Stage directories
DIR_REQUIREMENTS = os.path.join(PROJECT_ROOT, "1_requirements")
DIR_DEVELOPMENT = os.path.join(PROJECT_ROOT, "2_development")
DIR_TESTING = os.path.join(PROJECT_ROOT, "3_testing")

# Reviewer agent session directories (isolated to avoid --continue collision)
DIR_REQUIREMENTS_REVIEW = os.path.join(DIR_REQUIREMENTS, "_review")
DIR_DEVELOPMENT_REVIEW = os.path.join(DIR_DEVELOPMENT, "_review")

# Source repo root (where this config lives)
SOURCE_REPO_DIR = os.path.dirname(os.path.abspath(__file__))

# Memory store directory (relative to source repo)
MEMORY_DIR = os.path.join(SOURCE_REPO_DIR, "memory")

# System prompt directory (relative to this source repo)
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
