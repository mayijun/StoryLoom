"""
Crew 的 Deterministic Agents 包。

这些 Agent 是纯代码、不调用 LLM、永远可用的 Crew 成员：
- GM (GameMaster): 世界裁决
- 后续: ConsistencyChecker / ModerationGate / IntentRouter

GM 从 world/ 迁入此处后，world/game_master.py 保留为兼容转发层。
"""
