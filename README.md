# Panda Pipeline

## 工程目标

快速验证多 Agent 流水线，执行 Codex、Claude、Cursor 三种主流智能体工具，协作完成需求分析、开发、测试、审查与记忆整理。

## 环境初始化和使用

### Prompt 与 skills 渲染、安装

`environment.py` 在项目工作目录就绪后，统一渲染角色 prompt 和 `skills/`，输出到流水线代码目录的 `temp-prompt-skills/`。其中 `prompts/` 保留两套角色 prompt 目录，`commands/` 保存 `break-command/`、`system-command/` 的任务模板，`skills/` 保存规范、引用及可执行脚本。业务工作目录按运行参数渲染，脚本使用 `python3 scripts/<脚本名>.py`，相对对应 `SKILL.md` 所在目录执行；具体任务的 `{requirement_id}` 等占位符仍在调用时填充，JSON 花括号不参与此轮替换。

随后安装项目级 `.agents/skills/`（Codex、Cursor）及 `.claude/skills/`（Claude、Cursor 兼容发现）入口；不修改全局 skills。所有入口使用 `panda-pipeline-` 前缀：

| Skill | 按需加载内容 |
|---|---|
| `panda-pipeline-figma-access` | 定点发现、MCP 自带规则、请求去重、429 冷却与交接 |
| `panda-pipeline-ui-assets` | 物料索引、资源筛选、平台转换规范、Figma 校验脚本 |
| `panda-pipeline-ui-fidelity` | 分阶段设计细化、视觉自测、证据及复审要求 |
| `panda-pipeline-android-device-validation` | 开发/Code Review 的设备选择、启动脚本与设备回执 |
| `panda-pipeline-static-analysis` | 静态扫描流程、扫描脚本及配置规则集 |

每个角色 prompt 明确触发条件、读取方式与权限边界。调用消息只提供项目已安装 skills 路径；不依赖客户端自动发现，也不把全部 skill 正文拼入每轮任务。脚本、依赖及规则配置直接维护在对应 `skills/<skill名>/scripts/`，渲染安装时完整复制 skill 目录，不携带流水线本地配置中的凭据；安装本身不执行审计、扫描或设备启动。脚本要求当前环境 Python 3.11+，使用相对入口时显式设置 skill 工作目录；业务目录和报告参数仍传绝对路径，不把切换后的 cwd 当成业务根目录。

每次启动直接覆盖渲染目录和项目内同名 skills，不维护版本、哈希或安装归属记录，也不向 Agent 发送版本检测/重载指令。只覆盖仓库提供的 skill 名称，其他 skills 保留。源 prompt/skill 修改后再次渲染并安装即可覆盖；不监视源文件，也不主动刷新正在执行的模型上下文。渲染目录已忽略 Git；项目安装目录写入本地 Git exclude，不修改业务 .gitignore；静态扫描排除安装目录，避免扫描业务项目时把工具代码计入。

### MCP 启动检查

使用 Python 3.11 或更高版本。`environment.py` 在工作目录就绪后、Agent 启动前检查已配置的 `figma-android-mcp`，不输出 Token。

- Cursor 在当前工作目录逐个批准 `.cursor/mcp.json` 中的全部 MCP 服务，无 Figma 配置也执行；单项失败继续尝试其余服务，随后明确报错。Figma 另做 Token 校验并核对三个必要工具可发现；仅全局配置的其他服务不纳入项目批量批准。
- Claude 自动批准当前项目 `.mcp.json` 中的全部 MCP 服务：写入 `.claude/settings.local.json` 的 `enableAllProjectMcpServers=true`，清空其中的 `disabledMcpjsonServers`，保留其他权限配置。没有 Figma 服务也执行这项批准；配置 Figma 时另检查连接状态。
- Codex 配置了 Figma 服务时，自动将当前工作目录设为 `trusted`，核对有效配置及工具过滤；实际 MCP 连接在 Agent 启动时建立。

Token 身份校验失败或必要服务检查失败会在 Agent 启动前报错。429、身份接口缺少 `current_user:read` 权限、网络异常记为“未验证”，继续现有物料降级流程；身份校验成功不代表目标设计文件可访问或图片下载配额充足。

### Android CLI 环境准备

