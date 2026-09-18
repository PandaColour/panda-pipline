---
name: panda-pipeline-ui-assets
description: 当前流水线任务准备、补充、转换或审查 UI 原件、资源映射及工程素材时使用，按角色权限维护可追溯物料。
---
# UI 物料

先确认当前目标平台、页面/状态、UI AC 和角色模式；不把后端需求强制转成 UI 任务。读取 [物料索引与审计](references/materials.md) 与 [物料准备和分阶段交接](references/handoff.md) 的当前模式部分；设计源为 Figma 时再读取 [资源筛选](references/selection.md)。需要实际远程 Figma 请求或判断其可用性时，必须读取当前工程安装的 `panda-pipeline-figma-access`，再执行定点发现、读取和降级。

- 拆分/分析：准备当前阶段范围内的原件、来源和 manifest；不提前要求工程入包或运行图。
- 拆分审核/需求审核：只读核对原件、索引及审计，缺口反馈生产角色，不自行下载或修改物料。
- 开发：转换、入包和验证当前需求资源。Android 读取 [Android 资源规范](references/android.md)，iOS 读取 [iOS 资源规范](references/ios.md)；Web 等其他目标按原始需求与实际工具链，不加载无关平台规范。
- Code Review：核验实际消费和证据；仅在角色 prompt 授权下补充当前需求原始物料。修改工程资源、源码或测试仍交回 Developer。审查涉及 Android/iOS 入包资源时读取对应平台规范。

复审只核验改动资源、直接消费页面与失效证据。现有审计 passed 只证明脚本实际检查的内容，不证明语义正确或视觉通过。使用下方相对 skill 目录的审计脚本命令，当前报告保留缺失、已补内容、路径与验证结果，不另建平行物料根目录。

## 本轮校验入口

使用随包安装的 [figma_asset_audit.py](scripts/figma_asset_audit.py)：

执行下面命令时，将工具的工作目录（cwd/workdir）设为当前 `SKILL.md` 所在目录；相对路径 `scripts/` 从这里解析，不从业务项目或 `references/` 目录解析。使用当前环境可用的 Python 3.11+，示例命令为 `python3`。业务项目、requirements 和报告路径都使用明确的绝对路径，含空格时正确引用。执行完脚本后，业务命令仍在业务项目目录运行。

```bash
__PANDA_FIGMA_AUDIT_COMMAND__ --requirements-dir <当前requirements绝对路径> --requirement-id <当前R-xxx> --report <本轮指定审计报告绝对路径>
```

拆分阶段审核本批全部范围时省略 --requirement-id；小需求只校验当前项。报告位置和下载/修改权限仍由当前角色决定。校验脚本不代替实际看图，不因安装完成自动执行。脚本已随 skill 安装，不要求在业务源码根找到同名文件。
