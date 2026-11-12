# 织章 StoryLoom 架构

> 本文档描述「双模式 + 基座 + 扩展」的总体架构。
> 进度与差距见 [MVP.md](MVP.md)。

---

## 1. 两种模式，一个基座

| | 导演模式 | 游戏 / 扮演模式 |
|---|---|---|
| 用户 | 作者 | 玩家 |
| 输入 | 场景指令 / 章节意图 | 角色行动 / 选择 |
| 主导扩展 | `skill`：类型知识、结构模板、文风 | `mod`：地图、时间、数值、系统 |
| 权限 | 可改写事实（`FactOverride`，审计 + 快照） | 自由文本默认进入叙事；扩展可添加行动裁决 |
| 产物 | 小说章节 | 可交互的文字世界 |

两种模式共用同一套世界状态、裁决、渲染与扩展机制。两种模式的叙事链已合并进
统一叙事引擎 `NarrativeEngine`（`engine/narrative.py`）：导演模式走
`scene_brief → generate_scene()`，游戏模式走 `text → play_turn()`；
`flows/scene_flow.py` / `flows/turn_flow.py` 仅保留为向后兼容 shim。

模式切换是**存档级运行时状态**，不是项目创建属性：任意回合边界可切换，世界状态与
记忆不重置；切换前自动打 checkpoint，切换当回合强制重走一次 `director_frame`。

---

## 2. 分层

```
┌──────────────────────────────────────────────────────────────┐
│ Layer 4  表现层        PresentationAdapter                   │
│          TextAdapter / AdvAdapter / NvlAdapter / 未来 3D       │
├──────────────────────────────────────────────────────────────┤
│ Layer 3  Crew 协作层   Crew = LLM Agents + Tools              │
│          LLM Agents 全部输出统一 JSON 信封：                    │
│          director(裁决) / consistency(质检) / prose / ensemble  │
│          Tools:  ExtensionHost 加载的 mod/skill + builtin 工具   │
├──────────────────────────────────────────────────────────────┤
│ Layer 2  共享状态层    WorldState + LayeredMemory             │
│          Fact 真相 / Belief 认知 / 时间 / 地点 / Flag / 记忆    │
├──────────────────────────────────────────────────────────────┤
│ Layer 1  运行时        NarrativeEngine                          │
│          自由文本输入 / Agent JSON → StageDirective             │
├──────────────────────────────────────────────────────────────┤
│ Layer 0  基础设施      llm/router + db/repository              │
│          DeepSeek / OpenAI / Anthropic / Ollama + SQLite       │
│          分层核心记忆 / FTS / 可选向量索引                       │
└──────────────────────────────────────────────────────────────┘
```

与旧架构相比，**裁决不再有独立的规则引擎**：裁决、一致性检查、正文、选项、NPC 动作
全部由 Crew 中的 Agent 以同一套 JSON 信封输出，运行时按字段拆给不同消费方。
ExtensionHost 从独立的「基座层」变为 Crew 的 Tool 加载器，Save 合并进
LayeredMemory 的 checkpoint 机制。这样 Crew 成为整个系统的**唯一协作单元**——
不管是创作、裁决、一致性检查，全部统一在 Crew 的概念下，架构从 6 层简化到 5 层，
每层之间的依赖关系更清晰。

依赖方向自上而下，扩展包只能挂在 Layer 3 定义的 Tool 接口上，不修改核心层。

**模块归属**：`memory/` = 资产模型（`memory/models.py`）+ 世界状态（`memory/state.py`）+
分层记忆与 Checkpoint；`crews/` = Agent 定义 + 导演帧（`crews/scene_crew/outline.py`）；
`engine/narrative.py` = 双模式统一叙事引擎；`flows/` = 兼容层（旧 Flow 名转发到
`NarrativeEngine`）；`frontend/src/components/flow/controls.ts` = 控制策略配置。

---

## 3. 核心抽象

### 3.1 自由文本输入

```python
class TurnBoot(BaseModel):
    text: str = ""
    wait: bool = False
```

