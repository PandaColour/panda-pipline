# Panda Pipeline

多 Agent 协作的软件开发流水线，涵盖需求分析、代码开发、测试和审查阶段。

## 环境初始化

```bash
# 1. 创建 Python 虚拟环境
python -m venv .venv

# 2. 激活虚拟环境 (Windows)
.venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt
```

## 运行

```bash
python main.py
```

流水线启动后会自动初始化工作目录并克隆仓库。所有角色在同一个工程根目录中运行，
每个 Agent 通过各自的 CLI 会话 ID 保持独立对话上下文。
