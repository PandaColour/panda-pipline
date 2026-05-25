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

流水线启动后会自动初始化工作目录、克隆仓库并分发记忆文件到各阶段工作区。