核心运行时不做关键词解析或动作类型分类。Agent 推荐选项只是 `text` 的快捷输入，
与玩家手动输入走同一条回合链；具体玩法需要行动约束时，由 extension 提供。

### 3.2 状态容器：Fact / Belief / Memory（`memory/`）

| 层 | 内容 | 维护者 | 用途 |
|---|---|---|---|
| `Fact` | 客观真相 | 导演 Agent 裁决，唯一 | 裁决 |
| `Belief` | 角色相信什么 | 每个 Agent 一份 | 决策，允许错/被骗 |
| `Memory` | 角色经历过什么 | 每个 Agent 一份 | 叙事与回忆 |

```python
class Fact(BaseModel):
    id: str
    subject: str
    predicate: str
    object: str
    truth: Literal["true", "false", "unknown"]
    known_by: set[str]
    asserted_by: str | None
    source_event: str
```

**信息隔离纪律**：

- Agent 的 prompt 只注入 `view(agent_id)`，不拿全局 `WorldState`；
- 裁决 Agent 只信 `Fact`，不信 Agent 转述；
- 写入 `Belief` 走裁决统一处理（谁告诉了谁）。

第一阶段只启用 `known_by` 过滤（`known_only + scoped`）；欺骗 / 误解
（`belief_full`）在 M2 开放。

> 这里的 `Memory` 是**每个 Agent 的经历视图**；项目级的叙事记忆由 §5 的分层记忆系统维护。
> 两者通过 `visibility` / `known_by` 对接：`public` 全员可见；`restricted` 只对
> `known_by` 中的角色（可多人，可含 `crowd`）与全知视角（`gm` / `director` / `narrator`）可见。
>
> 实现归属：`Fact` / `WorldState` / `StageDirective` 等运行时状态位于
> `memory/state.py`；角色、地点、伏笔与项目元数据位于 `memory/models.py`。
> 世界状态被视为一种「世界书 / 长期状态」，与叙事记忆统一放在 `memory/` 包内。

### 3.3 Crew：统一的协作单元

Crew 不再只是「导演模式的多 Agent 编排」，而是整个 StoryLoom 的**核心协作单元**。
一个 Crew 实例 = 一组 LLM Agents + 一组 Tools。

#### LLM Agents（需要模型调用）

| Agent | 职责 | 默认模型 | 灵敏度 |
|-------|------|---------|--------|
| 🎬 导演 director | 场景意图规划；同时承担世界裁决 | DeepSeek V4 Pro | 🔴 CRITICAL |
| 🎭 主角 protagonist | 独立人格，基于动机自主行动 | Claude Sonnet | 🟠 HIGH |
| 👥 群演 ensemble | 多个次要角色共享 1 实例；承担 NPC 自主提案 | DeepSeek Flash | 🟢 LOW |
| 🎲 意外 surprise | 提出「预期之外、情理之中」的事件提案 | Claude Sonnet | 🟠 HIGH |
| 📌 伏笔 foreshadowing | 伏笔全生命周期管理 | DeepSeek V4 Pro | 🟠 HIGH |
| ✅ 一致性 consistency | 校验人设 / 时间线 / 设定冲突 | GPT-4o | 🔴 CRITICAL |
| ✍️ 润色 prose | 行动日志 → 文学化正式正文 | Claude Sonnet | 🟡 MEDIUM |
| 📋 大纲 outline | 章节级结构规划 | DeepSeek V4 Pro | 🟡 MEDIUM |

#### 统一 Agent 输出：`AgentPacket`

所有 Agent 只输出**一个 JSON 对象**，字段谁用谁取；没有独立的结构化管线。
`docs/TECHNICAL.md` 中的 `PACKET_CONTRACT` 是唯一的提示词契约来源。

```python
class AgentPacket(BaseModel):
    prose: str = ""                        # 正文（ProseAgent / 演绎 Agent）
    choices: list[AgentChoice] = []        # 推荐行动（3~4 条，快捷输入）
    stage: list[dict] = []                 # 舞台指令（媒体/表现层消费）
    decision: str = "allow"                # 裁决：allow / reject / direct
    narrative: str = ""                    # 裁决后的世界描述
    reason: str = ""                       # 裁决理由（调试与回放）
    state: dict = {}                       # 结构化增量，转 StateDelta
    available: list[str] = []              # 拒绝时可供选择的替代行动
    npc_actions: list[AgentOperation] = [] # NPC 自主提案，转 ActionProposal
    issues: list[str] = []                 # 一致性 / 审核问题
```

