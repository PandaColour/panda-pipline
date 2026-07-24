# Panda Pipeline

## 工程目标

快速验证多 Agent 流水线，执行 Codex、Claude、Cursor 三种主流智能体工具，协作完成需求分析、开发、测试、审查与记忆整理。

## 环境初始化和使用

确保本机已安装并登录 `codex`、`claude`、`cursor` 命令行工具，然后初始化 Python 环境：

```bash
python -m venv .venv
source .venv/bin/activate  # Windows 使用 .venv\Scripts\activate
```

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

## 欢迎交流学习

欢迎交流学习：panda.colour@qq.com