Android CLI 与其他外部工具统一放在 `config/config.json` 的 `EXTERNAL_CLI_TOOLS` 中，`environment.py` 没有 Android CLI 专用安装分支。三份示例分别配置 macOS Homebrew、Windows winget、Linux x86_64 官方用户级安装脚本；Python 不按工具名硬编码平台规则。Linux 使用 `~/.local/bin/android` 检查和验证，命令可执行文件中的 `~` 会展开，不依赖安装器修改 Shell 配置后才能生效的 PATH。Windows 安装若更新了 PATH，当前进程可能仍找不到命令；可重新打开终端或将检查/验证命令首项改为安装后的绝对路径。官方安装方式：https://developer.android.com/tools/agents/android-cli/download 。检查命令可使用绝对路径，避免 PATH 中旧命令遮蔽新安装；`verify` 中的命令应使用同一个可执行文件。

配置保留版本/首次初始化检查上限 90 秒，以及布局、截图、坐标解析和部署的四项能力检查（各 15 秒）；安装沿用通用 300 秒上限。检查通过后按 `path_env` 配置，以 `PANDA_PIPELINE_ANDROID_CLI` 传递绝对路径；失败或禁用清空该变量并继续 ADB 流程。已有可用工具不重装、不自动升级；不再创建流水线专用 Android CLI 下载目录，也不删除已有安装。CLI 自身首次调用仍可能下载运行时，超时仅提示。工具使用规范在设备验证 skill 中，不自动安装官方 skills、不启停设备或更新 SDK。

### Android 模拟器统一启动

开发和 Code Review Agent 按提示读取 `panda-pipeline-android-device-validation/SKILL.md`，将命令 cwd/workdir 设为该 skill 目录，执行 `python3 scripts/android_emulator.py`；每次任务交接（含恢复会话）也沿用该入口。其他角色及记忆整理、总结、回执补正阶段不启动设备。仅当前 Android 验收需要时调用，复审继续复用有效证据。

手动使用（在 `skills/panda-pipeline-android-device-validation/` 目录执行）：

```bash
# 优先唯一在线真机，再复用唯一在线模拟器；没有可用设备时才准备模拟器
python3 scripts/android_emulator.py ensure

# 明确选择真机；离线、未授权或拔出时不等待，自动降级
python3 scripts/android_emulator.py ensure --serial <ADB设备ID>

# 按当前设计基线创建/选择标准模拟器（示例规格，不是项目默认值）
python3 scripts/android_emulator.py ensure --avd DesignPhone --api 35 --device pixel_6 --width 750 --height 1624 --density 320

# 仅用户显式停止脚本管理的模拟器
python3 scripts/android_emulator.py stop --avd DesignPhone
```

`--serial` 与 `--avd` 互斥。未指定时优先唯一在线真机，即使同时有模拟器在线；无在线真机才复用唯一在线模拟器。多台在线真机需明确选择真机，仅有多台在线模拟器时需明确选择模拟器。显式 --serial/--avd 保留指定设备优先级。每轮验证默认重新选择，不沿用历史模拟器 ID；真机重新上线后下一轮切回，正在执行的测试不中途切换。确需固定模拟器视觉基线时说明理由后指定。真机离线、未授权或拔出时不轮询等待，切换其他可用设备，无可用设备才准备模拟器；模拟器 offline 时报告错误，不重复创建。指定 API 与已连接设备实际 API 不匹配时报告错误，不偷偷换机；只有项目明确限制 API 时才传 `--api`。`--device` 是 AVD profile，不是 ADB ID。新建省略 API/profile 默认 35/pixel_6，不能代替项目要求。

`--width/--height` 是目标设备像素 px，`--density` 是设备密度 dpi，三者必须一起传正整数。先确定目标逻辑 viewport 和设备密度，按 `px = dp×dpi/160` 换算：375×812 dp、320 dpi 应传 `--width 750 --height 1624 --density 320`；误传 375/812 请求的是 187.5×406 dp。参考图导出 1×/2× 只影响图片像素，不决定设备密度或分辨率；不要直接照抄画板数字、导出图像素或长滚动图高度。

新建 AVD 将参数写入设备配置，自动名称包含屏幕规格。已经连接的设备尺寸不匹配仍复用，只返回差异，绝不修改设备分辨率、密度或字体缩放；已有未启动 AVD 不匹配则报错，不覆盖，也不自动另建。

