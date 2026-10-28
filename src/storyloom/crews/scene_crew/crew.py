"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

场景生成 Crew（CrewAI 官方约定版）

- 8 个 Agent 的 role/goal/backstory 定义在同级 config/agents.yaml，
  由 @CrewBase 自动加载为 self.agents_config
- 标准任务序列定义在同级 config/tasks.yaml，由 @task 方法装配
- 通过 AgentModelRouter 为每个 Agent 注入最适合的 LLM
  （router 为 None 时使用 CrewAI 默认 LLM）
- protagonist / ensemble / prose 三个 Agent 由 Flow 按资产数据动态生成，
  YAML 中的 {name}/{persona}/{motivation}/{names}/{brief}/{style}
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

from typing import List, Optional, Tuple

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from storyloom.llm.router import AgentModelRouter
from storyloom.models import CharacterAsset


@CrewBase
class SceneCrew:
    """场景生成 Crew：8 个 Agent，YAML 定义角色 + 模型路由注入 LLM"""

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
        """复制 YAML 配置并用实际资产数据填充占位符"""
        config = dict(self.agents_config[key])
        for field in ("role", "goal", "backstory"):
            if isinstance(config.get(field), str):
                config[field] = config[field].format(**values)
        return config

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

    # ---------------- 标准任务序列（给 crewai CLI / @crew 用） ----------------
    # 注意：agent / context 在此显式装配，而不写在 tasks.yaml 中，
    # 避免 CrewBase 在实例化时立即物化全部 Agent（保持无 Key 环境可导入）。

    @task
    def surprise_proposal(self) -> Task:
        return Task(config=self.tasks_config["surprise_proposal"], agent=self.surprise())

    @task
    def foreshadowing_ops(self) -> Task:
        return Task(
            config=self.tasks_config["foreshadowing_ops"],
            agent=self.foreshadowing(),
        )

    @task
    def director_plan(self) -> Task:
        return Task(
            config=self.tasks_config["director_plan"],
            agent=self.director(),
            context=[self.surprise_proposal(), self.foreshadowing_ops()],
        )

    @task
    def actor_interaction(self) -> Task:
        return Task(
            config=self.tasks_config["actor_interaction"],
            agent=self.protagonist(),
            context=[self.director_plan()],
        )

    @task
    def consistency_check(self) -> Task:
        return Task(
            config=self.tasks_config["consistency_check"],
            agent=self.consistency(),
            context=[self.actor_interaction()],
        )

    @task
    def prose_polish(self) -> Task:
        return Task(
            config=self.tasks_config["prose_polish"],
            agent=self.prose(),
            context=[self.consistency_check()],
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )

    def print_creation_summary(self):
        """打印已创建 Agent 的模型分配摘要"""
        print("\n📋 Agent 创建摘要：")
        for agent_id, model_key in self._summary:
            print(f"  {agent_id:35s} → {model_key}")
