import json
import os
import shutil
import subprocess
import sys
import time

from ._result import AgentRunResult
from ._cli import executable_name
from review_decision import structured_review_decision


CURSOR_BASE_CMD = [
    executable_name("agent"), "-p", "--force", "--output-format", "stream-json", "--stream-partial-output",
]
_CLI_SEARCH_DIRS = [os.path.expanduser("~/.local/bin"), "/usr/local/bin", "/opt/homebrew/bin"]
KEEPALIVE_TIMEOUT_ERROR = "RetriableError: [internal] HTTP/2 keepalive ping timed out after 5000ms"
TLS_CONNECTION_DISCONNECTED_ERROR = "Error: [aborted] Client network socket disconnected before secure TLS connection was established"
WRITABLE_ITERABLE_CLOSED_ERROR = "RetriableError: WritableIterable is closed"
KEEPALIVE_RETRY_DELAY_SECONDS = 3
CURSOR_RETRIABLE_NETWORK_ATTEMPTS = 3


def _extended_path():
    parts = _CLI_SEARCH_DIRS + os.environ.get("PATH", "").split(os.pathsep)
    return os.pathsep.join(dict.fromkeys(part for part in parts if part))


def build_cursor_base_cmd():
    override = os.environ.get("CURSOR_AGENT_BIN")
    if override:
        binary = os.path.expanduser(override)
        if not (os.path.isfile(binary) and os.access(binary, os.X_OK)):
            raise FileNotFoundError(f"CURSOR_AGENT_BIN is not executable: {binary}")
    else:
        binary = shutil.which(executable_name("agent"), path=_extended_path())
        if not binary:
            raise FileNotFoundError(
                f"Cannot find '{executable_name('agent')}' CLI. Install it or set CURSOR_AGENT_BIN."
            )
    cmd = CURSOR_BASE_CMD.copy()
    cmd[0] = binary
    return cmd


def _subprocess_env():
    env = os.environ.copy()
    env["PATH"] = _extended_path()
    return env


def _preferred_result_text(stream_state, text_parts):
    candidates = [
        stream_state["result_text"],
        stream_state["last_assistant_text"],
        "".join(text_parts),
    ]
    for candidate in candidates:
        if candidate and structured_review_decision(candidate) is not None:
            return candidate
    return stream_state["result_text"] or stream_state["last_assistant_text"] or "".join(text_parts)


def _message_text(message):
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


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
    if event_type == "assistant":
        if "model_call_id" in data:
            return ""
        text = _message_text(data.get("message", {}))
        is_delta = "timestamp_ms" in data
        if is_delta:
            stream_state["saw_streaming_assistant"] = True
        elif stream_state.get("saw_streaming_assistant"):
            return ""
        if text:
            stream_state["last_assistant_text"] = text
    elif event_type == "result":
        text = data.get("result", "")
        if text:
            stream_state["result_text"] = text
    elif event_type == "thinking":
        sys.stdout.write("\r[Cursor thinking] ")
        sys.stdout.flush()
        return ""
    else:
        return ""

    if text:
        sys.stdout.write(text)
        sys.stdout.flush()
    return text


class CursorAgent:
    def run(self, work_dir, message, system_prompt=None, session_id=None, add_dirs=None):
        current_session_id = session_id
        for attempt in range(CURSOR_RETRIABLE_NETWORK_ATTEMPTS):
            result = self._run_once(work_dir, message, system_prompt, current_session_id, add_dirs)
            current_session_id = result.session_id or current_session_id
            if result.returncode == 0 or not self._is_retriable_network_error(result.error):
                return result
            if attempt == CURSOR_RETRIABLE_NETWORK_ATTEMPTS - 1:
                return result
            time.sleep(KEEPALIVE_RETRY_DELAY_SECONDS)
        return result

    @staticmethod
    def _is_retriable_network_error(error):
        return any(
            retry_error in (error or "")
            for retry_error in (
                KEEPALIVE_TIMEOUT_ERROR,
                TLS_CONNECTION_DISCONNECTED_ERROR,
                WRITABLE_ITERABLE_CLOSED_ERROR,
            )
        )

    def _run_once(self, work_dir, message, system_prompt, session_id, add_dirs):
        try:
            cmd = build_cursor_base_cmd()
        except FileNotFoundError as error:
            return AgentRunResult("", session_id, -1, str(error))

        if session_id:
            cmd.extend(["--resume", session_id])
            prompt = message
        else:
            prompt = message
            if add_dirs:
                directories = "\n".join(f"- {directory}" for directory in add_dirs)
                prompt = f"{prompt}\n\n[ADDITIONAL DIRECTORIES]\n{directories}\n[/ADDITIONAL DIRECTORIES]"
            if system_prompt:
                prompt = f"[SYSTEM PROMPT]\n{system_prompt}\n[/SYSTEM PROMPT]\n\n[USER PROMPT]\n{prompt}"
        cmd.append(prompt)

        try:
            process = subprocess.Popen(
                cmd, cwd=work_dir, env=_subprocess_env(), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", bufsize=1,
            )
            text_parts = []
            raw_output_parts = []
            stream_state = {
                "session_id": session_id,
                "saw_streaming_assistant": False,
                "result_text": None,
                "last_assistant_text": None,
            }
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
                f"Cursor exited with code {process.returncode}"
            )
            return AgentRunResult(
                _preferred_result_text(stream_state, text_parts), stream_state["session_id"],
                process.returncode, error,
            )
        except Exception as error:
            return AgentRunResult("", session_id, -1, str(error))
