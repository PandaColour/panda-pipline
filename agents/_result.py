from dataclasses import dataclass


@dataclass(frozen=True)
class AgentRunResult:
    text: str
    session_id: str | None
    returncode: int
    error: str | None = None
