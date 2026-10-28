"""
控制论增强 Demo —— 完整体验 7 大控制原理

复用 main_controlled.py 的场景，观察：
灵敏度分析表、反馈闭环轮次、多次采样投票、端到端质量评分。

运行：
    python examples/controlled_demo.py
"""

import sys
from pathlib import Path

# 允许直接运行 `python examples/controlled_demo.py`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storyloom.main_controlled import run_demo

if __name__ == "__main__":
    run_demo()
