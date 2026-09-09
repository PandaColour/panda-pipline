import os

from config import SYSTEM_PROMPT_DIR

from .claude import ClaudeAgent
from .codex import CodexAgent
from .cursor import CursorAgent
from .dsh import DshAgent
from .opencode import OpencodeAgent
from task_protocol import TaskMessage, validate_receipt, save_call_log


class Agent:
    """Public conversational agent facade for Claude, Codex, Cursor, and Opencode."""

    _STRATEGY_MAP = {
        "claude": ClaudeAgent,
        "codex": CodexAgent,
        "cursor": CursorAgent,
        "dsh": DshAgent,
        "opencode": OpencodeAgent,
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
        status_provider=None,
        call_scope_provider=None,
    ):
        self.name = name
        self.work_dir = work_dir
        self.add_dirs = add_dirs or []
        self.call_count = 0
        self.call_scope_counts = {}
        self.session_id = session_id
        self.last_run_result = None
        self.prompt_dir = prompt_dir or SYSTEM_PROMPT_DIR
        self.system_prompt = self._load_system_prompt(system_prompt_file)
        self.agent_type = agent_type
        self.agent_impl = self._create_strategy(agent_type)
        self.session_update_callback = session_update_callback
        self.agent_impl.session_invalidation_callback = self._invalidate_session
        self.status_provider = status_provider
        self.call_scope_provider = call_scope_provider

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

    @property
    def current_status(self):
        if not callable(self.status_provider):
            return None
        try:
            status = self.status_provider()
        except (KeyError, OSError, ValueError):
            return None
        return status.strip() if isinstance(status, str) and status.strip() else None

    @property
    def current_call_scope(self):
        if not callable(self.call_scope_provider):
            return None
        try:
            scope = self.call_scope_provider()
        except (KeyError, OSError, ValueError):
            return None
        return scope.strip() if isinstance(scope, str) and scope.strip() else None

    def _invalidate_session(self):
        """Detach the failed conversation without deleting its diagnostic history."""
        if self.session_update_callback:
            self.session_update_callback(None)
        self.session_id = None
        print(f"⚠️ {self.display_name} 会话失效，已清除恢复引用；后续尝试将新建会话。")

    def send_message(self, message):
        """Send one turn and resume this instance's explicit provider session."""
        self.call_count += 1
        call_scope = self.current_call_scope
        if call_scope:
            self.call_scope_counts[call_scope] = self.call_scope_counts.get(call_scope, 0) + 1
        status = self.current_status
        status_text = f" — 当前状态: {status}" if status else ""
        call_text = (
            f" — 需求 {call_scope} 第 {self.call_scope_counts[call_scope]} 次调用"
            f"（批次累计第 {self.call_count} 次）"
            if call_scope else
            f" — 第 {self.call_count} 次调用"
        )
        print(f"\n{'=' * 60}")
        print(f"🤖 {self.display_name}{status_text}{call_text}")
        print(f"{'=' * 60}")

        # Stage scheduling owns all retries so every physical review invocation
        # consumes its persisted budget, including malformed receipt corrections.
        if isinstance(message, TaskMessage):
            self.agent_impl.max_retries = 0
        result = self.agent_impl.run(
            work_dir=self.work_dir,
            message=message,
            system_prompt=self.system_prompt,
            session_id=self.session_id,
            add_dirs=self.add_dirs,
        )
        self.last_run_result = result
        if isinstance(message, TaskMessage):
            self.last_log_path = save_call_log(self.work_dir, self.name, result.error or result.text or '')
        previous_session_id = self.session_id
        if result.session_id:
            self.session_id = result.session_id
        if self.session_id and self.session_id != previous_session_id and self.session_update_callback:
            self.session_update_callback(self.session_id)
        if result.returncode != 0:
            detail = result.error or f"process exited with code {result.returncode}"
            raise RuntimeError(f"{self.display_name} execution failed: {detail}")
        if isinstance(message, TaskMessage):
            return validate_receipt(result.text, message, self.work_dir)
        return result.text
