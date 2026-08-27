import json
import os
import subprocess
import sys
import time

from ._result import AgentRunResult
from ._cli import executable_name


# dsh-cmd-starter (https://github.com/PandaColour/dsh-cmd-starter) 提供
# Claude-Code 风格的无头调度参数。`--output-format json` 让每次运行在 stdout
# 输出单行 JSON，含 sessionId，供这里解析并复用为下一次 `--resume`。
# 默认 MCP（飞书项目 Meegle）已装在 dsh 的 headless profile 里，无需这里处理。
DSH_BASE_CMD = [
    executable_name("dsh"),
    "--profile", "headless",
]
# 默认模型：DeepSeek 多模态实验模型（需 dsh 版本支持 inputModalities 字段）。
DEFAULT_PROVIDER = "deepseek-official"
DEFAULT_MODEL = "deepseek-v4-flash-vision-exp"
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5


def _subprocess_env():
    """Build the DSH child environment with its launch-only permission setting."""
    env = os.environ.copy()
    env["DSH_PERMISSION_MODE"] = "danger-full-access"
    return env


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
    def run(
        self,
        work_dir,
        message,
        system_prompt=None,
        session_id=None,
        add_dirs=None,
        patch_files=None,
        provider=None,
        model=None,
    ):
        result = self._run_once(
            work_dir, message, system_prompt, session_id, add_dirs, patch_files, provider, model,
        )
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
                patch_files,
                provider,
                model,
            )
        return result

    def _run_once(
        self, work_dir, message, system_prompt=None, session_id=None, add_dirs=None,
        patch_files=None, provider=None, model=None,
    ):
        cmd = DSH_BASE_CMD.copy()

        # launcher 参数：--patch（必须在 app 参数之前）。额外 patch 由调用方传入。
        for patch_file in patch_files or []:
            cmd.extend(["--patch", patch_file])

        # app 参数（从这里起交给 dsh-cmd-starter 解析）。
        cmd.extend(["--output-format", "json"])
        # 模型切换：默认 deepseek-v4-flash-vision-exp（多模态），可覆盖。
        cmd.extend(["--provider", provider or DEFAULT_PROVIDER])
        cmd.extend(["--model", model or DEFAULT_MODEL])
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
                env=_subprocess_env(),
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