各消费方只读自己关心的字段：

| 消费方 | 读取字段 | 入口 |
|---|---|---|
| 裁决 | `decision` / `narrative` / `reason` / `state` / `available` | `packet_to_result()` |
| 世界状态 | `state` | `packet_to_delta()` |
| NPC 回合 | `npc_actions` | `packet_to_proposals()` |
| 表现层 | `prose` / `choices` / `stage` | `compose_scene()` |
| 质量闸门 | `issues` | `SceneCrew.check_consistency()` |

纯文本输出自动退化为 `prose`，旧格式（如 `suggested_actions`、
`{"passed": false, "conflicts": [...]}`）由 `parse_agent_packet()` 兼容。

> 没有模型时不再调用规则引擎，而是退化为最小自由叙事兜底：时间 +1、
> 记录一条 `freeform` 事件，保证回合链不断。

#### 裁决与质量 Agents

| Agent | 职责 | 实现 |
|-------|------|------|
| 🎬 世界裁决（director） | 行动裁决：`allow / reject / direct` + `state_delta` | `SceneCrew.adjudicate()` |
| ✅ ConsistencyChecker | 校验人设 / 时间线 / 设定冲突 | `SceneCrew.check_consistency()` |
| 🛡️ ModerationGate | 内容审核闸门 | 接口预留，默认 passthrough |

> 裁决不再由确定性 GM 规则完成：导演 Agent 结合世界简报输出 JSON 裁决，
> 运行时只做 `packet_to_result` 的机械转换。规则化约束交给 extension。


#### Tools（由 ExtensionHost 加载）

ExtensionHost 不再是独立的「扩展宿主」层，而是 Crew 的 **Tool Loader**。
它解析 manifest、加载 mod/skill/policy/asset，把它们注册为 Crew 可用的工具。

```yaml
# Extension manifest 示例（注册为 Crew Tool）
id: map_basic
kind: mod
api_version: 1
contributes:
  state: { namespace: map, fields: [locations, routes] }
  rules:
    - { id: map.move, access: gm_only, handler: builtin.map.move }
  tools:
    - { id: map.route, access: llm_tool, read_only: true, handler: builtin.map.route }
```

工具权限分级：

| 能力 | 谁触发 | LLM 可 function call |
|---|---|---|
| `read` / `simulate` | 任意 LLM Agent | ✅ |
| `random` / `mutate` | 仅裁决 Agent（导演） | ❌ |
| `authoring` | 仅导演模式 LLM Agents | 只出提案 |
| `render` | 仅表现层 | ❌ |

LLM 的工具结果只作提案依据，裁决 Agent 用 `WorldState` 复核。

### 3.4 导演 Agent：统一 JSON 裁决

裁决不再是确定性规则引擎，而是**导演 Agent 的一次 JSON 输出**：
`SceneCrew.adjudicate()` 把世界简报（时间 / 地点 / 在场角色 / 已知事实 / 最近事件）
和提案一起交给导演 Agent，取回 `decision / narrative / reason / state / available`。

```
ActionProposal + WorldState 简报
  → 导演 Agent（PACKET_CONTRACT）
  → AgentPacket { decision: allow | reject | direct, state, available, ... }
  → packet_to_result()
  → AdjudicationResult { success, outcome, narrative, state_delta }
  → WorldState.apply_delta()
```

- `allow`：行动成立，`state` 转成 `StateDelta`；成功回合至少推进 1 分钟并留一条事件；
- `reject`：行动不成立，`available` 给出可行替代（同时用于推荐选项）；
- `direct`：导演模式下由导演直接给出世界走向，优先于玩家提案；
- 角色不存在 / 已死亡由运行时前置拦截，不进入 Agent 调用；
- 没有可用模型时走 `_narrate_fallback`，只推进时间并记录 `freeform` 事件。

