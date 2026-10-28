"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

统一模型提供商适配层

核心思路：不同提供商的 API 差异在这一层完全屏蔽，
上层（Agent/Flow）只看到统一的 CrewAI LLM 接口。

参考实践：
- AG2 框架的多模型配置模式
- EmaFusion 的提供商无关编排架构
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import yaml


@dataclass
class ModelSpec:
    """单个模型的完整规格"""

    provider: str
    model_name: str
    model_id: str                    # CrewAI / LiteLLM 格式的 model ID
    api_base: str
    api_key: Optional[str]
    cost_per_1k_tokens: float
    strengths: List[str]


class ModelRegistry:
    """
    模型注册中心：解析配置文件，维护所有可用模型的信息
    """

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            # 默认加载包内资源 src/storyloom/config/model_config.yaml
            config_path = str(
                Path(__file__).resolve().parent.parent
                / "config"
                / "model_config.yaml"
            )
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.models: Dict[str, ModelSpec] = {}
        self._parse_providers()

    def _parse_providers(self):
        """解析所有提供商和模型，统一注册"""
        for provider_name, provider_conf in self.config.get(
            "providers", {}
        ).items():
            api_base = provider_conf.get("api_base", "")
            env_key = provider_conf.get("env_key")
            api_key = os.getenv(env_key) if env_key else None

            for model_name, model_conf in provider_conf.get(
                "models", {}
            ).items():
                registry_key = f"{provider_name}.{model_name}"
                self.models[registry_key] = ModelSpec(
                    provider=provider_name,
                    model_name=model_name,
                    model_id=model_conf["model_id"],
                    api_base=api_base,
                    api_key=api_key,
                    cost_per_1k_tokens=model_conf.get(
                        "cost_per_1k_tokens", 0
                    ),
                    strengths=model_conf.get("strengths", []),
                )

    def get(self, registry_key: str) -> Optional[ModelSpec]:
        return self.models.get(registry_key)

    def is_available(self, registry_key: str) -> bool:
        """检查模型是否可用（有 API key 或是本地模型）"""
        spec = self.get(registry_key)
        if not spec:
            return False
        if spec.provider == "ollama":
            return True  # 本地模型假设可用
        return spec.api_key is not None and spec.api_key != ""

    def list_available(self) -> List[str]:
        return [k for k in self.models if self.is_available(k)]
