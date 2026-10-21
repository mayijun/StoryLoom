"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

Agent 工厂：根据资产定义和模型路由器动态创建各类 Agent
每个 Agent 在创建时自动获得最适合它的 AI 模型

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

from typing import List

from crewai import Agent

from assets.models import CharacterAsset
from llm.router import AgentModelRouter


class AgentFactory:
    """
    统一的 Agent 创建工厂

    核心设计：
    - 所有 Agent 通过此工厂创建，确保模型分配策略统一
    - 工厂持有 router 引用，Agent 本身不关心用的是什么模型
    - 每个 Agent 都有专门的角色、自己的系统提示和自己的 LLM 配置
    """

    def __init__(self, router: AgentModelRouter):
        self.router = router
        self._created_agents = []      # 跟踪已创建 Agent，便于调试

    # ---------------- 角色类 Agent ----------------

    def create_protagonist(self, char: CharacterAsset) -> Agent:
        """主角 Agent：1 角色 = 1 实例，用最有创意表现力的模型"""
        llm, model_key = self.router.get_llm_for_role("protagonist")
        agent = Agent(
            role=f"角色扮演者-{char.name}",
            goal=(
                f"完全代入{char.name}，基于其动机做出真实、"
                f"符合人设的言行反应"
            ),
            backstory=(
                f"你就是{char.name}。\n"
                f"性格: {char.persona}\n"
                f"当前动机: {char.motivation}\n"
                f"你只知道自己能合理知道的信息，不能预知剧情走向。"
            ),
            llm=llm,
            verbose=False,
            allow_delegation=False,
        )
        self._created_agents.append(
            (f"protagonist:{char.name}", model_key)
        )
        return agent

    def create_ensemble(self, characters: List[CharacterAsset]) -> Agent:
        """群演 Agent：多个次要角色共享一个实例，用便宜模型"""
        llm, model_key = self.router.get_llm_for_role("ensemble")
        names = ", ".join(c.name for c in characters)
        brief = "\n".join(
            f"  - {c.name}: {c.persona}（动机: {c.motivation}）"
            for c in characters
        )
        agent = Agent(
            role="群像角色代理",
            goal=(
                "根据场景需要，依次代入以下任一次要角色"
                "做出简短、符合人设的反应"
            ),
            backstory=(
                f"你同时负责扮演这些次要角色: {names}\n"
                f"人设简表:\n{brief}\n"
                f"每次只代入任务中指定的那一个角色说话行动。"
            ),
            llm=llm,
            verbose=False,
            allow_delegation=False,
        )
        self._created_agents.append((f"ensemble:{names}", model_key))
        return agent

    # ---------------- 全局类 Agent ----------------

    def create_director(self) -> Agent:
        """导演 Agent：用推理能力最强的模型，只产出结构化场景意图包"""
        llm, model_key = self.router.get_llm_for_role("director")
        agent = Agent(
            role="导演",
            goal=(
                "产出'场景意图包'：戏剧目标、冲突/伏笔、"
                "情绪曲线、禁止事项。整合意外和伏笔提案。"
            ),
            backstory=(
                "你是幕后导演，只给方向不替角色说话。"
                "你要综合 SurpriseAgent 和 ForeshadowingAgent 的建议，"
                "决定本场景是否采纳意外事件或伏笔操作。"
                "输出必须是结构化 JSON，不要输出小说正文。"
            ),
            llm=llm,
            verbose=False,
        )
        self._created_agents.append(("director", model_key))
        return agent

    def create_outline_agent(self) -> Agent:
        """大纲 Agent：章节级 / 卷级结构规划，需要长上下文"""
        llm, model_key = self.router.get_llm_for_role("outline")
        agent = Agent(
            role="故事架构师",
            goal=(
                "规划卷→章→场景的结构，明确每一幕的戏剧功能，"
                "为导演和角色提供稳定的骨架"
            ),
            backstory=(
                "你是结构主义者，擅长把故事拆解成清晰的节拍。"
                "输出结构化 JSON 大纲，不写具体正文。"
            ),
            llm=llm,
            verbose=False,
        )
        self._created_agents.append(("outline", model_key))
        return agent

    def create_consistency_checker(self) -> Agent:
        """
        一致性检测 Agent：用结构化输出最稳定的模型

        这里的模型选择至关重要：
        DeepSeek 推理模型在复杂结构化输出上不够稳定，
        而 GPT-4o 的工具调用 / JSON 模式最可靠
        """
        llm, model_key = self.router.get_llm_for_role("consistency")
        agent = Agent(
            role="一致性检测员",
            goal=(
                "检查本场景内容是否与已知人设、时间线、"
                "世界观设定冲突，输出结构化冲突报告"
            ),
            backstory=(
                "你是严格的设定审校员，只关注逻辑一致性，不评价文笔。"
            ),
            llm=llm,
            verbose=False,
        )
        self._created_agents.append(("consistency", model_key))
        return agent

    def create_prose_writer(self, style: str) -> Agent:
        """润色 Agent：用文学表现力最强的模型"""
        llm, model_key = self.router.get_llm_for_role("prose")
        agent = Agent(
            role="润色叙事者",
            goal=(
                f"将角色行动与对话记录，用'{style}'文风"
                f"改写成正式小说正文"
            ),
            backstory=(
                "你是本书唯一的叙事声音，负责把分散的角色行动日志"
                "揉合成连贯、文学化的叙事文本，像隐形在场的作者。"
            ),
            llm=llm,
            verbose=False,
        )
        self._created_agents.append(("prose", model_key))
        return agent

    # ---------------- 新增：意外 / 伏笔 Agent ----------------

    def create_surprise_agent(self) -> Agent:
        """
        意外 Agent：提出"合理但未被预期"的事件提案

        学术依据：
        - StoryWriter（清华 KEG）: surprise 是六大评估指标之一
        - ACL 2025: 意外元素应有意为之，服务于故事
        - Elser AI: "可控的随机性"——管理何时何处引入意外

        模型选择：用有创意的模型（如 Claude），因为需要跳出常规思维
        """
        llm, model_key = self.router.get_llm_for_role("surprise")
        agent = Agent(
            role="意外事件策划师",
            goal=(
                "在合理范围内提出令人意外但可追溯的事件提案。"
                "你不是制造混乱，而是在'预期之外、情理之中'的"
                "方向上丰富故事。每个提案必须附带'为什么合理'的论证"
                "和'对后续剧情的影响'说明。"
            ),
            backstory=(
                "你是故事中的'命运之手'。你的工作是阅读当前场景状态，"
                "找到那些'差一点就会被忽略但其实很有戏剧张力'的可能性。\n\n"
                "你提出的意外必须满足四个约束：\n"
                "1. 合理性：不违反已建立的世界观规则\n"
                "2. 可追溯性：读者事后能感叹'原来如此'\n"
                "3. 后果性：必须对后续剧情产生实质影响\n"
                "4. 节制性：不是每个场景都需要意外，"
                "有时'不发生意外'就是最好的选择\n\n"
                "意外类型包括：角色意外、信息意外、环境意外、"
                "关系意外、时间意外。\n"
                "输出必须是 JSON 格式的意外事件提案，"
                "或明确输出'本场景不需要意外'。"
            ),
            llm=llm,
            verbose=False,
        )
        self._created_agents.append(("surprise", model_key))
        return agent

    def create_foreshadowing_agent(self) -> Agent:
        """
        伏笔 Agent：管理伏笔的种植、强化、回收全生命周期

        学术依据：
        - CreAgentive: 知识图谱式语义三元组强制执行伏笔约束
        - Showrunner Agents: "戏剧算子"程序化注入伏笔操作
        - 长篇写作的注意力稀释导致早期伏笔被遗忘

        模型选择：用推理能力强的模型，因为需要维护复杂的状态追踪
        """
        llm, model_key = self.router.get_llm_for_role("foreshadowing")
        agent = Agent(
            role="伏笔管理大师",
            goal=(
                "管理故事中所有伏笔的生命周期。你的职责包括：\n"
                "1. PLANT：在合适时机提议埋下新伏笔\n"
                "2. REINFORCE：在后续场景中安排不经意的暗示/强化\n"
                "3. ACTIVATE：在剧情高潮前触发伏笔揭示\n"
                "4. RESOLVE：确保伏笔被妥善回收\n"
                "5. SUBVERT：配合 SurpriseAgent，将伏笔引向意外方向\n"
                "6. ALERT：当某伏笔超过容忍期未被提及时发出提醒"
            ),
            backstory=(
                "你是故事的'织网者'，维护一张隐形的因果之网。\n\n"
                "核心原则：\n"
                "- 每条伏笔都必须有明确的生命终点"
                "（RESOLVED 或 SUBVERTED）\n"
                "- 伏笔不能永远沉睡：超过设定的场景数未提及就必须提醒\n"
                "- 好的伏笔应该让读者在回收时感到'恍然大悟'\n"
                "- 伏笔密度要适中：同时活跃的伏笔不超过 5 条\n\n"
                "输出必须是 JSON 格式，包含建议的伏笔操作列表。"
            ),
            llm=llm,
            verbose=False,
        )
        self._created_agents.append(("foreshadowing", model_key))
        return agent

    def print_creation_summary(self):
        """打印已创建 Agent 的模型分配摘要"""
        print("\n📋 Agent 创建摘要：")
        for agent_id, model_key in self._created_agents:
            print(f"  {agent_id:35s} → {model_key}")