LLM Agent 决定「想做什么」，导演 Agent 决定「能不能发生」以及「世界随之改变什么」。
需要硬性规则（地图连通、资源扣减）时由 extension 在 `before_adjudicate` 钩子注入。

### 3.5 输出总线：`StageDirective`

```python
class StageDirective(BaseModel):
    kind: Literal[
        "say", "show", "hide", "bg", "bgm", "se",
        "wait", "shake", "flash", "cg", "choice",
        "move", "effect", "end"
    ]
    params: dict
```

`compose_scene()` 把 `AgentPacket` 的 `prose` / `choices` / `stage` 装配成指令序列，
`PresentationAdapter` 决定怎么演。文本只是 `say` 的一种表现；ADV、NVL、
未来的 3D / 多模态都消费同一串指令。`choices` 为空时回退
`WorldState.allowed_actions()` 并标记 `source="rules"`。

### 3.6 双模式权限策略

模式差异收敛在两处，不再有 `AuthorityPolicy` 类族：

```python
# 裁决：同一个入口，靠 mode 影响提示词
await crew.adjudicate(proposal, state, mode="game" | "director")

# 世界改写：直接落在 WorldState 上
state.apply_override(override, snapshot_id=...)
state.rollback_override(override_id)
state.switch_mode("director", checkpoint_id=...)
```

- 游戏模式：玩家与 NPC 同权，玩家提案来自外部输入；世界先于玩家意志；
- 导演模式：导演指令优先级最高，提示词要求输出 `decision="direct"`；允许带审计的改写。

模式只影响 `adjudicate` 的提示词与 `plan_next`，其余阶段完全共用。

导演改写事实必须结构化留痕：

```python
class FactOverride(BaseModel):
    override_id: str
    target: str                 # 角色 / 地点 / 事件 / 伏笔
    field: str
    before: Any                 # 自动从当前 WorldState 取值
    after: Any
    reason: str
    base_snapshot_id: str
```

执行前写 checkpoint，执行后写审计日志（含 before / after）；触发连带一致性扫描，
受影响的伏笔 / 关系 / 事件标记为 `needs_review`；`rollback_override(override_id)` 回到
`base_snapshot_id`；只允许改事实层，不允许绕过 `WorldState` 直接改渲染文本。

### 3.7 稳定钩子点

| 钩子 | 时机 | 可做 |
|---|---|---|
| `after_perceive` | 输入解析后 | 改写 / 补充提案 |
| `before_adjudicate` | 裁决前 | 注入规则、增删校验项 |
| `after_adjudicate` | 裁决后 | 修正 `state_delta` |
| `before_render` | 渲染前 | 注入文风 / 格式 |
| `after_render` | 渲染后 | 追加状态栏、插图指令 |
| `after_commit` | 写回后 | 触发副作用（成就、日志） |

mod 抛异常只降级跳过并打质量标记，不阻断回合。

---

## 4. 统一叙事引擎（`engine/narrative.py`）

`NarrativeEngine` 有两个公开入口，内部共享 `_narrate` 与 `_advance_world`：

| 入口 | 模式 | 链路 |
|---|---|---|
| `generate_scene()` | 导演 | `_narrate(mode="director") → _advance_world(mode="director") → SceneResult` |
| `play_turn()` | 游戏 | `perceive → adjudicate → _narrate(mode="game") → _advance_world → arc tick → render → TurnResult` |

游戏回合的实际顺序：

```
perceive              （从 WorldState 读地点 / 在场角色）
 → adjudicate          （导演 Agent JSON 裁决：allow / reject / direct）
 → _npc_round_fallback （idle_turns ≥ 3 时 NPC 自发事件）
 → _narrate            （DirectorAgent → 可选动态 Crew → ProseAgent；一致性 retry）
 → _advance_world      （世界推进 + 正文落库 + 记忆写入，两种模式共用）
 → arc tick            （OutlinePlanner 推进节拍 / 张力，属于 OutlineAgent）
 → render              （compose_scene：prose + choices + stage）
 → TurnResult
```

