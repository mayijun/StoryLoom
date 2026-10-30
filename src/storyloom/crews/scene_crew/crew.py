"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

场景生成 Crew（CrewAI 官方约定版）

- 8 个 Agent 的 role/goal/backstory 持久化在数据库（agent_configs 表），
  由 DbConfig 描述符接入 @CrewBase 的 self.agents_config
- 标准任务序列持久化在数据库（task_configs 表），
  由 self.tasks_config 读取、self.crew() 按 agent_key/context_keys 装配
- 同级 config/*.yaml 仅作为首次运行的种子数据，数据库是唯一事实来源
- 通过 AgentModelRouter 为每个 Agent 注入最适合的 LLM
  （router 为 None 时使用 CrewAI 默认 LLM）
- protagonist / ensemble / prose 三个 Agent 由 Flow 按资产数据动态生成，
  配置中的 {name}/{persona}/{motivation}/{names}/{brief}/{style}
  占位符会被代码填充（_dynamic_config）

Agent 角色划分（8 类）：
- ProtagonistAgent   重要角色，1 角色 = 1 实例
- EnsembleAgent      "群演"，1 实例承载 N 个次要角色，压缩成本
- DirectorAgent      导演，只输出"场景意图包"做间接引导
- OutlineAgent       大纲规划
- SurpriseAgent      意外事件提案
- ForeshadowingAgent 伏笔全生命周期管理
- ConsistencyAgent   一致性检测（强制结构化输出）
- ProseAgent         润色 / 叙事者
"""

from typing import Any, List, Optional, Tuple

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew

from storyloom.db import DbConfig, get_repository
from storyloom.llm.router import AgentModelRouter
from storyloom.models import CharacterAsset


@CrewBase
class SceneCrew:
    """场景生成 Crew：Agent / Task 定义来自数据库 + 模型路由注入 LLM"""

    # 覆盖 @CrewBase 的 YAML 加载：实例访问时从数据库读取配置
    agents_config = DbConfig("agents")
    tasks_config = DbConfig("tasks")

    def __init__(self, router: Optional[AgentModelRouter] = None):
        self.router = router          # AgentModelRouter，可为 None（用 CrewAI 默认 LLM）
        self._summary: List[Tuple[str, str]] = []
        # (agent_key, model_key) 记录，供 print_creation_summary

    # ---------------- 内部工具 ----------------

    def _llm(self, key: str, label: Optional[str] = None):
        """按角色从路由器获取 LLM；router 为 None 时返回 None（用 CrewAI 默认 LLM）"""
        if self.router is None:
            return None
        llm, model_key = self.router.get_llm_for_role(key)
        agent_key = label or key
        if not any(k == agent_key for k, _ in self._summary):
            self._summary.append((agent_key, model_key))
        return llm

    def _dynamic_config(self, key: str, **values) -> dict:
        """复制数据库中的配置并用实际资产数据填充占位符"""
        config = dict(self.agents_config[key])
        for field in ("role", "goal", "backstory"):
            if isinstance(config.get(field), str):
                config[field] = config[field].format(**values)
        return config

    def agent_for_key(self, key: str, **values: Any) -> Agent:
        """
        按 Agent key 创建实例。

        优先使用本类中带 @agent 的工厂方法（可注入角色专属的模型/参数）；
        数据库中新增、但没有对应工厂方法的 key，则回退为通用 Agent。
        """
        factory = getattr(self, key, None)
        if callable(factory) and getattr(factory, "is_agent", False):
            return factory(**values)

        config = self.agents_config.get(key)
        if config is None:
            raise KeyError(f"数据库中没有 Agent 定义: {key}")
        if values:
            config = self._dynamic_config(key, **values)
        return Agent(config=config, llm=self._llm(key), verbose=False)

    # ---------------- 角色类 Agent ----------------

    @agent
    def protagonist(self, char: Optional[CharacterAsset] = None) -> Agent:
        """主角 Agent：1 角色 = 1 实例，用最有创意表现力的模型"""
        if char is None:
            return Agent(
                config=self.agents_config["protagonist"],
                llm=self._llm("protagonist"),
                verbose=True,
            )
        llm = self._llm("protagonist", label=f"protagonist:{char.name}")
        return Agent(
            config=self._dynamic_config(
                "protagonist",
                name=char.name,
                persona=char.persona,
                motivation=char.motivation,
            ),
            llm=llm,
            verbose=False,
        )

    @agent
    def ensemble(self, characters: Optional[List[CharacterAsset]] = None) -> Agent:
        """群演 Agent：多个次要角色共享一个实例，用便宜模型"""
        if characters is None:
            return Agent(
                config=self.agents_config["ensemble"],
                llm=self._llm("ensemble"),
                verbose=True,
            )
        names = ", ".join(c.name for c in characters)
        brief = "\n".join(
            f"  - {c.name}: {c.persona}（动机: {c.motivation}）"
            for c in characters
        )
        llm = self._llm("ensemble", label=f"ensemble:{names}")
        return Agent(
            config=self._dynamic_config("ensemble", names=names, brief=brief),
            llm=llm,
            verbose=False,
        )

    # ---------------- 全局类 Agent ----------------

    @agent
    def director(self) -> Agent:
        """导演 Agent：用推理能力最强的模型，只产出结构化场景意图包"""
        return Agent(
            config=self.agents_config["director"],
            llm=self._llm("director"),
            verbose=True,
        )

    @agent
    def outline(self) -> Agent:
        """大纲 Agent：章节级 / 卷级结构规划，需要长上下文"""
        return Agent(
            config=self.agents_config["outline"],
            llm=self._llm("outline"),
            verbose=True,
        )

    @agent
    def consistency(self) -> Agent:
        """
        一致性检测 Agent：用结构化输出最稳定的模型

        这里的模型选择至关重要：
        DeepSeek 推理模型在复杂结构化输出上不够稳定，
        而 GPT-4o 的工具调用 / JSON 模式最可靠
        """
        return Agent(
            config=self.agents_config["consistency"],
            llm=self._llm("consistency"),
            verbose=True,
        )

    @agent
    def prose(self, style: Optional[str] = None) -> Agent:
        """润色 Agent：用文学表现力最强的模型"""
        if style is None:
            return Agent(
                config=self.agents_config["prose"],
                llm=self._llm("prose"),
                verbose=True,
            )
        llm = self._llm("prose", label=f"prose:{style}")
        return Agent(
            config=self._dynamic_config("prose", style=style),
            llm=llm,
            verbose=False,
        )

    # ---------------- 新增：意外 / 伏笔 Agent ----------------

    @agent
    def surprise(self) -> Agent:
        """
        意外 Agent：提出"合理但未被预期"的事件提案

        学术依据：
        - StoryWriter（清华 KEG）: surprise 是六大评估指标之一
        - ACL 2025: 意外元素应有意为之，服务于故事
        - Elser AI: "可控的随机性"——管理何时何处引入意外

        模型选择：用有创意的模型（如 Claude），因为需要跳出常规思维
        """
        return Agent(
            config=self.agents_config["surprise"],
            llm=self._llm("surprise"),
            verbose=True,
        )

    @agent
    def foreshadowing(self) -> Agent:
        """
        伏笔 Agent：管理伏笔的种植、强化、回收全生命周期

        学术依据：
        - CreAgentive: 知识图谱式语义三元组强制执行伏笔约束
        - Showrunner Agents: "戏剧算子"程序化注入伏笔操作
        - 长篇写作的注意力稀释导致早期伏笔被遗忘

        模型选择：用推理能力强的模型，因为需要维护复杂的状态追踪
        """
        return Agent(
            config=self.agents_config["foreshadowing"],
            llm=self._llm("foreshadowing"),
            verbose=True,
        )

    # ---------------- 标准任务序列 ----------------
    # 任务完全由数据库 task_configs 表驱动：position 决定顺序，
    # agent_key 决定执行者，context_keys 决定上游任务的输出作为上下文。
    # 因此不再定义 @task 方法——新增 / 删除 / 停用任务只需改数据库。

    @crew
    def crew(self) -> Crew:
        """按数据库中的任务顺序与依赖关系装配标准 Crew"""
        tasks: List[Task] = []
        built: dict[str, Task] = {}

        for meta in get_repository().load_task_meta():
            config = self.tasks_config.get(meta["key"])
            if config is None:
                continue
            kwargs: dict[str, Any] = {"config": dict(config)}
            if meta.get("agent_key"):
                kwargs["agent"] = self.agent_for_key(meta["agent_key"])
            context = [
                built[key]
                for key in meta.get("context_keys", [])
                if key in built
            ]
            if context:
                kwargs["context"] = context
            task = Task(**kwargs)
            built[meta["key"]] = task
            tasks.append(task)

        agents = [self.agent_for_key(key) for key in self.agents_config]
        return Crew(
            agents=agents,
            tasks=tasks,
            process=Process.sequential,
            verbose=True,
        )

    def print_creation_summary(self):
        """打印已创建 Agent 的模型分配摘要"""
        print("\n📋 Agent 创建摘要：")
        for agent_id, model_key in self._summary:
            print(f"  {agent_id:35s} → {model_key}")
