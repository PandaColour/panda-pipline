import os
import sys
import json
import subprocess

from config import (
    CLAUDE_BASE_CMD,
    CODEX_BASE_CMD,
    build_cursor_base_cmd,
    subprocess_env,
)


def _extract_text_deep(data, seen=None):
    """Recursively find all text content in a nested dict/list structure."""
    if seen is None:
        seen = set()
    obj_id = id(data)
    if obj_id in seen:
        return ""
    seen.add(obj_id)

    text_parts = []

    if isinstance(data, dict):
        # Direct text fields
        if "text" in data and isinstance(data["text"], str):
            t = data["text"]
            # Skip empty or pure-whitespace standalone fragments
            if t.strip():
                text_parts.append(t)
        # Delta that carries text
        delta = data.get("delta")
        if isinstance(delta, dict):
            text_parts.append(_extract_text_deep(delta, seen))
        # content list in message
        content = data.get("content")
        if isinstance(content, (list, dict)):
            text_parts.append(_extract_text_deep(content, seen))
        # tool input (dict) -> serialize brief
        tool_input = data.get("input")
        if isinstance(tool_input, dict):
            text_parts.append(_extract_text_deep(tool_input, seen))
        # message in assistant/user events
        message = data.get("message")
        if isinstance(message, dict):
            text_parts.append(_extract_text_deep(message, seen))
        # result field
        result = data.get("result")
        if isinstance(result, str) and result.strip():
            text_parts.append(result)

    elif isinstance(data, list):
        for item in data:
            text_parts.append(_extract_text_deep(item, seen))

    elif isinstance(data, str) and data.strip():
        text_parts.append(data)

    return "".join(text_parts)


def parse_and_print_stream(json_line):
    """Decode structured JSON from Claude stream and print as much content as possible."""
    try:
        data = json.loads(json_line.strip())
        event_type = data.get("type", "")

        # ---- thinking ----
        if event_type == "thinking":
            sys.stdout.write("\r🧠 [Claude 正在深度思考中...] ")
            sys.stdout.flush()
            return ""

        # ---- stream_event wraps inner events ----
        if event_type == "stream_event":
            inner = data.get("event") or data.get("content_block") or {}
            return parse_and_print_stream(json.dumps(inner))

        # ---- content_block_delta: the main streaming text source ----
        if event_type == "content_block_delta":
            delta = data.get("delta", {})
            delta_type = delta.get("type", "")
            if delta_type == "text_delta":
                text = delta.get("text", "")
                if text:
                    sys.stdout.write(text)
                    sys.stdout.flush()
                    return text
            elif delta_type == "input_json_delta":
                partial = delta.get("partial_json", "")
                if partial:
                    # tool arg streaming — print inline for visibility
                    sys.stdout.write(partial)
                    sys.stdout.flush()
                    return partial
            # Generic fallback for any delta
            text = _extract_text_deep(delta)
            if text:
                sys.stdout.write(text)
                sys.stdout.flush()
                return text
            return ""

        # ---- content_block_start: new content block begins ----
        if event_type == "content_block_start":
            block = data.get("content_block", {})
            block_type = block.get("type", "")
            if block_type == "tool_use":
                tool_name = block.get("name", "unknown")
                sys.stdout.write(f"\n🛠️  [工具调用] {tool_name}")
                sys.stdout.flush()
            elif block_type == "text":
                pass  # text will arrive via content_block_delta
            text = _extract_text_deep(block)
            if text:
                sys.stdout.write(text)
                sys.stdout.flush()
                return text
            return ""

        # ---- content_block_stop ----
        if event_type == "content_block_stop":
            sys.stdout.write("\n")
            sys.stdout.flush()
            return ""

        # ---- message_start ----
        if event_type == "message_start":
            role = data.get("message", {}).get("role", "")
            if role:
                sys.stdout.write(f"\n--- [{role}] ---\n")
                sys.stdout.flush()
            return ""

        # ---- message_delta ----
        if event_type == "message_delta":
            stop_reason = data.get("delta", {}).get("stop_reason", "")
            usage = data.get("usage", {})
            if stop_reason:
                sys.stdout.write(f"\n[停止原因: {stop_reason}]")
                sys.stdout.flush()
            if usage:
                sys.stdout.write(f"\n[用量: {usage}]")
                sys.stdout.flush()
            return ""

        # ---- message_stop ----
        if event_type == "message_stop":
            sys.stdout.write("\n")
            sys.stdout.flush()
            return ""

        # ---- assistant (full message, non-streaming fallback) ----
        if event_type == "assistant":
            text = _extract_text_deep(data)
            if text:
                sys.stdout.write(f"\r{text}")
                sys.stdout.flush()
                return text
            return ""

        # ---- user event (tool results) ----
        if event_type == "user":
            text = _extract_text_deep(data)
            if text:
                sys.stdout.write(f"\n📥 [工具结果] {text[:200]}{'...' if len(text) > 200 else ''}")
                sys.stdout.flush()
            return ""

        # ---- ping ----
        if event_type == "ping":
            return ""

        # ---- system ----
        if event_type == "system":
            subtype = data.get("subtype", "")
            if subtype == "api_retry":
                sys.stdout.write(f"\n⚠️  [网络波动] 重试第 {data.get('attempt', '?')} 次...\n")
                sys.stdout.flush()
            else:
                # Print any system message we haven't explicitly handled
                text = _extract_text_deep(data)
                if text:
                    sys.stdout.write(f"\n[系统] {text}")
                    sys.stdout.flush()
            return ""

        # ---- result event (final) ----
        if event_type == "result":
            text = _extract_text_deep(data)
            if text:
                sys.stdout.write(f"\n{text}")
                sys.stdout.flush()
                return text
            return ""

        # ---- catch-all: try deep extraction for anything else ----
        text = _extract_text_deep(data)
        if text:
            sys.stdout.write(text)
            sys.stdout.flush()
            return text

    except json.JSONDecodeError:
        if json_line.strip():
            sys.stdout.write(json_line)
            sys.stdout.flush()
    return ""


