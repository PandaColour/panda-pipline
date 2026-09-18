## Android 模拟器统一入口

仅当前 Android AC 确需设备验证时使用。本入口只授权开发和 Code Review Agent；记忆整理、总结和回执补正不启动模拟器。其他平台按项目实际工具链验证。

```bash
__ANDROID_EMULATOR_COMMAND__ ensure --timeout 180 --prepare-timeout 1800
```

脚本路径相对本 skill 的 `SKILL.md` 所在目录；执行前将命令 cwd/workdir 设为该目录，不是当前 references/ 目录。不在业务工程中查找或复制脚本。真机和模拟器均通过 ensure 选择：每轮实际设备验证开始时重新执行 ensure，默认不带 --serial/--avd，优先选择唯一在线真机，即使同时有模拟器在线；没有在线真机才复用唯一在线模拟器。多台在线真机时用 --serial 明确选择真机；仅有多台在线模拟器时用 --serial <ADB设备ID> 或 --avd <AVD名称> 明确选择，两者互斥。显式指定设备优先于默认选择；仅因上一轮使用过模拟器，不得沿用它的 --serial/--avd 绕过真机优先。确需固定模拟器做视觉对照时，在已有开发/审查报告中说明理由后明确指定。真机离线、未授权或拔出时不等待，脚本立即降级到其他可用设备；没有可用设备则准备模拟器。模拟器 offline 时先报告，不重复创建。真机重新上线后，下一轮验证重新默认选择真机；已在执行的测试不因重新插入而中途切换设备。每次选择后，本轮安装、运行、截图使用同一份最终回执的设备 ID；中途断线则终止当前受影响测试、重新 ensure 并在新设备上重跑，分别记录设备与证据，不混称同一轮通过。不能继续用已失效的旧 ID。

仅项目明确限制 API 时加 --api；--device 是 AVD profile，不是 ADB ID，不照抄默认设备规格。需要匹配设备基线时，一起传 --width <设备像素宽px> --height <设备像素高px> --density <设备dpi>。先确定目标逻辑 viewport 与设备 density，再按 px=dp×dpi/160 换算；例如目标 375×812 dp、320 dpi，传 --width 750 --height 1624 --density 320，误传 375/812 得到的是 187.5×406 dp。设计图导出 1×/2× 只影响参考图像素，不决定设备规格，不能直接照抄画板数值或导出图像素，也不能把长滚动内容图高度当设备屏高。新建 AVD 使用这些规格；已连接设备尺寸不匹配仍复用并报告，已有未启动 AVD 不匹配则返回差异，不覆盖、不擅自新建其他实例。尺寸不同可继续功能验证，视觉对照另核逻辑宽度、字体缩放和系统栏；需要标准模拟器时明确指定 --avd，不修改真机的 wm size/density/font_scale。SDK 工具、Emulator、镜像和 AVD 缺失由 Python 自动准备，不手工创建；新建省略规格默认 API 35 / pixel_6，仅为工具默认值。

脚本检测宿主，首版仅支持 macOS；通过 launchd 启动模拟器，独立日志及 `caffeinate -i` 防空闲休眠随脚本管理的实例运行，锁屏/熄屏不要求退出。合盖、手动睡眠、注销及外部设备的防休眠不作保证。非 macOS 或脚本实际失败时记录错误，继续可控验证，不绕过脚本自行启动长驻进程。

