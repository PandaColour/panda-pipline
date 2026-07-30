import os

from config import SYSTEM_PROMPT_DIR

from .claude import ClaudeAgent
from .codex import CodexAgent
from .cursor import CursorAgent


class Agent:
    """Public conversational agent facade for Claude, Codex, and Cursor."""

    _STRATEGY_MAP = {
        "claude": ClaudeAgent,
        "codex": CodexAgent,
        "cursor": CursorAgent,
    }

    def __init__(
        self,
        name,
        system_prompt_file,
        work_dir,
        add_dirs=None,
        agent_type="claude",
        prompt_dir=None,
        session_id=None,
        session_update_callback=None,
    ):
        self.name = name
        self.work_dir = work_dir
        self.add_dirs = add_dirs or []
        self.call_count = 0
        self.session_id = session_id
        self.last_run_result = None
        self.prompt_dir = prompt_dir or SYSTEM_PROMPT_DIR
        self.system_prompt = self._load_system_prompt(system_prompt_file)
        self.agent_type = agent_type
        self.agent_impl = self._create_strategy(agent_type)
        self.session_update_callback = session_update_callback

    @classmethod
    def register_backend(cls, name, strategy_cls):
        """Register a backend implementation for an additional provider."""
        cls._STRATEGY_MAP[name] = strategy_cls

    def _create_strategy(self, agent_type):
        strategy_cls = self._STRATEGY_MAP.get(agent_type)
        if strategy_cls is None:
            raise ValueError(
                f"Unknown agent_type: '{agent_type}'. "
                f"Available types: {list(self._STRATEGY_MAP.keys())}"
            )
        return strategy_cls()

    def _load_system_prompt(self, filename):
        filepath = os.path.join(self.prompt_dir, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as prompt_file:
                return prompt_file.read()
        except FileNotFoundError:
            print(f"⚠️  Warning: system prompt file not found: {filepath}")
            return ""

    @property
    def display_name(self):
        return f"{self.name}agent({self.agent_type})"

    def send_message(self, message):
        """Send one turn and resume this instance's explicit provider session."""
        self.call_count += 1
        print(f"\n{'=' * 60}")
        print(f"🤖 {self.display_name} — 第 {self.call_count} 次调用")
        print(f"{'=' * 60}")

        result = self.agent_impl.run(
            work_dir=self.work_dir,
            message=message,
            system_prompt=self.system_prompt,
            session_id=self.session_id,
            add_dirs=self.add_dirs,
        )
        self.last_run_result = result
        previous_session_id = self.session_id
        if result.session_id:
            self.session_id = result.session_id
        if self.session_id and self.session_id != previous_session_id and self.session_update_callback:
            self.session_update_callback(self.session_id)
        if result.returncode != 0:
            detail = result.error or f"process exited with code {result.returncode}"
            raise RuntimeError(f"{self.display_name} execution failed: {detail}")
        return result.text
