# Agent 会话后端匹配设计

## 目标

恢复持久化 Agent 会话时校验当前 `agent_type`。类型一致才复用已有 session ID；类型不一致时创建新会话，并用首次返回的新 session ID 和当前类型覆盖原记录。

## 设计

- `ExecutionPlanStore.get_agent_session()` 新增可选 `agent_type` 参数。
- 字典格式的会话记录同时存在已保存类型和当前类型时，仅在两者一致时返回 session ID；不一致返回 `None`。
- `BreakPipeline._create_agent()` 在读取 session ID 时传入即将创建的 Agent 类型。
- `Agent.send_message()` 和 `CursorAgent`、`CodexAgent`、`ClaudeAgent` 不修改：收到 session ID 时继续 resume，收到 `None` 时继续创建新会话。
- 新会话返回 ID 后沿用现有 `session_update_callback`，保存新的 session ID、prompt 文件和当前 Agent 类型。

## 兼容性

旧版纯字符串记录或缺少 `agent_type` 的字典记录无法判断原后端，继续按现有行为恢复，避免破坏已有执行计划。只有明确记录了不同类型时才放弃旧 session ID。

## 测试

- 当前类型与保存类型一致时恢复原 session ID。
- 当前类型与保存类型不一致时首次调用不传 session ID，并将新返回的 ID 与当前类型写回执行计划。
- 缺少类型的旧记录仍恢复原 session ID。
