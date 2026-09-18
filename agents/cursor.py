import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

from ._result import AgentRunResult
from ._retry import run_with_retry
from ._cli import executable_name
from ._prompt_snapshot import check_command_length, prompt_file
from review_decision import structured_final_answer_decision, REVIEW_STATUSES


CURSOR_BASE_CMD = [
    executable_name("agent"), "-p", "--force", "--output-format", "stream-json", "--stream-partial-output",
]
_CLI_SEARCH_DIRS = [os.path.expanduser("~/.local/bin"), "/usr/local/bin", "/opt/homebrew/bin"]
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5


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
        stream_state.get("assistant_snapshot"),
        stream_state["last_assistant_text"],
        "".join(text_parts),
    ]
    for candidate in candidates:
        if candidate and structured_final_answer_decision(candidate, REVIEW_STATUSES | {'completed'}) is not None:
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
        text = _message_text(data.get("message", {}))
        if "model_call_id" in data:
            stream_state["assistant_snapshot"] = text
            return ""
        is_delta = "timestamp_ms" in data
        if is_delta:
            stream_state["saw_streaming_assistant"] = True
        elif stream_state.get("saw_streaming_assistant"):
            stream_state["assistant_snapshot"] = text
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
    # Result is a separate candidate, not another assistant delta. Appending
    # it would duplicate a final receipt or add trailing prose to valid JSON.
    return text if event_type == "assistant" else ""


class _CursorSessionModeError(RuntimeError):
    """The store cannot safely be checked or updated; use a fresh conversation."""


def _ensure_agent_mode(work_dir, session_id):
    """Reset persisted Ask/Plan mode before resuming a pipeline conversation.

    Cursor 2026.09.10 has no --mode agent; omitting --mode keeps the stored
    mode. Its meta['0'] is hex-encoded JSON. Only change mode, preserving
    conversation blobs and permission settings.
    """
    if not session_id:
        return None
    if not isinstance(session_id, str) or any(c in session_id for c in '/\\:') or session_id in {'.', '..'}:
        raise _CursorSessionModeError('会话 ID 无法用于本地模式检查')

    config = os.environ.get('CURSOR_CONFIG_DIR', '')
    xdg = os.environ.get('XDG_CONFIG_HOME', '')
    if config.strip():
        root = Path(config)
    elif xdg.strip():
        root = Path(xdg) / 'cursor'
    else:
        root = Path.home() / '.cursor'
    # Match Node path.resolve: lexical absolute path, without resolving symlinks.
    work = os.path.abspath(work_dir)
    if not root.is_absolute():
        root = Path(work) / root
    project = hashlib.md5(work.encode('utf-8')).hexdigest()
    path = root / 'chats' / project / session_id / 'store.db'

    try:
        if not path.is_file():
            # Let Cursor's existing invalid-session handling deal with absence.
            return None
        with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=2)) as db:
            row = db.execute('SELECT value FROM meta WHERE key = ?', ('0',)).fetchone()
            if row is None:
                raise _CursorSessionModeError('会话模式元数据缺失')
            raw = row[0]
            metadata = json.loads(bytes.fromhex(raw).decode('utf-8'))
            if not isinstance(metadata, dict) or metadata.get('agentId') != session_id:
                raise _CursorSessionModeError('会话模式元数据与会话 ID 不一致')
            mode = metadata.get('mode')
            if mode in ('default', 'agent', 'code', 'debug'):
                return None
            if mode not in ('search', 'ask', 'chat', 'plan', 'architect'):
                raise _CursorSessionModeError('无法识别会话模式')
            metadata['mode'] = 'default'
            encoded = json.dumps(metadata, ensure_ascii=False, separators=(',', ':')).encode('utf-8').hex()
            with db:
                changed = db.execute('UPDATE meta SET value = ? WHERE key = ? AND value = ?',
                                     (encoded, '0', raw))
                if changed.rowcount != 1:
                    raise _CursorSessionModeError('会话元数据已被其他进程更新')
            return mode
    except (OSError, sqlite3.Error, ValueError, TypeError) as error:
        # Metadata may contain encryption keys; never print its contents/errors.
        raise _CursorSessionModeError('无法安全读取或调整本地会话模式') from error


class CursorAgent:
    def run(self, work_dir, message, system_prompt=None, session_id=None, add_dirs=None):
        return run_with_retry(
            lambda current: self._run_once(work_dir, message, system_prompt, current, add_dirs),
            session_id, retries=getattr(self, "max_retries", MAX_RETRIES), delay=RETRY_DELAY_SECONDS, sleep=time.sleep,
            invalidate=getattr(self, "session_invalidation_callback", None),
        )

    def _run_once(self, work_dir, message, system_prompt, session_id, add_dirs):
        try:
            cmd = build_cursor_base_cmd()
        except FileNotFoundError as error:
            return AgentRunResult("", session_id, -1, str(error))

        try:
            try:
                previous_mode = _ensure_agent_mode(work_dir, session_id)
            except _CursorSessionModeError as error:
                # Persist detachment before starting, so a later CLI failure
                # cannot resurrect the same incompatible conversation.
                invalidate = getattr(self, 'session_invalidation_callback', None)
                if invalidate is not None:
                    invalidate()
                session_id = None
                print(f'⚠️ Cursor {error}；本次改用新的 Agent 会话。')
            else:
                if previous_mode:
                    print(f'ℹ️ Cursor 会话模式 {previous_mode} → Agent，保留原会话继续执行。')
            prompt = message
            if session_id:
                cmd.extend(["--resume", session_id])
            elif add_dirs:
                directories = "\n".join(f"- {directory}" for directory in add_dirs)
                prompt = f"[ADDITIONAL DIRECTORIES]\n{directories}\n[/ADDITIONAL DIRECTORIES]\n\n{prompt}"
            if system_prompt:
                role_path = prompt_file(system_prompt)
                # Catch missing/unreadable snapshots before starting a model turn.
                # Actual model-side reading is requested below, not assumed here.
                with open(role_path, 'r', encoding='utf-8') as role_file:
                    role_file.read(1)
                reference = json.dumps(role_path, ensure_ascii=False)
                if session_id:
                    instruction = (
                        f'当前角色规则文件（绝对路径）：{reference}。继续遵循其中规则；'
                        '需要时重新读取。若尚未完整读取或上下文已丢失，先完整读取再执行任务。'
                    )
                else:
                    instruction = (
                        f'先完整读取角色规则文件（绝对路径）：{reference}。'
                        '读取完成后，按其中的规则执行下方任务。'
                    )
                instruction += '读取失败时报告具体原因，不得跳过角色规则继续执行。'
                prompt = f"[SYSTEM PROMPT]\n{instruction}\n[/SYSTEM PROMPT]\n\n[USER PROMPT]\n{prompt}"
            cmd.append(prompt)
            check_command_length(cmd)

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
