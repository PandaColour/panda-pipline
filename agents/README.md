# Agent 会话恢复

各后端负责命令构造和输出解析，返回 AgentRunResult。通用重试策略位于
`_retry.py`，Codex、Claude、Cursor、OpenCode、DSH 均调用它。

- 明确的上下文超限或会话失效诊断触发 session_invalidation_callback。
  Agent 先调用持久化回调清除引用，再清空内存 session；清除失败直接传播，
  不启动新会话。原始会话历史文件不删除。
- BreakPipeline 的持久化回调接受 None，清除执行计划中该 Agent 的引用，
  包括旧格式的回退记录，防止重启恢复失效会话。
- 普通失败仍沿用原会话及原有重试预算（首次调用加最多三次重试）。
  单次 run 最多进行一次新会话恢复；新会话再次上下文超限会立即返回失败。
  该限制不改变外层进程重启策略。
- 新会话由后端原有无 session 分支创建，重新携带角色提示词和当前调用消息。
  不复制失效线程历史；调用消息应包含当前任务和所需产物路径。
- 更换会话后的最终失败不返回可持久化的 session ID；成功后按原回调保存新 ID。

错误分类只检查非零返回结果的运行时诊断，不检查成功回复正文。
单独的 compact 失败不代表会话失效。新增后端错误格式时应补充真实诊断样例
和 tests/test_session_recovery.py，避免把一般网络错误或文件不存在误判为会话失效。

# 固定系统提示词

流水线启动时，由 environment.py 统一渲染角色 prompt、命令模板和 skills，覆盖代码根目录
`temp-prompt-skills/prompts/`、`temp-prompt-skills/commands/` 和 `temp-prompt-skills/skills/`，随后覆盖安装项目级 skills。
prompts 保留 system-prompt、break-system-prompt 两类角色目录；commands 保留 system-command、break-command 两类命令目录；skills 包含规范、引用、脚本及依赖。
不保留历史版本或安装归属记录。目录已加入 Git 忽略。

调用消息只提供项目已安装 skills 目录：Claude 使用 `<工程>/.claude/skills/`，
其他后端使用 `<工程>/.agents/skills/`。渲染目录不作为 Agent 的 skill 入口。
详细规则按角色 prompt 的触发条件从安装目录读取，脚本相对各 skill 目录执行。
不检测版本、不通知 Agent 加载新版，也不主动刷新运行中的模型上下文。
修改源文件后再次渲染/安装，直接覆盖原路径即可。

直接创建 Agent 而未准备 environment 的兼容调用仍在此目录下按角色原目录固定 prompt；
直接调用后端、未经过 Agent 角色加载的调用按内容哈希放入 `temp-prompt-skills/inline/`。
兼容调用不会自动安装 skills；需要技能的流水线须先完成 environment 准备。

各后端的传递方式：

- Codex 保持 stdin；首次从固定规则构造原有输入，恢复会话仍只传当次任务。
- Claude 使用 `--append-system-prompt-file <绝对路径>`，任务继续走 stdin，
  保留追加系统规则的语义，恢复会话也传规则文件。
- OpenCode 改用 stdin，首次输入保留原有角色/任务/附加目录结构，恢复时仍只传任务。
  已检查本机 1.18.18 的 `run` 入口支持管道输入。

- Cursor 首次调用只在命令行传固定规则文件的绝对路径和读取指令，要求先完整读取再执行任务；
  resume 保留同一路径，需要时重读，未读或上下文丢失时先完整读取。角色全文不再进入 argv。
  Python 启动前检查文件可读；模型侧读取失败须报告原因，不能跳过规则。
  这属于文本指令，不是 Cursor 原生 system-prompt-file 参数，也不减少模型读取规则的 Token。

当前任务消息不另写文件；记忆整理/总结命令模板一起渲染，具体任务占位符仍在调用时填充。
`break-command/` 存放 BreakPipeline 的 memory_curation.md、requirement_summary.md；
`system-command/` 存放普通 Pipeline 的 memory_curation.md。它们通过 `_render_command` 生成调用消息，发送给已有角色 Agent，不作为独立角色 prompt。
命令模板只定义当前任务，不重复 FINAL_ANSWER 章节；回执规则由角色 prompt 和 TaskMessage 的统一协议提供，阶段允许状态与必需输出仍由调用消息声明。
Cursor 任务仍走命令行，特别长的任务仍可能超限；DSH 的 CLI 传参方式保持原状。
以上四个后端在 Windows 上会检查序列化命令长度；超限报错，不截断规则或任务。
