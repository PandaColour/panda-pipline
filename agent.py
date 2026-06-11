import os
from abc import ABC, abstractmethod

from config import SYSTEM_PROMPT_DIR
from utils import run_claude_task, run_codex_task


class AgentInterface(ABC):
    """Abstract base defining the contract for AI coding agent backends."""

    @abstractmethod
    def run(self, work_dir, message, system_prompt=None, use_continue=False, add_dirs=None):
        """Execute the agent task and return the full response text."""
        pass


class ClaudeAgent(AgentInterface):
    """Wraps the Claude CLI as the agent backend."""

    def run(self, work_dir, message, system_prompt=None, use_continue=False, add_dirs=None):
        return run_claude_task(
            work_dir=work_dir,
            message=message,
            system_prompt=system_prompt,
            use_continue=use_continue,
            add_dirs=add_dirs
        )


class CodexAgent(AgentInterface):
    """Wraps the Codex CLI as the agent backend."""

    def run(self, work_dir, message, system_prompt=None, use_continue=False, add_dirs=None):
        return run_codex_task(
            work_dir=work_dir,
            message=message,
            system_prompt=system_prompt,
            use_continue=use_continue,
            add_dirs=add_dirs
        )


class Agent:
    """Multi-backend conversational agent. Delegates execution to a backend strategy
    (ClaudeAgent or CodexAgent) based on agent_type."""

    _STRATEGY_MAP = {
        "claude": ClaudeAgent,
        "codex": CodexAgent,
    }

    def __init__(self, name, system_prompt_file, work_dir, add_dirs=None, agent_type="claude"):
        self.name = name
        self.work_dir = work_dir
        self.add_dirs = add_dirs or []
        self.call_count = 0
        self.system_prompt = self._load_system_prompt(system_prompt_file)
        self.agent_type = agent_type
        self.agent_impl = self._create_strategy(agent_type)

    @classmethod
    def register_backend(cls, name, strategy_cls):
        """Register a new agent backend type."""
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
        print(f"🤖 Agent [{self.name}] — 第 {self.call_count} 次调用 (backend: {self.agent_type})")
        print(f"{'=' * 60}")

        return self.agent_impl.run(
            work_dir=self.work_dir,
            message=message,
            system_prompt=self.system_prompt,
            use_continue=use_continue,
            add_dirs=self.add_dirs
        )
