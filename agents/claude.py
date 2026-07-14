import json
import subprocess
import sys

from ._result import AgentRunResult
from ._cli import executable_name


CLAUDE_BASE_CMD = [
    executable_name("claude"),
    "--permission-mode", "bypassPermissions",
    "--output-format=stream-json",
    "--verbose",
]


def _extract_text(data, seen=None):
    if seen is None:
        seen = set()
    if id(data) in seen:
        return ""
    seen.add(id(data))

    if isinstance(data, dict):
        parts = []
        text = data.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text)
        for key in ("delta", "content", "input", "message"):
            value = data.get(key)
            if isinstance(value, (dict, list)):
                parts.append(_extract_text(value, seen))
        result = data.get("result")
        if isinstance(result, str) and result.strip():
            parts.append(result)
        return "".join(parts)
    if isinstance(data, list):
        return "".join(_extract_text(item, seen) for item in data)
    return data if isinstance(data, str) and data.strip() else ""


def parse_stream(json_line, stream_state):
    try:
        data = json.loads(json_line.strip())
    except json.JSONDecodeError:
        if json_line.strip():
            sys.stdout.write(json_line)
            sys.stdout.flush()
        return ""

    session_id = data.get("session_id")
    if isinstance(session_id, str) and session_id:
        stream_state["session_id"] = session_id
    event_type = data.get("type", "")

    if event_type == "thinking":
        sys.stdout.write("\r[Claude thinking] ")
        sys.stdout.flush()
        return ""
    if event_type == "stream_event":
        return parse_stream(json.dumps(data.get("event") or data.get("content_block") or {}), stream_state)
    if event_type == "content_block_delta":
        delta = data.get("delta", {})
        text = delta.get("text") or delta.get("partial_json") or _extract_text(delta)
    elif event_type == "content_block_start":
        block = data.get("content_block", {})
        if block.get("type") == "tool_use":
            sys.stdout.write(f"\n[Claude tool] {block.get('name', 'unknown')}")
            sys.stdout.flush()
        text = _extract_text(block)
    elif event_type == "assistant":
        text = _extract_text(data)
    elif event_type == "result":
        text = _extract_text(data)
    elif event_type == "system":
        text = ""
    elif event_type in {"content_block_stop", "message_start", "message_delta", "message_stop", "user", "ping"}:
        text = ""
    else:
        text = _extract_text(data)

    if text:
        sys.stdout.write(text)
        sys.stdout.flush()
    return text


class ClaudeAgent:
    def run(self, work_dir, message, system_prompt=None, session_id=None, add_dirs=None):
        cmd = CLAUDE_BASE_CMD.copy()
        if session_id:
            cmd.extend(["--resume", session_id])
        if system_prompt:
            cmd.extend(["--append-system-prompt", system_prompt])
        for directory in add_dirs or []:
            cmd.extend(["--add-dir", directory])
        cmd.append("-p")

        try:
            process = subprocess.Popen(
                cmd, cwd=work_dir, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", bufsize=1,
            )
            process.stdin.write(message)
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
            error = None if process.returncode == 0 else f"Claude exited with code {process.returncode}"
            return AgentRunResult("".join(text_parts), stream_state["session_id"], process.returncode, error)
        except Exception as error:
            return AgentRunResult("", session_id, -1, str(error))
