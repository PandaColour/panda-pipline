import os

# Source repo root (where this config lives)
SOURCE_REPO_DIR = os.path.dirname(os.path.abspath(__file__))
SYSTEM_PROMPT_DIR = os.path.join(SOURCE_REPO_DIR, "system-prompt")

# 代码静态扫描（detekt）规则文件：pipeline.py 与 break_pipeline.py 共用同一份配置，
# 两个模块彼此独立，只共同依赖本配置模块。
STATIC_ANALYSIS_DIR = os.path.join(SOURCE_REPO_DIR, "static-analysis")
DETEKT_CONFIG_PATH = os.path.join(STATIC_ANALYSIS_DIR, "detekt.yml")
