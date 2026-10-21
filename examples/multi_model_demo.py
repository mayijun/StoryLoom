"""
多模型 Demo —— 配置多个 API Key 后效果最佳

该脚本复用 main.py 中的完整演示场景（3 个角色 + 2 条预埋伏笔），
重点观察"不同 Agent 使用不同模型"的分配表与降级行为。

运行：
    python examples/multi_model_demo.py
"""

import sys
from pathlib import Path

# 允许直接运行 `python examples/multi_model_demo.py`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import run_demo

if __name__ == "__main__":
    run_demo()