- `_narrate` 是 2~3 次 LLM kickoff 的统一链：DirectorAgent 合成
  surprise / intent / foreshadow / consistency，动态 Crew 仅在导演模式启用，
  最后统一走 ProseAgent；一致性 major 冲突按 `max_retries` 重试；
- 没有可用模型时走确定性降级：导演 JSON 兜底 + 最小自由叙事，回合链不断；
- `flows/turn_flow.py` 的 `TurnLoop` 是兼容 shim：保留 quota / timeout / trace
  等旧流程控制，核心叙事转发 `NarrativeEngine.play_turn()`；
- `flows/scene_flow.py` 的 `SceneGenerationFlow` 是兼容 shim：转发
  `NarrativeEngine.generate_scene()`；
- 出口：`play_turn` 在 `ArcState.phase == "ending"` 时返回 `exit="stop"`，
  否则 `next_turn`；超时 / 配额由 shim 返回 `timeout` / `quota_exceeded`；
- 重试与硬上限：`max_retries`（一致性重试）、`max_duration_ms`（超时）、
  `max_turns` / `max_cost`（请求级配额）。

---

## 5. 记忆：资产、世界状态与叙事记忆

`memory/` 是 Layer 2 的统一状态包，按职责拆成多个文件：

| 文件 | 内容 | 对应抽象 |
|---|---|---|
| `memory/models.py` | 角色 / 地点 / 伏笔 / 意外提案 / 项目 | 项目资产 |
| `memory/state.py` | `WorldState` / `Fact` / `CharState` / `LocationState` / `ArcState` / `StageDirective` / `FactOverride` | 运行时世界状态 |
| `memory/base.py` | `MemoryItem` / `MemorySettings` / `MemoryTier` / `WorkingMemory` | 记忆模型与配置 |
| `memory/core.py` | `LayeredMemory` | 分层叙事记忆 |
| `memory/scoring.py` | 摘要 / 重要性评分 / 降级判定 | 记忆生命周期 |
| `memory/compress.py` | 压缩提示词 / 确定性兜底压缩 | 分层压缩 |
| `memory/checkpoint.py` | `CheckpointStore`（`SaveService` 别名保留） | SessionState 快照 |
| `memory/lexical.py` / `vector.py` / `hybrid.py` | 检索后端 | 记忆召回 |
| `memory/indexer.py` | `MemoryIndexer` | 历史场景回填与资产刷新 |

叙事引擎不在 `memory/`：双模式入口位于 `engine/narrative.py`；
旧的 `flows/scene_flow.py` / `flows/turn_flow.py` 只做兼容转发。
导演帧是 Crew 的生成参数，位于 `crews/scene_crew/outline.py`；
ARC / 节拍由 `OutlineAgent` 负责，运行时只保留确定性推进。
控制策略不在后端：它是 Flow 配置，位于 `frontend/src/components/flow/controls.ts`。

### 5.1 运行时状态（`memory/state.py`）

```
WorldState
├── time_minutes / precision
├── characters: CharState（位置 / 情绪 / 健康 / 知识 / 目标 / 背包）
├── locations: LocationState（出口 / 旅行耗时 / 在场角色）
├── facts: Fact（truth / known_by / asserted_by）
├── flags / relationships
├── arc: ArcState（phase / tension_target / beats_remaining / info_budget）
└── pending_promises（伏笔 / 命运承诺）
```

`WorldEvent` 记录已发生事件，`Promise` 记录承诺与期限。

**权威态与记忆投影的边界**：`WorldState` 是运行时权威真相，不做压缩或淘汰；
`WorldState.memory_projection()` 只把回忆型内容投影到记忆层
（`facts` / `relationships` / `promises` → `long_term`，关键事件 → `key_events`），
由 `LayeredMemory.sync_world_state()` 在 `_advance_world` 末尾同步。
已降级到 `archive` 的投影条目保持原位，不因每回合同步而复活。

### 5.2 叙事记忆分层 + Checkpoint（`memory/core.py` + `memory/checkpoint.py`）

