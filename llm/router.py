"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

模型路由器：根据 Agent 角色自动选择最优模型

核心逻辑：
1. 先尝试 primary 模型
2. 若不可用（缺 API key 等），自动降级到 fallback
3. 若都不可用，使用任意可用模型
4. strategy.mode 可在 balanced / cost_optimized / quality_first 间切换
"""

from typing import Optional, Tuple

from crewai import LLM

from llm.providers import ModelRegistry, ModelSpec


class AgentModelRouter:
    """
    模型路由器

    这实现了多 Agent 系统的主流设计模式：
    "每个 Agent 都有专门的角色、自己的系统提示，甚至自己的 LLM 模型配置"
    """

    def __init__(self, registry: ModelRegistry):
        self.registry = registry
        self.config = registry.config
        self.mapping = self.config.get("agent_model_mapping", {})
        self.strategy = self.config.get("strategy", {})
        self.mode = self.strategy.get("mode", "balanced")

    def _pick_key(self, primary_key: str, fallback_key: str) -> str:
        """按策略在 primary / fallback 之间做选择，并处理降级"""
        available = [
            k for k in (primary_key, fallback_key)
            if self.registry.is_available(k)
        ]

        if available:
            if self.mode == "cost_optimized":
                return min(
                    available,
                    key=lambda k: self.registry.get(k).cost_per_1k_tokens,
                )
            return available[0]

        any_available = self.registry.list_available()
        if any_available:
            return any_available[0]

        raise RuntimeError(
            "没有任何可用模型！请检查 .env 中的 API Key 配置"
        )

    def get_llm_for_role(self, role: str) -> Tuple[LLM, str]:
        """
        为指定角色返回 CrewAI LLM 实例 + 实际选择的模型标识

        Args:
            role: Agent 角色标识
                  (director / protagonist / ensemble / consistency /
                   prose / outline / surprise / foreshadowing)

        Returns:
            (LLM 实例, 模型标识字符串)
        """
        role_conf = self.mapping.get(role, {})
        primary_key = role_conf.get("primary", "deepseek.flash")
        fallback_key = role_conf.get("fallback", "deepseek.flash")
        temperature = role_conf.get("temperature", 0.8)

        chosen_key = self._pick_key(primary_key, fallback_key)
        if chosen_key != primary_key:
            print(
                f"  ⚠️ [{role}] 首选模型 {primary_key} 不可用或不适用，"
                f"使用 {chosen_key}"
            )

        spec: ModelSpec = self.registry.get(chosen_key)
        if spec is None:
            raise RuntimeError(
                f"模型 {chosen_key} 未注册，请检查 model_config.yaml"
            )

        # 构建 CrewAI LLM —— LiteLLM 统一格式
        llm_kwargs = {
            "model": spec.model_id,
            "temperature": temperature,
        }
        if spec.api_key:
            llm_kwargs["api_key"] = spec.api_key
        if spec.api_base:
            llm_kwargs["base_url"] = spec.api_base

        return LLM(**llm_kwargs), chosen_key

    def print_assignment_table(self):
        """打印当前的模型分配表，方便调试"""
        print("\n" + "=" * 70)
        print(f"🤖 Agent → 模型分配表（策略: {self.mode}）")
        print("=" * 70)
        for role, conf in self.mapping.items():
            _, chosen = self.get_llm_for_role(role)
            reason = conf.get("reason", "")
            status = "✅" if chosen == conf.get("primary") else "⬇️降级"
            print(f"  {role:15s} → {chosen:28s} {status}  ({reason})")
        print("=" * 70 + "\n")