成功退出 0 并输出单条 JSON：`status=ready`、`serial`、`avd`（真机为 null）、`device_type`（physical/emulator）、`api`、`adb_path`、`adb_args`、`screen`、`selection` 及已有启动/日志字段。`screen` 包含实际有效像素尺寸、dpi、`logical_width_dp/height_dp`、font_scale、target、`target_logical_width_dp/height_dp`、matches_target、differences、warnings；未传目标时请求逻辑尺寸为 null。优先采用 Android 的 Override 值，无法读取时标记未知，不宣称匹配。matches_target 只比较请求与实际设备的像素尺寸和密度，字体缩放另报；不匹配时 warnings 同时解释请求/实际逻辑尺寸，提示核对 px/dp 和导出倍率，不自动改变目标或设备，也不能据此判 UI 失败。`selection.fallback_reason` 说明真机降级原因。

UI 并排图按对应业务画布等比缩放到统一展示宽度，标注两图原始像素、逻辑宽度、缩放系数和安全区裁剪。例如同为 375 dp 宽，375 px 参考图保持 1×，750 px 运行图缩放 0.5×。长图分段或留白，不拉伸到相同高度；保留原图，不用展示图覆盖物料。不同逻辑 viewport 仍按响应式规则判断，不能因展示同宽就要求布局或换行完全相同。生成并排图不等于完成视觉核对。

后续安装、截图等命令必须使用最终回执中的 `adb_args`，不沿用失效的设备 ID，也不把 AVD 名称当作 serial。失败输出 `status=error`、stage、error 和日志路径，`serial=null`；不能继续设备操作。安装进度只写 preparation.log。并发调用通过用户级锁串行准备设备。当前宿主支持仍为 macOS。

模拟器由用户会话的 launchd 管理，`caffeinate -i` 与模拟器共同运行；脚本退出或 Agent 崩溃不会关闭它，也不会继承 Agent 输出管道。锁等待最多 --prepare-timeout，准备/下载另有 --prepare-timeout 期限（默认 1800 秒，允许 1–7200 秒），设备启动 --timeout 默认 180 秒（允许 1–600 秒）。Agent 外层超时需覆盖以上三段，默认至少 3900 秒；工具支持时可异步执行并轮询脚本回执。ADB/launchctl 等短命令最多 10 秒，下载安装和创建命令分别受准备期限及单步上限约束，超时杀掉其专用进程组。已成功安装资源下次复用；中断的命令行工具临时下载不会当作安装成功。脚本创建的 AVD 数据位于服务目录的 avds/，由创建记录标识；创建中断后下次只清理自身未完成输出，再创建，不覆盖外部 AVD。验证结束不关闭实例，只有用户显式 `stop --avd` 才卸载该脚本管理的服务，不操作外部启动的模拟器。

服务定义和日志位于 `~/Library/Application Support/panda-pipeline/android-emulator/`。服务按需加载，无开机自动启动和崩溃无限重启。防休眠允许锁屏/熄屏，随该模拟器退出释放；不保证合盖、手动睡眠或注销后运行。复用外部设备时 `managed=false`、`sleep_protection=external`，其防休眠仍由原有环境管理。

系统级自测可运行 `python3 tests/android_emulator_launchd_smoke.py`，使用临时假 SDK 验证 launchd 接管、调用进程退出后存活、防休眠与复用，结束清理测试服务，不连接真实 ADB。需在允许 launchctl 和本地端口探测的 macOS 环境执行。

### 流水线配置

交接文件按所属需求存储：总体拆分、总结和全局输入使用 `requirements/handoffs/`；小需求的评审意见、人工反馈、续作上下文、失败任务原文及复审快照统一使用 `requirements/R-xxx/handoffs/`。同一目录内内容相同的交接只保存一份，即使调用方使用不同名称也复用已有路径。旧恢复记录及旧快照引用的路径继续读取，不自动搬迁或删除；这些交接和快照不是可直接清理的普通运行日志。

首次使用时，从示例文件创建不会提交到 Git 的本地配置：

```bash
# macOS
cp config/config.json.mac.example config/config.json
# Linux
cp config/config.json.linux.example config/config.json
```

Windows PowerShell 使用：

```powershell
Copy-Item config/config.json.win.example config/config.json
```

