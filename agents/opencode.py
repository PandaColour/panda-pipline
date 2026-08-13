import json
import os
import shutil
import subprocess
import sys
import time

from ._result import AgentRunResult
from ._cli import executable_name


OPENCODE_BASE_CMD = [
    executable_name("opencode"), "run",
    "--format", "json",
    "--auto",
]
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5


def build_opencode_base_cmd():
    override = os.environ.get("OPENCODE_AGENT_BIN")
    if override:
        binary = os.path.expanduser(override)
        if not (os.path.isfile(binary) and os.access(binary, os.X_OK)):
            raise FileNotFoundError(f"OPENCODE_AGENT_BIN is not executable: {binary}")
    else:
        binary = shutil.which(executable_name("opencode"))
        if not binary:
            raise FileNotFoundError(
                f"Cannot find '{executable_name('opencode')}' CLI. Install it or set OPENCODE_AGENT_BIN."
            )
    cmd = OPENCODE_BASE_CMD.copy()
    cmd[0] = binary
    model = os.environ.get("OPENCODE_MODEL")
    if model:
        cmd.extend(["--model", model])
    return cmd


def parse_stream(json_line, stream_state):
    try:
        data = json.loads(json_line.strip())
    except json.JSONDecodeError:
        if json_line.strip():
            sys.stdout.write(json_line)
            sys.stdout.flush()
        return ""

    session_id = data.get("sessionID")
    if isinstance(session_id, str) and session_id:
        stream_state["session_id"] = session_id

    event_type = data.get("type", "")
    part = data.get("part") or {}
    if event_type == "text":
        text = part.get("text") or ""
        if text:
            message_id = part.get("messageID")
            if message_id and message_id != stream_state["last_message_id"]:
                stream_state["last_message_id"] = message_id
                stream_state["last_message_text"] = ""
            stream_state["last_message_text"] += text
    elif event_type == "reasoning":
        sys.stdout.write("\r[opencode thinking] ")
        sys.stdout.flush()
        text = ""
    elif event_type == "tool_use":
        sys.stdout.write(f"\n[opencode tool] {part.get('tool', 'unknown')}")
        sys.stdout.flush()
        text = ""
    elif event_type == "error":
        error = data.get("error") or {}
        message = error.get("data", {}).get("message") if isinstance(error.get("data"), dict) else error.get("message")
        if message:
            sys.stdout.write(f"\n[opencode error] {message}")
            sys.stdout.flush()
        text = ""
    else:
        text = ""

    if text:
        sys.stdout.write(text)
        sys.stdout.flush()
    return text


class OpencodeAgent:
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
        try:
            cmd = build_opencode_base_cmd()
        except FileNotFoundError as error:
            return AgentRunResult("", session_id, -1, str(error))

        if session_id:
            cmd.extend(["--session", session_id])
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
                cmd, cwd=work_dir, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", bufsize=1,
            )
            text_parts = []
            raw_output_parts = []
            stream_state = {
                "session_id": session_id,
                "last_message_id": None,
                "last_message_text": "",
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
                f"Opencode exited with code {process.returncode}"
            )
            return AgentRunResult(
                stream_state["last_message_text"] or "".join(text_parts),
                stream_state["session_id"],
                process.returncode,
                error,
            )
        except Exception as error:
            return AgentRunResult("", session_id, -1, str(error))
