---
name: panda-pipeline-android-device-validation
description: 仅开发或 Code Review 的当前 Android AC 确需设备验证时使用，调用已安装脚本选择真机或准备模拟器。
---
# Android 设备验证

先读取 [设备启动与取证规范](references/device.md)。仅 Developer/Code Review 获授权使用；分析、需求审核、拆分、记忆整理、总结、回执补正不得启动设备。保留角色对源码/测试的写入边界。

设备就绪后，需要安装 APK、观察 UI 布局或截图时，按同一规范中的 Android CLI 章节使用环境已验证的工具；不可用则用 ADB，不自行安装或升级。Android CLI 不接管设备选择和模拟器启停。

本轮启动入口：

执行下面命令时，将工具的工作目录（cwd/workdir）设为当前 `SKILL.md` 所在目录；相对路径 `scripts/` 从这里解析，不从业务项目或 `references/` 目录解析。使用当前环境可用的 Python 3.11+，示例命令为 `python3`。业务项目、requirements 和报告路径都使用明确的绝对路径，含空格时正确引用。执行完脚本后，业务命令仍在业务项目目录运行。

```bash
__ANDROID_EMULATOR_COMMAND__ ensure --timeout 180 --prepare-timeout 1800
```

每轮实际设备验证先用上述不带 --serial/--avd 的命令重新选择，默认优先唯一在线真机，无在线真机才选择模拟器；不得仅因历史记录沿用模拟器 ID。多台同类候选或确需固定模拟器视觉基线时，按规范明确选择并说明理由。真机恢复后下一轮验证切回，正在执行的测试不中途切换。参数和后续设备 ID 必须按脚本实际回执使用。真机离线/未授权时降级，禁止无限等待；模拟器保持给后续任务复用，不擅自停止。脚本及依赖已随 skill 安装，不复制到业务源码、不寻找业务仓库同名脚本。平台与尺寸按当前需求输入确定，不照抄设计图像素作为设备参数。首审或证据失效时才补必要验证，不扩大复审范围。
