import json
import subprocess
import sys

from ._result import AgentRunResult
from ._cli import executable_name


CODEX_BASE_CMD = [
    executable_name("codex"), "exec",
    "-c", "shell_environment_policy.inherit=all",
    "--sandbox", "danger-full-access",
    "--json",
]


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
        if session_id:
            cmd = [executable_name("codex"), "exec", "resume", "--json", session_id]
            prompt = message
            if add_dirs:
                directories = "\n".join(f"- {directory}" for directory in add_dirs)
                prompt = f"{prompt}\n\n[ADDITIONAL DIRECTORIES]\n{directories}\n[/ADDITIONAL DIRECTORIES]"
        else:
            cmd = CODEX_BASE_CMD.copy()
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
            stream_state = {"session_id": session_id}
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    text = parse_stream(line, stream_state)
                    if text:
                        text_parts.append(text)
            process.wait()
            error = None if process.returncode == 0 else f"Codex exited with code {process.returncode}"
            return AgentRunResult("".join(text_parts), stream_state["session_id"], process.returncode, error)
        except Exception as error:
            return AgentRunResult("", session_id, -1, str(error))