def run_claude_task(work_dir, message, system_prompt=None, use_continue=False, add_dirs=None):
    """Execute Claude CLI task in work_dir with optional --continue, --append-system-prompt, and --add-dir."""
    cmd = CLAUDE_BASE_CMD.copy()

    if use_continue:
        cmd.append("--continue")

    if system_prompt:
        cmd.extend(["--append-system-prompt", system_prompt])

    if add_dirs:
        for d in add_dirs:
            cmd.extend(["--add-dir", d])

    cmd.extend(["-p", message])

    print(f"\n[任务发送] 工作目录: {work_dir}")
    print(f"[提示词]: {message[:100]}...")
    print(f"[参数]: use_continue={use_continue}, has_system_prompt={system_prompt is not None}")
    print("⏳ 正在初始化流式监听管道并等待首包响应...")

    try:
        process = subprocess.Popen(
            cmd,
            cwd=work_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            bufsize=1
        )

        full_response_text = []

        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                clean_text = parse_and_print_stream(line)
                if clean_text:
                    full_response_text.append(clean_text)

        process.wait()
        if process.returncode != 0:
            print(f"\n❌ Claude 执行异常退出，退出码: {process.returncode}")
        else:
            print(f"\n\n✨ Claude 任务段流式对接完毕。")

        return "".join(full_response_text)
    except Exception as e:
        print(f"💥 脚本运行时发生异常: {e}")
        return None