项目级叙事记忆分为 5 层：核心层常驻 prompt，检索层按需召回；
**Checkpoint 作为 SessionState（WorldState + LayeredMemory + 渲染历史）的快照机制**，
与分层记忆共用持久化后端，不再是独立的 `SaveService` 模块。

| 层 | 内容 | 进入 prompt | 持久化 |
|---|---|---|---|
| L0 `working` | 当前场景 brief / 地点 / 在场角色 / 本轮意图 | 总是 | 否 |
| L1 `short_term` | 最近 K 个场景的详细摘要 | 是 | 是 |
| L2 `long_term` | 压缩后的章节 / 桥段摘要 | 是 | 是 |
| L3 `key_events` | 改变主线 / 世界格局的关键事件 | 是 | 是 |
| L4 `archive` | 环境、世界观、角色背景、已解决伏笔、被降级旧记忆 | 按需检索 | 是（索引可重建） |
| — **Checkpoint** | **WorldState 快照 + 渲染历史 + memory_snapshot** | **恢复时写入 working** | **是（与记忆同后端）** |

核心层固定为 `short_term → long_term → key_events` 三档（`working` / `archive` 是端点）；
三档的容量与压缩由 `tiers` 有序列表配置，降级 / 回温由 `demotion` 配置。
优先级：`MemorySettings` 代码默认 < `memory_config.default.yaml` 种子 < 项目 `memory_configs`；
种子只在项目首次读取时导入，之后以数据库配置为准。层名受 `MemoryTier`
枚举约束，当前不支持新增自定义层。

**Checkpoint 机制**（原 `SaveService`）：

```python
class Checkpoint(BaseModel):
    checkpoint_id: str
    project_id: str
    label: str                           # "第N回合" / "switch_to_director" / "手动存档"
    created_at: datetime
    turn: int
    mode: Literal["game", "director"]
    kind: Literal["story", "checkpoint"] # story=玩家手动存; checkpoint=系统自动打
    world_state: dict                    # WorldState.model_dump()
    directives: list[dict]               # 最近一轮渲染结果（回放不重新生成）
    text: str
    choices: list[dict]
    memory_snapshot: dict                # LayeredMemory.snapshot()（恢复时直接写入）
    metadata: dict
```

Checkpoint 的产生时机：
- **玩家主动存档**（存档 API）
- **模式切换前**（`WorldState.switch_mode`）
- **事实改写前**（`FactOverride.base_snapshot_id`）

Checkpoint 合并进记忆系统的设计理由：

| 旧设计 | 问题 | 新设计 |
|---|---|---|
| `saves/service.py` 独立模块 | 职责分散：记忆和存档都持久化 session 状态，却用两套系统 | 合并进 `memory/`，统一 checkpoint 接口 |
| 文件快照 `data/saves/*.json` | 与 `memory_items` 两张表不共享后端 | Checkpoint 记录可以和记忆条目共用 SQLite，或后续统一迁移到 DB |
| 回滚时要分别恢复 WorldState 和 Memory | 两处恢复、两处一致性检查 | `LayeredMemory.restore()` 接受 checkpoint，一次恢复 |
| 手动存档与系统 checkpoint 两种实现 | 手动存档保存了 SceneDirective 回放，系统 checkpoint 只存 WorldState | 统一 Checkpoint 模型，都保存完整状态 |

### 5.3 检索后端

| 后端 | 实现 | 适用 |
|---|---|---|
| `fts` | SQLite FTS5 `trigram` + `LIKE` 兜底 | 默认；专名、伏笔、场景回溯 |
| `vector` | 内存向量索引 + 可注入 embedding | 主题、情绪、相似桥段 |
| `hybrid` | FTS + 向量，RRF 融合 | 配好 embedding 后的推荐值 |

- 三种后端同级，按项目记忆配置（`memory_configs` 的 `retrieval.backend`）切换；
- 作品数据（`scenes` / 资产）是事实来源，记忆索引与向量库可重建；
- 不默认绑定 embedding 模型；中文叙事需显式注入多语言模型；
- embedding 不可用时，`vector` 返回空，`hybrid` 自动退化为 `fts`，不阻断生成。

### 5.4 与角色视图的关系

