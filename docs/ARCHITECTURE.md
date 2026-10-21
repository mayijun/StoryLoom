# 织章 StoryLoom 架构文档

> 本文档是项目设计结论的落地说明，对应 `config/`、`llm/`、`agents/`、`assets/`、
> `memory/`、`control/`、`flow/`、`media/` 各层实现。

---

## 1. 分层架构

```
┌──────────────────────────────────────────────────────────────┐
│ Layer 7  Web 界面层（规划）                                   │
│ FastAPI + Streamlit：项目管理 / 资产编辑 / 生成 / 历史回溯      │
├──────────────────────────────────────────────────────────────┤
│ Layer 6  多模态渲染层                media/render_adapter.py │
│ RenderAdapter → TextOnly / TTS / Image / Video               │
├──────────────────────────────────────────────────────────────┤
│ Layer 5  控制论管控层                control/                │
│ 灵敏度分析 | 反馈闭环 | 统计滤波 | 质量闸门 | 人机结合         │
├──────────────────────────────────────────────────────────────┤
│ Layer 4  工作流编排层                flow/                   │
│ SceneGenerationFlow / ControlledSceneFlow（CrewAI Flow）      │
├──────────────────────────────────────────────────────────────┤
│ Layer 3  Agent 层                   agents/factory.py       │
│ Director | Protagonist | Ensemble | Surprise | Foreshadowing │
│ Consistency | Prose | Outline                                │
├──────────────────────────────────────────────────────────────┤
│ Layer 2  记忆层 / 资产层      memory/manager.py  assets/      │
│ CoreMemory (prompt) + VectorMemory (RAG) | Character/Location │
│ Foreshadowing / SurpriseProposal                              │
├──────────────────────────────────────────────────────────────┤
│ Layer 1  模型路由层           llm/providers.py  llm/router.py │
│ DeepSeek | OpenAI | Anthropic | Ollama + 自动降级             │
├──────────────────────────────────────────────────────────────┤
│ Layer 0  项目层                      assets/models.py        │
│ NovelProject：资产库 / 记忆实例 / 场景计数 / 伏笔状态          │
└──────────────────────────────────────────────────────────────┘
```

每层只依赖下一层的接口，因此替换模型、增加渲染器、接入 Web 界面
都不需要改动已有 Agent 与 Flow 的核心逻辑。

---

## 2. Agent 角色设计

| Agent | 职责 | 数量策略 | 默认模型 |
|-------|------|---------|---------|
| 导演 DirectorAgent | 输出"场景意图包"做间接引导，不替角色说话 | 每个场景 1 个 | deepseek.v4pro |
| 主角 ProtagonistAgent | 独立人格、动机、记忆 | 1 个 primary 角色 = 1 实例 | anthropic.claude_sonnet |
| 群演 EnsembleAgent | 承载多个次要角色，按任务切换人格 | 每场景 1 个（可装 N 个角色） | deepseek.flash |
| 意外 SurpriseAgent | 提出"合理但未被预期"的事件提案 | 每场景 1 个 | anthropic.claude_sonnet |
| 伏笔 ForeshadowingAgent | 管理伏笔种植/强化/揭示/回收/颠覆 | 每场景 1 个 | deepseek.v4pro |
| 一致性 ConsistencyAgent | 校验人设、时间线、设定冲突 | 每场景 1 个（可控多次采样） | openai.gpt4o |
| 润色 ProseAgent | 行动日志 → 文学化正文 | 每场景 1 个 | anthropic.claude_sonnet |
| 大纲 OutlineAgent | 卷→章→场景结构规划 | 按项目 | deepseek.v4pro |

### 关键设计决策

1. **导演只做间接引导**：导演输出的是结构化 JSON（戏剧目标、冲突、情绪曲线、
   禁止事项），不输出正文，也不指定角色具体动作。角色 Agent 决定怎么演，
   保留涌现感。
2. **重要角色与次要角色异构**：`importance_tier` 决定实例化方式，
   既保证主角的独立性，又压缩群演成本。
3. **一致性检测强制结构化**：推理模型在复杂结构化输出上不稳定，
   所有检测结果都按 `ConsistencyReport` 解析，失败时保守放行。

---

## 3. 场景生成 Pipeline

```
SurpriseAgent（意外提案，可控冷却期）
        ↓
ForeshadowingAgent（伏笔操作建议 + 超时预警）
        ↓
DirectorAgent（综合裁决，产出场景意图包）
        ↓
RAG 检索（按资产类型取需要时才取的背景）
        ↓
Actor Crew（主角独立实例 + 群演共享实例）
        ↓
ConsistencyAgent（冲突则回退重试，最多 N 次）
        ↓
ProseAgent（统一文风转写正文）
        ↓
Memory 更新 + 伏笔状态机推进 + 端到端质量评估
```

对应实现：
- 基础版：[scene_flow.py](../flow/scene_flow.py)
- 控制论版：[controlled_scene_flow.py](../flow/controlled_scene_flow.py)

---

## 4. 资产层与项目层

```python
NovelProject
├── project_id / title / style
├── characters: List[CharacterAsset]     # 人设卡 + importance_tier
├── locations: List[LocationAsset]       # 场景环境
├── foreshadowings: List[Foreshadowing]  # 伏笔状态机
├── scene_count / surprise_cooldown      # 节奏控制
└── last_major_surprise_scene
```

- 资产的结构化字段直接进 prompt，自由文本字段可自动 embedding 入库。
- 多项目隔离在 `NovelProject` 层完成，每个项目有独立的向量库 namespace
  （`memory_store/{project_id}`）。
- 资产可以"启用/禁用"，实现"这一幕只有这几个资产参与"的动态组合。

---

## 5. 记忆层

```
CoreMemory（直接拼入 prompt）
├── 当前场景状态（地点、在场角色）
├── 最近 2~3 个场景摘要（滚动压缩）
└── 导演当前指令包

SimpleRAGMemory（按需检索）
├── 世界观设定 / 角色背景 / 场景细节
├── ChromaDB 持久化，按项目隔离
└── 未安装 chromadb 时退化为关键词检索
```

设计原则：**关键记忆直接给，背景记忆按需取**。
把所有设定一次性塞进 prompt 会稀释模型注意力，反而降低一致性。

---

## 6. 多模态预留

`ProseAgent` 的产出可先转成结构化中间表示：

```json
{
  "scene_id": "scene_03",
  "speaker": "林夏",
  "dialogue": "你确定？",
  "narration": "她的手指微微收紧",
  "emotion_tag": "tension",
  "camera_hint": "close-up"
}
```

未来接入 TTS / Seedance / 图片生成时，只需在 `media/render_adapter.py`
新增一个 `RenderAdapter` 子类，Agent 与 Flow 逻辑不变。

**这是补救成本最高的一处设计，所以现在就定下来。**

---

## 7. 扩展路线

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1 | 多 Agent 协作、多模型路由、伏笔管理、控制论管控、分层记忆 | ✅ |
| Phase 2 | Web 界面、多项目管理、章节串联、历史回溯、SQLite 持久化 | 🔲 |
| Phase 3 | TTS 语音小说、插图、短剧视频 | 🔲 |
| Phase 4 | 交互式分支叙事、多人协作、游戏引擎集成 | 🔲 |