def parse_and_print_codex_stream(json_line):
    """Decode structured JSON from Codex --json output and print useful content."""
    try:
        data = json.loads(json_line.strip())
        event_type = data.get("type", "")

        if event_type == "thread.started":
            thread_id = data.get("thread_id", "")
            if thread_id:
                sys.stdout.write(f"\n🧵 [Codex 会话] {thread_id}\n")
                sys.stdout.flush()
            return ""

        if event_type == "turn.started":
            sys.stdout.write("\n--- [codex] ---\n")
            sys.stdout.flush()
            return ""

        if event_type == "turn.completed":
            usage = data.get("usage", {})
            if usage:
                sys.stdout.write(f"\n[用量: {usage}]")
                sys.stdout.flush()
            return ""

        if event_type in {"item.started", "item.completed"}:
            item = data.get("item", {})
            item_type = item.get("type", "")

            if item_type == "agent_message":
                text = item.get("text", "")
                if text:
                    sys.stdout.write(text)
                    sys.stdout.flush()
                    return text
                return ""

            if item_type == "command_execution":
                command = item.get("command", "")
                status = item.get("status", "")
                if event_type == "item.started":
                    sys.stdout.write(f"\n🛠️  [Codex 执行命令] {command}")
                else:
                    exit_code = item.get("exit_code")
                    output = item.get("aggregated_output", "")
                    sys.stdout.write(f"\n✅ [Codex 命令完成] exit_code={exit_code}, status={status}")
                    if output:
                        preview = output.strip()
                        if preview:
                            sys.stdout.write(f"\n{preview}\n")
                sys.stdout.flush()
                return ""

            if item_type in {"reasoning", "thinking"}:
                sys.stdout.write("\r🧠 [Codex 正在思考中...] ")
                sys.stdout.flush()
                return ""

            if item_type in {"tool_call", "function_call", "mcp_tool_call"}:
                tool_name = item.get("name") or item.get("tool_name") or "unknown"
                sys.stdout.write(f"\n🛠️  [Codex 工具调用] {tool_name}")
                sys.stdout.flush()
                return ""

            text = item.get("text", "")
            if isinstance(text, str) and text:
                sys.stdout.write(text)
                sys.stdout.flush()
                return text
            return ""

        if event_type in {"agent_message", "agent_message_delta", "message"}:
            text = data.get("text") or data.get("delta") or data.get("content") or ""
            if isinstance(text, dict):
                text = text.get("text") or text.get("content") or ""
            if text:
                sys.stdout.write(text)
                sys.stdout.flush()
                return text

        if event_type == "text":
            text = data.get("content", "")
            if text:
                sys.stdout.write(text)
                sys.stdout.flush()
                return text

        if event_type == "tool_call":
            tool_name = data.get("name", "unknown")
            sys.stdout.write(f"\n🛠️  [工具调用] {tool_name}")
            sys.stdout.flush()
            return ""

        if event_type == "thinking":
            sys.stdout.write("\r🧠 [Codex 正在深度思考中...] ")
            sys.stdout.flush()
            return ""

        if event_type == "done":
            sys.stdout.write("\n")
            sys.stdout.flush()
            return ""

        if event_type == "error":
            msg = data.get("message", "")
            sys.stdout.write(f"\n❌ [错误] {msg}")
            sys.stdout.flush()
            return ""

        # Generic fallback: extract any text from unrecognized structures
        text = _extract_text_deep(data)
        if text:
            sys.stdout.write(text)
            sys.stdout.flush()
            return text

    except json.JSONDecodeError:
        if json_line.strip():
            sys.stdout.write(json_line)
            sys.stdout.flush()
    return ""


def run_codex_task(work_dir, message, system_prompt=None, use_continue=False, add_dirs=None):
    """Execute Codex CLI task with optional resume (--continue equivalent)."""
    if system_prompt:
        prompt = f"[SYSTEM PROMPT]\n{system_prompt}\n[/SYSTEM PROMPT]\n\n[USER PROMPT]\n{message}"
    else:
        prompt = message

    if use_continue:
        cmd = ["codex", "exec", "resume", "--last"]
    else:
        cmd = CODEX_BASE_CMD.copy()

    if add_dirs:
        if use_continue:
            extra_dirs = "\n".join(f"- {d}" for d in add_dirs)
            prompt = f"{prompt}\n\n[ADDITIONAL DIRECTORIES]\n{extra_dirs}\n[/ADDITIONAL DIRECTORIES]"
        else:
            for d in add_dirs:
                cmd.extend(["--add-dir", d])

    cmd.append(prompt)

    print(f"\n[任务发送] 工作目录: {work_dir}")
    print(f"[提示词]: {message[:100]}...")
    print(f"[参数]: use_continue={use_continue}, has_system_prompt={system_prompt is not None}")
    print("⏳ 正在初始化流式监听管道并等待首包响应...")

    try:
        process = subprocess.Popen(
            cmd,
            cwd=work_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            bufsize=1
        )

        full_response_text = []

        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                clean_text = parse_and_print_codex_stream(line)
                if clean_text:
                    full_response_text.append(clean_text)

        process.wait()
        if process.returncode != 0:
            print(f"\n❌ Codex 执行异常退出，退出码: {process.returncode}")
        else:
            print(f"\n\n✨ Codex 任务段流式对接完毕。")

        return "".join(full_response_text)
    except Exception as e:
        print(f"💥 脚本运行时发生异常: {e}")
        return None


def _extract_cursor_message_text(message):
    """Extract assistant/user text blocks from a Cursor stream message."""
    if not isinstance(message, dict):
        return ""

    parts = []
    content = message.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
    elif isinstance(content, str) and content:
        parts.append(content)

    return "".join(parts)


