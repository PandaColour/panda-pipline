# Panda Pipeline

## 工程目标

快速验证多 Agent 流水线，执行 Codex、Claude、Cursor 三种主流智能体工具，协作完成需求分析、开发、测试、审查与记忆整理。

## 环境初始化和使用

首次使用时，从示例文件创建不会提交到 Git 的本地配置：

```bash
cp config/config.json.example config/config.json
```

根据 `config/config.json` 中的角色配置，确保本机已安装并完成所用命令行工具的认证。可配置的工具为 `codex`、`claude`、`cursor`、`dsh` 和 `opencode`。然后初始化 Python 环境：

```bash
python -m venv .venv
source .venv/bin/activate  # Windows 使用 .venv\Scripts\activate
```

运行前编辑仓库根目录的 `config/config.json`，配置目标工程、仓库与各流水线角色使用的 Agent 工具。该文件已被 Git 忽略；需要更新默认模板时，请修改并提交 `config/config.json.example`。`REPOS` 和 `AGENT_TYPES` 都是对象数组：

```json
{
  "PROJECT_ROOT": "/Users/panda.colour/Company/ios-m6",
  "REPOS": [
    {
      "url": "https://gitee.com/pandacolour/aiphone.git",
      "branch": "main"
    }
  ],
  "AGENT_TYPES": [
    {"role": "requirement_breaker", "agent_type": "cursor"},
    {"role": "breakdown_reviewer", "agent_type": "cursor"},
    {"role": "requirements_analyst", "agent_type": "cursor"},
    {"role": "requirements_reviewer", "agent_type": "cursor"},
    {"role": "developer", "agent_type": "cursor"},
    {"role": "code_reviewer", "agent_type": "cursor"}
  ]
}
```

每个角色可独立设为 `claude`、`codex`、`cursor`、`dsh` 或 `opencode`。配置缺失、空值或未支持的工具名称会直接报错，不会默认回退到其他工具。

运行普通开发流水线：

```bash
python main.py
```

运行大需求拆分流水线：

```bash
python break_main.py
```

如需保留所有人工审核卡点、但自动按回车通过：

```bash
python main.py --skipHuman
python break_main.py --skipHuman
```

通宵或长时间运行拆分流水线时，macOS 可能睡眠导致进程暂停。仓库提供了通用保活脚本：

```bash
./run_break_main_awake.sh
```

脚本会在自身所在仓库目录执行 `caffeinate -dimsu python3 break_main.py --skipHuman`，运行期间阻止系统睡眠，并支持继续追加 `break_main.py` 参数。IntelliJ IDEA 可新建 `Shell Script` Run Configuration，`Script path` 选择 `run_break_main_awake.sh`，`Working directory` 选择本仓库根目录。

## 小需求持续推进与降级

`blocked` 仅用于需求拆分/拆分评审的资源访问关口。小需求分析、评审、开发、Code Review 不得用它挂起整个需求：

- 物料远程优先，允许按需补充下载；读取失败时按失败节点使用已审计本地基线。不能用近似图标/占位图伪装缺失资源，缺口不影响其他可控工作继续。
- 需求冲突执行现有 Agent 保守决策：显式限制优先、保持既有行为、默认关闭、可替换边界、fail-closed；不等待逐项产品签署才开发。
- 环境缺失先检查用户已有 Mock 服务、账号和项目注入配置，走 Mock 登录及业务场景；Mock 健康检查或无凭据访问真实服务的 401 均不代表业务验证结果。真实联调缺口单独披露。
- 本地设备先复用，再启动已有 AVD；无适用 AVD 时允许使用已安装 SDK/镜像创建本地测试 AVD。命令带硬超时，不擅自覆盖已有设备或关闭他人实例。

需求评审、代码审查各累计最多 10 次。需求评审到上限记录 `review_outcomes.requirements_review=not_approved` 后继续开发；Code Review 到上限记录未通过并结束当前需求回合，后续依赖项可以继续，但会收到上游未决事实，必须检查已有实现、Mock 或可替换边界，不能把调度放行理解为上游已验收通过。

当前小需求回执不允许 `blocked`，返回此状态按协议错误处理，不当作批准。历史计划中的 `blocked` 兼容记录仍可读取：恢复旧的 `外部阻塞` 小需求到原阶段，旧的需求评审上限挂起恢复到开发阶段。证据转存 `suspension_history`，累计次数不重置。此迁移只在使用本版本运行对应项目时发生，不会自动修改其他项目副本；没有恢复阶段的旧外部阻塞项从需求分析重建可执行方案。

不再提供 `--resume-item` / `--evidence-file` 外部证据恢复关口，正常运行 `python3 break_main.py --skipHuman` 即可继续。历史通用 `阻塞` 状态不等同于新版生成的 `外部阻塞`，不猜测解除可能由人工设置的通用阻塞。

仍有未通过的评审时，全部回合执行完毕后标记“执行结束（有未通过项）”，正常结束本次运行、不归档、不宣称全部验收成功；完整记录保留在 execution_plan.json 和各项报告。没有未通过项时沿用正常完成/总结/归档流程。拆分评审自身达到上限仍暂停拆分，不带着未批准的拆分直接开发。

## Agent 文档交接与短回执

两条流水线统一通过 `TaskMessage` 声明本轮任务、项目根目录、输入文档路径、必需/可选输出路径、阶段与审核轮次、具体执行要求和完成条件。角色提示词提供长期职责，调用消息指定本轮工作。需求、分析、开发、测试及审核报告全文不进入调用消息；原始需求、反馈、调用日志和不可变报告快照存入 `requirements/handoffs/`，消息只传路径。

最终回复只允许 `FINAL_ANSWER` 后跟一个 JSON 对象，含标记与空白共不超过 **2048 字符**（中文按字符计）。必填 `status`、`summary`、`outputs`；`approval_token` 仅为可选补充说明，可省略、为 `null` 或空字符串，不参与流程判定；`outputs` 是名称到已生成文档路径的映射。详细 issues、日志和证据全部写报告。非评审完成使用 `completed`；评审通过由当前阶段允许的 `status=approved` 和必需产物校验决定。空回复、关键词命中、非法 JSON、超长回执、未声明或不存在的输出路径不能批准任务。

每次审核调用前持久化累计次数；启动失败、网络失败、回执格式错误和回执补正均占用额度。任务调用关闭后端隐式重试，避免绕过计数。审核累计最多 10 次；原有拆分流水线的到限后续调度规则保留，普通流水线到限停止并保留未通过状态。失败类型、日志路径和每轮报告快照记录在 `execution_plan.json` 的 `attempt_history` 中，重启和索引规范化都不清零。

回执补正只重发结果，不重新执行业务任务；补正时遇到网络/启动失败，保留补正模式及原始回执日志继续占用剩余额度。非审核阶段的回执最多自动补正一次。需要人工处理的资源访问阻塞将完整资源 URL、原因和所需动作写入调用声明的 `resource_blocker.json`，短回执通过 `outputs.blocker` 引用它。

验证命令：`python3 -m unittest discover -s tests`。

## 欢迎交流学习

欢迎交流学习：panda.colour@qq.com