选择对应平台模板后，修改 `PROJECT_ROOT` 示例路径和仓库信息。模板仅区分外部工具的安装命令，不表示整条流水线已支持所有宿主：现有静态扫描工具安装仍依赖 Homebrew，模拟器自动启动脚本仍限 macOS；本次没有扩展这两项能力。Windows 模板需要 winget；Linux 模板需要 bash/curl，官方安装器可能更新用户 Shell 的 PATH 配置。

根据 `config/config.json` 中的角色配置，确保本机已安装并完成所用命令行工具的认证。可配置的工具为 `codex`、`claude`、`cursor`、`dsh` 和 `opencode`。然后初始化 Python 环境：

```bash
python -m venv .venv
source .venv/bin/activate  # Windows 使用 .venv\Scripts\activate
```

运行前编辑仓库根目录的 `config/config.json`，配置目标工程、仓库与各流水线角色使用的 Agent 工具。该文件已被 Git 忽略；需要更新默认模板时，请同步修改 `config/config.json.mac.example`、`config/config.json.win.example` 和 `config/config.json.linux.example`，保留各平台路径与安装命令的差异。`REPOS` 和 `AGENT_TYPES` 都是对象数组：

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

可选的外部 CLI 和全局 skills 也放在同一个配置文件中（省略时均为空数组，兼容旧配置）：

```json
{
  "EXTERNAL_CLI_TOOLS": [
    {
      "name": "lark-cli",
      "check": ["lark-cli", "--version"],
      "install": ["npx", "--yes", "@larksuite/cli@latest", "install"]
    }
  ],
  "EXTERNAL_SKILLS": [
    {
      "source": "larksuite/cli",
      "names": ["lark-shared", "lark-doc", "lark-wiki"],
      "agents": ["codex", "claude", "cursor"]
    }
  ]
}
```

`environment.py` 在启动 Agent 前按配置检查，缺失才安装，安装后再检查；每项可加 `"enabled": false` 跳过。CLI 的 `check`/`install` 必须是参数数组，不拼 Shell 字符串；检查命令应只检测安装/版本，不用登录状态检测，否则未登录可能被误判成需安装。命令不存在或检查非零时安装一次；检查超时只提示，不重装。检查默认最多 45 秒，可用 `check_timeout` 配置 1–300 秒；安装最多 300 秒，关闭 stdin，不等待交互。失败提示后继续流水线，不自动登录、授权或升级已通过检查的工具。

CLI 可选 `verify` 数组，每项包含 `command` 参数数组和 `contains` 非空字符串数组；在安装/版本检查通过后执行，要求退出码为 0 且输出包含全部指定内容，每项最多 15 秒。能力不足仅提示，不循环重装。可选 `path_env` 指定 `PANDA_PIPELINE_` 前缀的环境变量；全部检查通过才写入 `check` 命令的可执行文件绝对路径，失败/禁用为空，供 Agent 安全复用同一个工具。省略这些字段时仍是普通的检查、缺失安装流程。

外部 skills 通过 `npx --yes skills ls -g --json` 一次读取全局清单，按 `source`（GitHub `owner/repo`）、`names` 中全部必需项和每个目标 Agent 的关联判断。`agents` 支持 `codex`、`claude`、`cursor`、`opencode`，省略时默认前三项。缺失时执行 `npx --yes skills add <source> -y -g --agent <agents...>`，安装该来源的整套技能；`names` 是最低验收清单，不是安装筛选器，也不保证已同步远程新发布的所有技能。需要保证某项存在就在 `names` 中列出，不用单个哨兵代替全部必需项。安装后重新查询，检查仍失败不宣称成功。清单超时、非 JSON 或缺少来源信息时不盲目安装；不会每次联网枚举远程技能或自动更新。来源与命令参考 [skills CLI](https://github.com/vercel-labs/skills) 和 [Lark CLI](https://github.com/larksuite/cli)。

`skills add larksuite/cli` 安装的是技能说明，CLI 本体需单独配置；业务账号认证也另行处理。这里管理的是全局第三方技能，现有 `panda-pipeline-*` 技能仍从仓库 `skills/` 渲染并覆盖安装到业务项目。Android CLI 也使用同一外部 CLI 列表；具体安装来源和能力检查见上文及示例配置，不通过 npx 安装。

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
- 本地设备先复用；缺 SDK 工具、镜像和 AVD 时，由开发或 Code Review 调用统一 Python 脚本下载安装、创建并启动。命令带硬超时，不擅自覆盖已有设备或关闭他人实例。

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
