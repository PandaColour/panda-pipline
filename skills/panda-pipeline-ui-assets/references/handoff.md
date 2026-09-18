# 原始物料准备与分阶段审计

仅适用于当前需求实际使用的 UI 物料；Figma 专项仅在其为设计来源时执行。以下“全部”指当前明确交付范围；复审只重验变更、已有问题和失效证据，保留未受影响矩阵。不扩大角色在 prompt 中规定的写入权限。

## 获取与用途核验

1. 按 UI AC → 页面/状态 → 消费节点核对全部 FRAME，遍历范围内候选资源，不得抽样，也不下载整个 Figma 文件的无关图库。原始节点和参考图按 file/node/version 去重，父响应完整覆盖子节点时直接复用。
2. 图片物料、字体与确认必需独立资产下载到本地当前 `figma_assets/`，静态原件按设置或默认 SVG/PNG @2x，动图/视频保留原格式和播放约束。按类型存放，如 `icons/`、`images/`；每个关键页面必须有参考效果图保存到 `figma_assets/reference_screens/`。下载后实际检查路径可读、内容、尺寸及用途，不只相信命令执行成功。
3. 参考效果图不等于独立资产。不能只导出 logo/切图区而漏掉业务插图、弹窗或内嵌定制 icon，也不能以系统近似图标、Compose 绘制或截图抠图掩盖缺失。核实属于原生布局/渐变的样式可按筛选规范实现；父资产已覆盖的子路径记录合法覆盖关系，不重复切碎。
4. 物料映射表仅维护在 schema_version: 3 的 manifest：来源节点、版本/原始响应、文件相对路径、资源类型、格式/倍率、具体用途与消费状态、导出/复用/排除依据。字体与资源文件逐一验证；冗余文件须说明用途或由有权限角色整理，不得删除旧证据掩盖遗漏。
5. 本地物料不完整时列出具体缺失资源/页面/状态、查过的来源、失败原因、影响 AC、可还原部分、临时边界及补验条件。不能只写“待补/下游补充”，也不能仅按这些词判断违规；真实缺口交接和责任说明不是推卸。只有关键来源不可用且无法确定范围/必要契约时按角色资源访问协议处理，其余部分继续有依据的工作，不伪报审计通过。

无 Figma 设计稿时记录该事实并沿原需求指定的其他设计资料；若确无设计基准，明确需由开发完成的 UI 设计范围，不虚构节点、原件或 Figma 审计结果。

## 审计执行与报告

脚本入口、Python 与工作目录规则见本 skill 的 SKILL.md；审计只读物料，输出审计报告。参数均以本次调用的实际绝对路径为准，默认布局示例如下。现有简化流水线同样使用 R 编号（默认 `R-001-main`），应使用调用给出的实际 ID 和目录，不能从角色名称推断没有 R 编号：

| 模式 | --requirements-dir | --requirement-id | 默认 --report |
|---|---|---|---|
| breakdown | 当前 requirements 根目录 | 省略，核对本批范围 | requirements/figma_asset_audit_report.json |
| breakdown-review | 当前 requirements 根目录 | 省略 | requirements/figma_asset_audit_review_report.json |
| analysis | 当前 requirements 根目录 | 当前 R-xxx | 当前项/figma_asset_audit_report.json |
| requirements-review | 当前 requirements 根目录 | 当前 R-xxx | 当前项/figma_asset_audit_review_report.json |
| development | 当前 requirements 根目录 | 当前 R-xxx | 当前项/figma_asset_audit_developer_report.json |
| code-review | 当前 requirements 根目录 | 当前 R-xxx | 当前项/figma_asset_audit_code_review_report.json |

当前 `figma_asset_audit.py` 读取根目录 `_figma_inventory.json`，`--requirement-id` 必须是其中的真实键，并唯一对应 `<ID>-*` 子目录；该脚本不接受任意单包目录作为根目录。自定义布局不满足这些输入时，记录脚本适用性缺口并按本规范核验实际资料，不能虚构 ID、移动资料或宣称脚本 passed。非 Figma 来源不执行该 Figma 专项脚本，记录不适用而非通过。

拆分/分析在准备后主动运行；开发在实现前只读运行并在补充后重跑；审核首审或物料变更/审计证据失效时独立运行。报告记录实际命令、退出码、报告路径、FRAME 总数/已读取数/发现资产数/导出数/跳过数/缺失数。退出非 0、未读取或未决资源不可宣称对应资料完整；审计已通过也不能代替实际视觉核对。

## 角色权限与交接

- breakdown：准备已识别必需原件、范围与设计入口，不做工程转换或运行验收。被指出同类漏项后完成当前需求范围内同类检查与对应审计，不仅修点名页。
- analysis：允许补齐当前 R-xxx 的原始资料、manifest 和分析 Token；禁止修改其他 R-xxx。核对精确属性与用途，不替开发提前产出工程入包或运行截图。
- breakdown-review / requirements-review：物料全程只读，允许写本阶段审查/审计报告；禁止修改 figma_assets、manifest、物料映射表或自行下载。首审独立核实远程范围及筛选依据，Figma 真实失败则核对已保存基线和失败证据。缺陷返回 changes_requested 给 Requirement Breaker / Requirements Analyst，不替生产角色修复。审核报告的「物料完整性校验表」可引用 manifest，保留节点/页面/状态、路径、格式、存在性、独立资产/父覆盖依据、格式合规性、缺口与结论，不能只信映射声明。
- Developer 和 Code Reviewer 均允许在对应角色授权下后续合理补充，不能因此把上游已知必需资源故意留给下游。允许按需补充下载当前 R-xxx 实际需要的资源，补充前核实 AC、消费节点/状态、真实类型和缓存；原件补充仅写当前 figma_assets、asset_manifest.json 和物料映射表，禁止修改其他 R-xxx、原始需求或 AC。同步 selection_evidence、来源/格式/用途/路径、补充者与原因；旧映射按物料入口协议合并升级到 schema_version: 3。补充后重新运行当前小需求审计，逐文件核验并在现有报告记录前后差异。
- development：在上述原件范围外，按本角色开发授权完成工程转换、入包、源码接入及运行验证，记录“资源 → 代码使用位置与播放行为”。
- code-review：可以补原件，不修改源码、测试或工程资源；补齐后仍核对真实消费、入包、动画与当前构建截图，不能仅因下载成功就通过。需要代码接入或设备重采交回 Developer，Reviewer 仍可按自身授权独立验证。纯实现遗漏返回 changes_requested；类型/范围确需修订才按角色允许的状态交 Requirements Analyst。审计缺口只影响对应节点，其他有效部分继续；本地足够的可修复遗漏不能归为外部缺失。