- 叙事记忆是**项目级**的，供导演、渲染与一致性检查使用；
- `Fact / Belief / Memory` 是**角色级**的，Agent 只拿 `view(agent_id)`；
- 叙事记忆用 `visibility` + `known_by` 表达知情范围：
  - `public`：所有角色可见；
  - `restricted`：`known_by` 中的角色可见，支持多人与 `crowd`（无名路人）；
  - `restricted` + 空 `known_by`：只有全知视角（导演 / GM / 旁白）可见；
- `secrets` 唯一存储在 `memory_items` 的 `secret:<角色>`（`archive + restricted + known_by=[角色]`），
  `characters` 表不再保存该字段；旧列在 `create_all` 时一次性迁移后删除；
- 伏笔描述与真相分别投影为 `foreshadow:<id>` / `foreshadow_truth:<id>`，共享同一
  `visibility + known_by`：默认仅全知视角可见，生成时可指定“天生知道”的角色；
- 回溯补录伏笔时先做结构检查（角色是否存在、场景时间线、重复/矛盾），再由导演视角
  对相关记忆做一致性检查；major 冲突以 409 阻断，LLM 不可用时降级为 minor 提示；
- 世界书检索在 `LayeredMemory.retrieve` 先按 `viewer` 过滤候选池，再交给
  `fts` / `vector` / `hybrid`，三种后端共享同一可见性边界；
- `Fact.known_by` 是**可变权威**：新增知情者后，`sync_world_state` 按稳定 id
  `ws:fact:<id>` 原地更新对应记忆；场景记忆的 `known_by` 是**目击者集合**，不随事后传播改写；
- 压缩合并跨可见范围时取 `known_by` 交集，避免把不同知情者的记忆合成公开信息；
- 群演只是一个 LLM 实例串行扮演多个角色，`known_by` 仍按角色名记录，每个角色 Task
  用自己的 `viewer` 取记忆。

---

## 6. 当前模块与目录

| 模块 | 位置 | 职责 |
|---|---|---|
| StoryEngine | `api/engine.py` | 项目 / 资产 / Checkpoint / 扩展 / 双模式 API 门面 |
| NarrativeEngine | `engine/narrative.py` | `generate_scene()` / `play_turn()`，共享 `_narrate` + `_advance_world` |
| SceneCrew | `crews/scene_crew/crew.py` | LLM Agents + 导演裁决 + NPC 提案 + 质检 |
| AgentPacket | `crews/scene_crew/packet.py` | 统一 JSON 契约 + 场景装配 |
| ExtensionHost | `extensions/host.py` | Crew 的 Tool Loader |
| LayeredMemory | `memory/core.py` | 分层记忆 / 压缩 / 降级 / 回温 |
| CheckpointStore | `memory/checkpoint.py` | SessionState 快照与回放 |
| 兼容 shim | `flows/scene_flow.py` / `flows/turn_flow.py` | 旧 Flow 名转发到 `NarrativeEngine` |

StoryEngine 是 API 门面，叙事细节委托给 `NarrativeEngine`：

```python
class StoryEngine:
    # === 项目管理 / 资产 ===
    create_project / get_project / list_projects / add_character / ...

    # === 两种模式 ===
    generate_scene(request)           # 导演模式：委托 NarrativeEngine.generate_scene()
    play_turn(project_id, boot)       # 游戏模式：委托 NarrativeEngine.play_turn()

    # === 模式切换 ===
    switch_game_mode(project_id, target_mode, instance_id)

    # === 记忆 & Checkpoint ===
    memory_for(project_id, backend) -> LayeredMemory
    create_save / list_saves / load_save

    # === 扩展 ===
    resolve_extensions(instance_id, enabled)
```

### 6.1 目录结构

