---
name: panda-pipeline-ui-fidelity
description: 当前流水线任务涉及 UI 需求拆分、精细分析、实现、视觉验收或总结既有 UI 证据时使用；包括设计来源失败、资源缺口、屏幕适配和动态文案差异。
---
# UI 需求分析、实现与验收

这是 UI 工作的统一规范入口。当前需求决定目标平台和设计来源；仅处理原始 UI 范围，不新增 AC，不改变角色写入权限、首审/复审范围、调度和 FINAL_ANSWER 协议。

## 按当前模式读取

除 `summary` 外，以下 UI 模式先读 [设计来源与验收边界](references/sources-and-boundaries.md) 和 [资源缺口](references/gaps.md)，再只读对应行的规范，不全文加载所有阶段：

| 当前模式 | 必须读取 | 本阶段结果 |
|---|---|---|
| `breakdown` / `breakdown-review` | [拆分与拆分审核](references/breakdown.md) | 范围、AC/状态/节点映射、原始物料入口及已知缺口；审核只读，不提前要求精细 Token、工程资源或运行截图 |
| `analysis` / `requirements-review` | [精细分析与需求审核](references/analysis.md) | 当前需求的精确基准、适配依据、检查点与验证安排；审核只读核对 |
| `development` | [实现与自测](references/development.md)、[视觉证据](references/evidence.md) | Token → 代码、实际设计/运行对照、自测及剩余缺口 |
| `code-review` | [验收与复审](references/review.md)、[视觉证据](references/evidence.md) | 独立核验原始 UI AC；复审仅查既有问题、直接回归及缺失/失效证据 |
| `summary` | [既有 UI 证据汇总](references/summary.md) | 只读核对既有结论与矛盾，不重新获取设计、启动设备或展开全量验收 |

调用消息明确的模式优先于角色名。纯逻辑/后端任务不因发现此 skill 增加 UI 检查；记忆整理与回执补正不执行本 skill 的设计获取、素材生成、设备启动或重新验收。

## 按动作加载工具规范

从调用消息提供的“项目已安装 skills 目录”读取 `<安装目录>/<skill名>/SKILL.md`，使用相同角色模式；不能仅凭名称或其他角色已读就跳过：

- 要准备、补充、转换或审查原件、映射与工程资源时，必须读取 `panda-pipeline-ui-assets`。范围、筛选、倍率/画布、转换与审计由它统一规定；本 skill 的 UI 基准和视觉结论不能用物料审计代替。
- 当前阶段要读取远程 Figma 或判断可用性/降级原因时，必须先读取 `panda-pipeline-figma-access`，遵循定点发现、MCP 自带规范、请求去重和限流冷却。仅复用有效证据的复审、总结不为此额外联网。
- 当前 Android AC 确需设备验证且本轮为开发或 Code Review 时，必须读取 `panda-pipeline-android-device-validation`；其他角色无设备启动权限，其他平台用实际工具链。

规范结果写入调用指定的既有需求/分析/开发/审核/总结报告，保留 AC 编号、来源和未验证事实，不新增平行台账。共享入口与 manifest 沿用原路径，文档精简不删除物料或引用。技能入口不可读时报告具体配置缺口，不虚报执行；远程设计获取失败按来源规则处理。
