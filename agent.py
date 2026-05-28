import os

from config import SYSTEM_PROMPT_DIR
from utils import run_claude_task


class Agent:
    """Wraps the claude CLI as a conversational agent with --continue tracking."""

    def __init__(self, name, system_prompt_file, work_dir, add_dirs=None):
        self.name = name
        self.work_dir = work_dir
        self.add_dirs = add_dirs or []
        self.call_count = 0
        self.system_prompt = self._load_system_prompt(system_prompt_file)

    def _load_system_prompt(self, filename):
        filepath = os.path.join(SYSTEM_PROMPT_DIR, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            print(f"⚠️  Warning: system prompt file not found: {filepath}")
            return ""

    def send_message(self, message):
        """Send a message to this agent. First call is fresh (no --continue),
        subsequent calls include --continue to maintain conversation context."""
        use_continue = self.call_count > 0
        self.call_count += 1

        print(f"\n{'=' * 60}")
        print(f"🤖 Agent [{self.name}] — 第 {self.call_count} 次调用")
        print(f"{'=' * 60}")

        return run_claude_task(
            work_dir=self.work_dir,
            message=message,
            system_prompt=self.system_prompt,
            use_continue=use_continue,
            add_dirs=self.add_dirs
        )
