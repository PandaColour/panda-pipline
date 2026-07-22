import json
import subprocess
import sys
import time

from ._result import AgentRunResult
from ._cli import executable_name


CODEX_BASE_CMD = [
    executable_name("codex"), "exec",
    "-c", "shell_environment_policy.inherit=all",
    "-c", 'sandbox_mode="danger-full-access"',
    "--json",
]
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5


def _codex_exec_cmd(*subcommands):
    return [*CODEX_BASE_CMD[:2], *subcommands, *CODEX_BASE_CMD[2:]]


def _extract_text(data):
    if not isinstance(data, dict):
        return ""
    for key in ("text", "content", "delta"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            nested = _extract_text(value)
            if nested:
                return nested
    return ""


def parse_stream(json_line, stream_state):
    try:
        data = json.loads(json_line.strip())
    except json.JSONDecodeError:
        if json_line.strip():
            sys.stdout.write(json_line)
            sys.stdout.flush()
        return ""

    event_type = data.get("type", "")
    if event_type == "thread.started":
        thread_id = data.get("thread_id")
        if thread_id:
            stream_state["session_id"] = thread_id
        return ""
    if event_type in {"item.started", "item.completed"}:
        item = data.get("item", {})
        if item.get("type") == "agent_message":
            text = item.get("text", "")
            if event_type == "item.completed" and text:
                stream_state["final_text"] = text
        elif item.get("type") in {"reasoning", "thinking"}:
            sys.stdout.write("\r[Codex thinking] ")
            sys.stdout.flush()
            return ""
        else:
            text = item.get("text", "")
    elif event_type in {"agent_message", "agent_message_delta", "message", "text"}:
        text = _extract_text(data)
    elif event_type in {"thinking", "turn.started", "turn.completed", "done", "tool_call", "error"}:
        text = ""
    else:
        text = _extract_text(data)

    if text:
        sys.stdout.write(text)
        sys.stdout.flush()
    return text


class CodexAgent:
    def run(self, work_dir, message, system_prompt=None, session_id=None, add_dirs=None):
        current_session_id = session_id
        result = self._run_once(work_dir, message, system_prompt, current_session_id, add_dirs)
        for _attempt in range(MAX_RETRIES):
            current_session_id = result.session_id or current_session_id
            if result.returncode == 0:
                return result
            time.sleep(RETRY_DELAY_SECONDS)
            result = self._run_once(work_dir, message, system_prompt, current_session_id, add_dirs)
        return result

    def _run_once(self, work_dir, message, system_prompt=None, session_id=None, add_dirs=None):
        if session_id:
            cmd = _codex_exec_cmd("resume")
            cmd.append(session_id)
            prompt = message
            if add_dirs:
                directories = "\n".join(f"- {directory}" for directory in add_dirs)
                prompt = f"{prompt}\n\n[ADDITIONAL DIRECTORIES]\n{directories}\n[/ADDITIONAL DIRECTORIES]"
        else:
            cmd = _codex_exec_cmd()
            prompt = message
            if system_prompt:
                prompt = f"[SYSTEM PROMPT]\n{system_prompt}\n[/SYSTEM PROMPT]\n\n[USER PROMPT]\n{message}"
            for directory in add_dirs or []:
                cmd.extend(["--add-dir", directory])
        cmd.append("-")

        try:
            process = subprocess.Popen(
                cmd, cwd=work_dir, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", bufsize=1,
            )
            process.stdin.write(prompt)
            process.stdin.close()
            text_parts = []
            raw_output_parts = []
            stream_state = {"session_id": session_id, "final_text": None}
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    raw_output_parts.append(line)
                    text = parse_stream(line, stream_state)
                    if text:
                        text_parts.append(text)
            process.wait()
            error = None if process.returncode == 0 else "".join(raw_output_parts).strip() or (
                f"Codex exited with code {process.returncode}"
            )
            return AgentRunResult(
                stream_state["final_text"] or "".join(text_parts),
                stream_state["session_id"],
                process.returncode,
                error,
            )
        except Exception as error:
            return AgentRunResult("", session_id, -1, str(error))