def parse_and_print_cursor_stream(json_line, stream_state=None):
    """Decode Cursor Agent stream-json output and print useful content.

  stream_state is an optional dict used to deduplicate assistant chunks when
  --stream-partial-output emits both deltas and a final summary message.
    """
    try:
        data = json.loads(json_line.strip())
        event_type = data.get("type", "")
        subtype = data.get("subtype", "")

        if event_type == "system":
            if subtype == "init":
                model = data.get("model")
                if model:
                    sys.stdout.write(f"\n🤖 [Cursor 模型] {model}")
                    sys.stdout.flush()
            return ""

        if event_type == "user":
            return ""

        if event_type == "thinking":
            if subtype == "delta":
                sys.stdout.write("\r🧠 [Cursor 正在思考中...] ")
                sys.stdout.flush()
            return ""

        if event_type == "assistant":
            # model_call_id events repeat the already-streamed chunk before tool calls.
            if "model_call_id" in data:
                return ""

            text = _extract_cursor_message_text(data.get("message", {}))
            if not text:
                return ""

            is_stream_delta = "timestamp_ms" in data
            if stream_state is not None:
                if is_stream_delta:
                    stream_state["saw_streaming_assistant"] = True
                elif stream_state.get("saw_streaming_assistant"):
                    # Final full message after partial deltas; skip duplicate.
                    return ""

            sys.stdout.write(text)
            sys.stdout.flush()
            return text

        if event_type == "tool_call":
            if subtype == "started":
                sys.stdout.write("\n🛠️  [Cursor 工具调用]")
                sys.stdout.flush()
            return ""

        if event_type == "result":
            result = data.get("result")
            if isinstance(result, str) and result:
                if stream_state is not None:
                    stream_state["result_text"] = result
                sys.stdout.write(f"\n{result}")
                sys.stdout.flush()
                return result
            return ""

        if event_type == "error":
            msg = data.get("message", "")
            sys.stdout.write(f"\n❌ [Cursor 错误] {msg}")
            sys.stdout.flush()
            return msg if msg else ""

    except json.JSONDecodeError:
        if json_line.strip():
            sys.stdout.write(json_line)
            sys.stdout.flush()
    return ""


def run_cursor_task(work_dir, message, system_prompt=None, use_continue=False, add_dirs=None):
    """Execute Cursor Agent CLI task in headless mode with optional --continue."""
    try:
        cmd = build_cursor_base_cmd()
    except FileNotFoundError as e:
        print(f"💥 脚本运行时发生异常: {e}")
        return None

    if use_continue:
        cmd.append("--continue")
        prompt = message
    else:
        prompt = message
        if add_dirs:
            extra_dirs = "\n".join(f"- {d}" for d in add_dirs)
            prompt = f"{prompt}\n\n[ADDITIONAL DIRECTORIES]\n{extra_dirs}\n[/ADDITIONAL DIRECTORIES]"
        if system_prompt:
            prompt = f"[SYSTEM PROMPT]\n{system_prompt}\n[/SYSTEM PROMPT]\n\n[USER PROMPT]\n{prompt}"

    cmd.append(prompt)

    print(f"\n[任务发送] 工作目录: {work_dir}")
    print(f"[提示词]: {message[:100]}...")
    print(f"[参数]: use_continue={use_continue}, has_system_prompt={system_prompt is not None}")
    print("⏳ 正在初始化 Cursor Agent 流式监听管道并等待首包响应...")

    try:
        process = subprocess.Popen(
            cmd,
            cwd=work_dir,
            env=subprocess_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            bufsize=1
        )

        full_response_text = []
        stream_state = {"saw_streaming_assistant": False, "result_text": None}

        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                clean_text = parse_and_print_cursor_stream(line, stream_state)
                if clean_text:
                    full_response_text.append(clean_text)

        process.wait()
        if process.returncode != 0:
            print(f"\n❌ Cursor 执行异常退出，退出码: {process.returncode}")
        else:
            print(f"\n\n✨ Cursor 任务段流式对接完毕。")

        if stream_state.get("result_text"):
            return stream_state["result_text"]
        return "".join(full_response_text)
    except Exception as e:
        print(f"💥 脚本运行时发生异常: {e}")
        return None


def human_gate(stage_name, review_file_path=None):
    """Human review gate with support for feedback loops."""
    print("\n" + "=" * 50)
    print(f"🛑 【人工确认卡点】{stage_name} 阶段已完成！")
    if review_file_path and os.path.exists(review_file_path):
        print(f"📝 请前去审查该文件: {review_file_path}")
    print("=" * 50)

    while True:
        user_input = input("\n👉 请输入指令 [ Enter 键通过 / 输入修改意见让 AI 重做 / 输入 'exit' 退出 ]: ").strip()
        if user_input.lower() == 'exit':
            print("👋 流程被人工终止。")
            sys.exit(0)
        elif user_input == "":
            print(f"💚 阶段 {stage_name} 已人工确认通过，准备进入下一阶段...")
            return None
        else:
            print(f"🔄 收到反馈意见，正在指示 Claude 重新调整...")
            return user_input
