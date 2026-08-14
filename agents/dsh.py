import json
import subprocess
import sys
import time

from ._result import AgentRunResult
from ._cli import executable_name


# dsh-cmd-starter (https://github.com/PandaColour/dsh-cmd-starter) 提供
# Claude-Code 风格的无头调度参数。`--output-format json` 让每次运行在 stdout
# 输出单行 JSON，含 sessionId，供这里解析并复用为下一次 `--resume`。
DSH_BASE_CMD = [
    executable_name("dsh"),
    "--profile", "headless",
    "--output-format", "json",
]
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5


def _find_result_line(stdout):
    """在完整输出里找含 sessionId 的那一行 JSON，返回解析后的 dict 或 None。"""
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "sessionId" in data:
            return data
    return None


class DshAgent:
    def run(self, work_dir, message, system_prompt=None, session_id=None, add_dirs=None):
        result = self._run_once(work_dir, message, system_prompt, session_id, add_dirs)
        for _attempt in range(MAX_RETRIES):
            if result.returncode == 0:
                return result
            time.sleep(RETRY_DELAY_SECONDS)
            result = self._run_once(
                work_dir,
                message,
                system_prompt,
                result.session_id or session_id,
                add_dirs,
            )
        return result

    def _run_once(self, work_dir, message, system_prompt=None, session_id=None, add_dirs=None):
        cmd = DSH_BASE_CMD.copy()
        if session_id:
            # dsh-cmd-starter 的 --resume 同时接受 session id 和 --name 别名。
            cmd.extend(["--resume", session_id])
        if system_prompt:
            # 对应 Claude 的 --append-system-prompt：本次运行临时追加系统提示词，
            # 不落盘、不进会话历史，所以每次运行都要重新传。
            cmd.extend(["--append-prompt", system_prompt])

        prompt = message
        if add_dirs:
            # dsh 无 --add-dir；把额外目录显式告知模型（模型可读，写仍受 workspace 沙箱限制）。
            directories = "\n".join(f"- {directory}" for directory in add_dirs)
            prompt = f"{prompt}\n\n[ADDITIONAL DIRECTORIES]\n{directories}\n[/ADDITIONAL DIRECTORIES]"
        cmd.append(prompt)

        try:
            process = subprocess.Popen(
                cmd, cwd=work_dir, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", bufsize=1,
            )
            stdout, _ = process.communicate()
            data = _find_result_line(stdout)
            text = data.get("finalResponse") or "" if data else ""
            resolved_session_id = (data.get("sessionId") if data else None) or session_id
            error = None if process.returncode == 0 else stdout.strip() or (
                f"dsh exited with code {process.returncode}"
            )
            return AgentRunResult(text, resolved_session_id, process.returncode, error)
        except Exception as error:
            return AgentRunResult("", session_id, -1, str(error))