```
src/storyloom/
├── api/
│   ├── main.py              # FastAPI 入口 + CORS
│   ├── engine.py            # **StoryEngine**：项目/资产/双模式 API 门面
│   ├── schemas.py
│   └── routers/             # 版本化 API：/runtime/v1/* + /api/*
├── engine/
│   └── narrative.py         # **NarrativeEngine**：generate_scene / play_turn
├── crews/
│   └── scene_crew/
│       ├── crew.py          # @CrewBase SceneCrew：Agent + 裁决 + NPC + 质检
│       ├── packet.py        # AgentPacket 统一 JSON 契约 + 场景装配
│       ├── arc.py           # 导演帧：起承转合 + 张力 + 信息预算（Crew 生成参数）
│       ├── tools.py         # Crew 工具（如活跃伏笔查询）
│       └── config/          # agents.default.yaml / tasks.default.yaml
├── extensions/
│   ├── manifest.py          # manifest schema + 校验
│   └── host.py              # ExtensionHost = Crew 的 Tool Loader
├── memory/
│   ├── models.py            # 资产模型 / 伏笔 / 意外 / NovelProject
│   ├── state.py             # WorldState + Fact + FactOverride + 裁决协议
│   ├── base.py              # MemoryItem / MemorySettings / MemoryTier
│   ├── core.py              # LayeredMemory：分层 / 压缩 / 降级 / 回温
│   ├── scoring.py           # 摘要 / 重要性评分 / 降级判定
│   ├── compress.py          # 压缩提示词 + 确定性兜底
│   ├── checkpoint.py        # CheckpointStore：快照 + 恢复
│   ├── lexical.py           # fts 后端
│   ├── vector.py            # vector 后端
│   ├── hybrid.py            # hybrid 后端
│   └── indexer.py           # 历史场景回填与资产刷新
├── llm/                     # providers.py + router.py
├── db/                      # ORM + Repository
├── config/
│   ├── memory_config.default.yaml
│   └── model_config.yaml
├── templates/               # xianxia_system.py / sandbox_life.py + 内嵌扩展
└── frontend/                # Vue 3（components/flow/controls.ts 为 Flow 控制配置）
```

---

## 7. 控制论

控制论不再作为独立后端层，而是落在 **Flow 配置 + Crew 反馈闭环** 上：
调整控制策略本质上就是修改 Flow 的节点 / 连线参数。

| 原理 | 新位置 |
|---|---|
| 反馈闭环 | 导演 Agent 裁决 + ConsistencyChecker + ModerationGate；Flow 中 `feedback_loop` 节点 |
| 统计滤波 | Flow 节点 `nSamples` / `multi_sample` 策略 |
| 灵敏度分析 | `frontend/src/components/flow/controls.ts` 的 Agent 灵敏度画像 |
| 解耦控制 | `TurnBoot(text)` / `AgentPacket` / `StageDirective` / `Fact` 分层解耦 |
| 分层管控 | Layer 3 Crew（LLM+Tools）+ Layer 2 状态 + Layer 1 运行时 |
| 人机结合 | Flow 中 `human_review` 节点 |

详见 [CONTROL_THEORY.md](CONTROL_THEORY.md)。

---

## 8. 多模态预留

`ProseAgent` / `StageDirective` 的产出是结构化中间表示，未来接入 TTS、
图片、视频时只需新增 `PresentationAdapter` 或 `MediaProvider`，Agent 与
Flow 逻辑不变。

第一阶段媒体范围：`image + audio`；`video` 在类型系统预留、默认关闭。
M0 只解析 `asset` manifest，不做媒体渲染。

---

## 9. 演进阶段

| 阶段 | 内容 | 状态 |
|---|---|---|
| 作者模式 MVP | 场景生成 / 资产与场景落库 / 章节 / Web 工作台 | ✅ |
| M0 | 双模式纵切：WorldState / 导演 Agent JSON 裁决 / 双总线 / `NarrativeEngine` 统一叙事链 / 模式切换 / NPC 自主 / LayeredMemory + Checkpoint / memory 统一资产·状态·记忆 / Mod v1 / 游戏前端 | ✅ |
| M1 | TFC 五档、审核 Gate 实装、图片/音频媒体、Flag/Choice/好感度、章节化收束 | 🔲 |
| M2 | 命运、Casting、路线图、日程、POV、Belief 全量、ADV/NVL | 🔲 |
| M3 | 视频、生成式媒体、TTS | 🔲 |