只在退出码 0 且 JSON status=ready 后使用返回的 serial。回执 avd 是虚拟机名称，serial 是 ADB 设备 ID，二者不得混用；后续用回执 adb_path 和 -s <serial>，或直接使用 adb_args 数组，再追加 install/shell 等参数，不猜 emulator-5554。记录 device_type、api、screen（实际像素/dpi、logical_width_dp/height_dp、请求 target 及 target_logical_width_dp/height_dp、font_scale、matches_target、differences、warnings）、selection.fallback_reason、device_profile、created、source、managed、sleep_protection、日志路径及退出码；matches_target 只比较请求与实际设备 px/dpi；false 时先对照请求/实际逻辑尺寸和 warnings 排查单位误传，不因该值自动换机、等待或判 UI 失败，也不把 true 当 UI 还原通过。准备/下载单独受 --prepare-timeout 限制（默认 1800 秒），就绪等待由 --timeout 控制（默认 180 秒）；调用脚本的外层超时需覆盖锁等待、准备和启动（默认至少 3900 秒），工具支持时用异步执行和轮询收取脚本最终回执，不等模拟器进程退出。脚本失败读取 stage/error 和日志，serial=null 时禁止继续设备操作；缺 Java 或未接受 SDK 许可如实交接，不自行安装绕过或代用户确认许可。后续安装、启动应用、截图、拉日志和设备查询仍须硬超时（如 Python subprocess.run timeout=30），禁止无超时的 adb wait-for-device 或持续 logcat。

禁止自行使用 `emulator -avd`、nohup、`&`、`tee`、自建后台 Shell 或子代理启动模拟器。ensure 返回后不等待模拟器退出，验证成功/失败后均保留实例供后续需求复用；不执行 emu kill、pkill 或 stop，不关闭外部设备。停止由用户显式操作，不能把“未关闭模拟器”记为交付缺陷。Code Review 只为缺失/失效证据和直接回归执行必要设备验证，不因此重跑全量检查，仍不得修改源码/测试。

## Android CLI：部署与 UI 观察

`environment.py` 按 `EXTERNAL_CLI_TOOLS` 的 Android CLI 配置完成检查、必要安装与能力验证，成功后通过该条目的 `path_env` 环境变量 `PANDA_PIPELINE_ANDROID_CLI` 提供可执行文件绝对路径；空值或不可读取表示本轮不可用，直接使用已有 ADB 流程，不反复探测下载、不自行安装/升级。不能仅凭 PATH 中有 `android` 就认定可用。以参数数组调用该绝对路径，加 `--no-metrics`；子命令及参数以本机 `--help` 为准。SDK 使用 ensure 回执中的 `sdk` 路径，通过全局 `--sdk=<绝对路径>` 指定，避免操作另一套 SDK。

- **设备不变**：先完成 ensure，再对所有涉及设备的 CLI 命令显式传 `--device=<回执 serial>`。注意这里 `--device` 是 ADB ID，与 ensure 的 `--device`（AVD profile）不同。CLI 不支持当前操作的显式设备参数时，回退到回执 `adb_args`，不能让工具重新自动选设备；不调用 CLI 的 emulator create/start/stop 或 sdk install/update 绕过统一入口。
- **部署**：使用 `run --device=<serial> --apks=<APK绝对路径>` 安装并启动已有构建产物，它不代替 Gradle 构建。重复安装时按本机帮助使用 `--use-delta-install` 或 `install` 的增量能力；当前版本不支持或失败则使用回执 `adb_args` + `install -r`。记录安装退出码与构建标识，不把安装成功当成业务验证通过。
- **观察与操作**：用 `layout --full --device=<serial>` 获取完整布局，避免默认只显示交互元素而漏掉图标/正文。定位困难时使用 `screen capture --annotate --device=<serial> --output=<绝对路径>`，再用 `screen resolve --screenshot=<绝对路径> --string="input tap #编号"` 解析坐标，最终点击通过回执 `adb_args` 执行。每次操作后重新读取当前布局/截图，旧编号不可跨画面复用。
- **视觉证据**：标注截图只用于定位，验收仍采集无标注原图，并按既有 UI skill 对照设计，布局树不代替尺寸、位置、对齐与视觉检查。CLI 失败或不支持的控件可回退 ADB/UIAutomator 并保留失败原因；在已有开发/审查报告简记工具、设备、结果，不新增平行报告。
- **超时**：帮助/布局/截图/解析通常最多 30 秒，APK 部署最多 120 秒，调用均须设置硬超时。失败后确认原目标设备状态，仍在线则用 ADB 继续；已断线按上面的设备降级规则重新 ensure，不无限重试。不得自动运行 `android init` 或 `skills add/install` 安装另一套角色规则。
