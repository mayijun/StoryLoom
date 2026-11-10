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
| 权限 | 可改写事实（`FactOverride`，审计 + 快照） | 行动需 GM 裁决，可失败 |
| 产物 | 小说章节 | 可交互的文字世界 |

两种模式共用同一套世界状态、裁决、渲染与扩展机制。导演模式保留现有的
`scene_brief → 场景正文` 入口；游戏模式走 `PlayerIntent → TurnLoop`。

模式切换是**存档级运行时状态**，不是项目创建属性：任意回合边界可切换，世界状态与
记忆不重置；切换前自动打 checkpoint，切换当回合强制重走一次 `director_frame`。

---

## 2. 分层

```
┌──────────────────────────────────────────────────────────────┐
│ Layer 4  表现层        PresentationAdapter                   │
│          TextAdapter / AdvAdapter / NvlAdapter / 未来 3D       │
├──────────────────────────────────────────────────────────────┤
│ Layer 3  Crew 协作层   Crew = LLM Agents + Deterministic + Tools │
│          LLM Agents:  director / protagonist / ensemble / ... │
│          Deterministic Agents:  GM(裁决) / Consistency / 审核   │
│          Tools:  ExtensionHost 加载的 mod/skill + builtin 工具   │
├──────────────────────────────────────────────────────────────┤
│ Layer 2  共享状态层    WorldState + LayeredMemory             │
│          Fact 真相 / Belief 认知 / 时间 / 地点 / Flag / 记忆    │
├──────────────────────────────────────────────────────────────┤
│ Layer 1  运行时        IntentRouter + DirectiveBus             │
│          PlayerIntent / StageDirective                        │
├──────────────────────────────────────────────────────────────┤
│ Layer 0  基础设施      llm/router + db/repository              │
│          DeepSeek / OpenAI / Anthropic / Ollama + SQLite       │
│          分层核心记忆 / FTS / 可选向量索引                       │
└──────────────────────────────────────────────────────────────┘
```

与旧架构相比，**GM 从独立的「世界层」降级为 Crew 中的一个确定性角色**，
ExtensionHost 从独立的「基座层」变为 Crew 的 Tool 加载器，Save 合并进
LayeredMemory 的 checkpoint 机制。这样 Crew 成为整个系统的**唯一协作单元**——
不管是创作、裁决、一致性检查，全部统一在 Crew 的概念下，架构从 6 层简化到 5 层，
每层之间的依赖关系更清晰。

依赖方向自上而下，扩展包只能挂在 Layer 3 定义的 Tool 接口上，不修改核心层。

---

## 3. 核心抽象

### 3.1 输入总线：`PlayerIntent`

```python
class PlayerIntent(BaseModel):
    kind: Literal["text", "choice", "click", "qte", "skip", "save", "load", "meta"]
    payload: dict
```

选项与自由输入共存：`choice` 是传统 galgame，`text` 是动态文字世界，
两者走同一条解析与裁决链。

### 3.2 状态容器：Fact / Belief / Memory

| 层 | 内容 | 维护者 | 用途 |
|---|---|---|---|
| `Fact` | 客观真相 | GM Crew Agent，唯一 | 裁决 |
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
- GM 只信 `Fact`，不信 Agent 转述；
- 写入 `Belief` 走 GM 统一处理（谁告诉了谁）。

第一阶段只启用 `known_by` 过滤（`known_only + scoped`）；欺骗 / 误解
（`belief_full`）在 M2 开放。

> 这里的 `Memory` 是**每个 Agent 的经历视图**；项目级的叙事记忆由 §5 的分层记忆系统维护。
> 两者在 M0 通过 `visibility` / `known_by` 对接：叙事记忆的私有条目只有对应角色可见。

### 3.3 Crew：统一的协作单元

Crew 不再只是「导演模式的多 Agent 编排」，而是整个 StoryLoom 的**核心协作单元**。
一个 Crew 实例 = 一组 LLM Agents + 一组 Deterministic Agents + 一组 Tools。

#### LLM Agents（需要模型调用）

| Agent | 职责 | 默认模型 | 灵敏度 |
|-------|------|---------|--------|
| 🎬 导演 director | 场景意图规划，间接引导而非操控角色 | DeepSeek V4 Pro | 🔴 CRITICAL |
| 🎭 主角 protagonist | 独立人格，基于动机自主行动 | Claude Sonnet | 🟠 HIGH |
| 👥 群演 ensemble | 多个次要角色共享 1 实例，压缩成本 | DeepSeek Flash | 🟢 LOW |
| 🎲 意外 surprise | 提出「预期之外、情理之中」的事件提案 | Claude Sonnet | 🟠 HIGH |
| 📌 伏笔 foreshadowing | 伏笔全生命周期管理 | DeepSeek V4 Pro | 🟠 HIGH |
| ✍️ 润色 prose | 行动日志 → 文学化正式正文 | Claude Sonnet | 🟡 MEDIUM |
| 📋 大纲 outline | 章节级结构规划 | DeepSeek V4 Pro | 🟡 MEDIUM |

#### Deterministic Agents（纯代码，不需要模型调用）

| Agent | 职责 | 为什么是 deterministic |
|-------|------|----------------------|
| 🎲 **GM** (GameMaster) | 行动裁决：存在性、在场性、可见性、资源、世界规则 | 规则是确定性的，不该让 LLM 即兴发挥 |
| ✅ **ConsistencyChecker** | 校验人设/时间线/设定冲突 | 逻辑一致性可代码化，LLM 只做语义辅助 |
| 🛡️ **ModerationGate** | 内容审核闸门 | 合规策略是确定性规则，LLM 做分类辅助 |
| 🔀 **IntentRouter** | 解析输入意图类型 | 分类走路由逻辑，不 LLM |

> 这些 deterministic agents 不占 API Key，永远可用，不随模型质量波动。
> 它们可以被 CrewAI 的 `@tool` 或 Flow 节点包装，和 LLM agents 无缝协作。

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
| `random` / `mutate` | 仅 GM Agent | ❌ |
| `authoring` | 仅导演模式 LLM Agents | 只出提案 |
| `render` | 仅表现层 | ❌ |

LLM 的工具结果只作提案依据，GM Agent 裁决时用 `WorldState` 复核。

### 3.4 GM Agent：裁决

GM 现在是 Crew 中的一个 deterministic agent。它做的事情没有变，只是身份从
「独立模块」变成了「Crew 的一员」。

```
ActionProposal
  → 存在性 / 在场性 / 可见性
  → allowed_actions(地点, 角色)
  → 资源、能力、世界规则
  → 在场 NPC 反应（只读工具）
  → AdjudicationResult { success, outcome, state_delta, time_delta }
```

LLM Agent 决定「想做什么」，GM Agent 决定「能不能发生」。规则缺口策略可配：
`reject | llm_referee | human_review`。

GM Agent 是 TurnLoop 中 `adjudicate` 阶段的执行者。

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

渲染层产出指令序列，`PresentationAdapter` 决定怎么演。文本只是 `say`
的一种表现；ADV、NVL、未来的 3D / 多模态都消费同一串指令。

### 3.6 双模式权限策略

```python
class AuthorityPolicy(Protocol):
    def adjudicate(self, proposal, world, frame) -> Adjudication: ...
    def may_write_state_directly(self, actor: str) -> bool: ...
    def apply_override(self, override, world, snapshot_id) -> WorldState: ...
```

- `GameAuthority`：GM Agent 全权裁决；玩家与 NPC 同权，玩家提案来自外部输入；
- `DirectorAuthority`：导演指令优先级最高，GM Agent 降级为事实检查器；允许带审计的改写。

模式只影响 `interpret_*`、`adjudicate`、`plan_next` 三处策略，其余阶段完全共用。

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
受影响的伏笔 / 关系 / 事件标记为 `needs_review`；`rollback(override_id)` 回到
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

## 4. TurnLoop

```
boot
 → perceive
 → classify_input
      ├─ player_action → interpret_player_action
      ├─ directive     → interpret_director_command
      └─ idle          → autonomous_tick
 → director_frame      （节拍 / 张力 / 信息预算 / 命运预兆）
 → actor_round         （按 detail_plan 决定实例化谁）
 → adjudicate          （GM Agent 规则、随机、时间推进）
 → consistency_check   （ConsistencyChecker Agent 冲突 → retry ≤ N）
 → moderation_gate     （ModerationGate Agent 暂存态审核）
 → render_scene        （产出 StageDirective）
 → commit              （事务转正）
 → plan_next
      ├─ next_turn → perceive
      ├─ end_arc
      ├─ stop
      ├─ idle_stop
      └─ human_review
```

- 循环用 `@router` 回到上游；`@listen` 不能指向自身，回环统一经 `plan_next` 标签；
- 出口条件：`max_turns`、`arc_complete`、`player_quit`、`idle_stop`、
  连续 3 回合质量下降、`human_review_required`；
- 硬上限：`max_turns_per_session`、`max_retries_per_turn`、`max_cost_per_turn`；
- Flow 的 `max_method_calls` 兜底，防止逻辑遗漏导致死循环。

---

## 5. 世界状态与记忆

### 5.1 运行时状态

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

### 5.2 叙事记忆分层 + Checkpoint

项目级叙事记忆分为 5 层：核心层常驻 prompt，检索层按需召回；
**Checkpoint 作为 SessionState（WorldState + LayeredMemory + 渲染历史）的快照机制**，
与分层记忆共用持久化后端，不再是独立的 `SaveService` 模块。

| 层 | 内容 | 进入 prompt | 持久化 |
|---|---|---|---|
| L0 `working` | 当前场景 brief / 地点 / 在场角色 / 本轮意图 | 总是 | 否 |
| L1 `short_term` | 最近 K 个场景的详细摘要 | 是 | 是 |
| L2 `long_term` | 压缩后的章节 / 桥段摘要 | 是 | 是 |
| L3 `canon` | 改变主线 / 世界格局的关键事件（历史事件） | 是 | 是 |
| L4 `archive` | 环境、世界观、角色背景、已解决伏笔、被降级旧记忆 | 按需检索 | 是（索引可重建） |
| — **Checkpoint** | **WorldState 快照 + 渲染历史 + memory_snapshot** | **恢复时写入 working** | **是（与记忆同后端）** |

核心层固定为 `short_term → long_term → canon` 三档（`working` / `archive` 是端点）；
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
- **玩家主动存档**（`PlayerIntent.kind = "save"`）
- **模式切换前**（`GameAuthority.switch_mode`）
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
| `vector` | Chroma + 可配置 embedding（OpenAI / Ollama） | 主题、情绪、相似桥段 |
| `hybrid` | FTS + 向量，RRF 融合 | 配好 embedding 后的推荐值 |

- 三种后端同级，按项目记忆配置（`memory_configs` 的 `retrieval.backend`）切换；
- 作品数据（`scenes` / 资产）是事实来源，记忆索引与向量库可重建；
- 不使用 Chroma 默认英文 embedding；中文叙事需显式配置多语言模型；
- embedding / Chroma 不可用时，`vector` 返回空，`hybrid` 自动退化为 `fts`，不阻断生成。

### 5.4 与角色视图的关系

- 叙事记忆是**项目级**的，供导演、渲染与一致性检查使用；
- `Fact / Belief / Memory` 是**角色级**的，Agent 只拿 `view(agent_id)`；
- 叙事记忆中的 `secrets` 等私有条目带 `visibility = private:<name>`，
  只有对应角色在场时才进入其 prompt；
- M2 接入完整 `Belief` 后，`known_by` 直接映射为 `visibility` 过滤，不改检索后端协议。

---

## 6. 与现有实现的映射

| 现有模块 | 在新架构中的位置 | 状态 |
|---|---|---|
| `api/engine.py` | **StoryEngine**：项目 / 资产 / 两种模式运行时，改名 + 职责收窄 | 改名 + 保留 |
| `crews/scene_crew/` | Layer 3 Crew：导演模式 LLM Agents + 扩展 Deterministic Agents (GM) + Tools | 保留 + 扩展 |
| `flows/scene_flow.py` | 导演模式的单场景子流程 | 保留 |
| `flows/turn_flow.py` | 双模式 TurnLoop | 保留 |
| `control/` | 全层质量控制 | 保留 |
| `memory.py` → `memory/` | Layer 2 分层记忆 + Checkpoint（原 SaveService 合并进来） | 重构 + 合并 |
| `llm/router.py` | Layer 0 模型路由 | 复用 |
| `models.py` | 资产模型 | 复用 |
| `db/repository.py` | Layer 0 持久化 | 复用 + Checkpoint 记录 |
| `media/render_adapter.py` | Layer 5 表现层雏形 | 重构为 `PresentationAdapter` |

### 6.1 StoryEngine（原 NovelEngine）

| 旧名 | 新名 | 理由 |
|---|---|---|
| `NovelEngine` | **StoryEngine** | 不再只是生成小说章节；游戏模式、双模式切换、TurnLoop、记忆编排都在这个引擎里。`StoryEngine` 更直观地表达「整个 StoryLoom 运行时的入口」。 |

StoryEngine 的职责：

```python
class StoryEngine:
    # === 项目管理 ===
    create_project / get_project / list_projects / add_character / ...
    
    # === 两种模式的统一入口 ===
    generate_scene(request)          # 导演模式：生成一章场景
    play_turn(project_id, boot)     # 游戏模式：跑一个 TurnLoop
    
    # === 模式切换 ===
    switch_game_mode(project_id, target_mode, instance_id)
    
    # === 记忆 & Checkpoint ===
    memory_for(project_id, backend) -> LayeredMemory
    create_checkpoint / list_checkpoints / restore_checkpoint  # 原 save_* 方法
    
    # === 扩展 ===
    resolve_extensions(instance_id, enabled)
```

### 6.2 目录结构

```
src/storyloom/
├── api/
│   ├── main.py              # FastAPI 入口 + CORS
│   ├── engine.py            # **StoryEngine**：项目/资产/双模式运行时
│   ├── schemas.py
│   └── routers/             # 版本化 API：/runtime/v1/* + /api/*
├── crews/
│   └── scene_crew/
│       ├── crew.py          # @CrewBase SceneCrew + Deterministic Agents
│       ├── deterministic/  # GM / ConsistencyChecker / ModerationGate
│       ├── tools/           # ExtensionHost 注册的 mod/skill 工具
│       └── config/          # agents.default.yaml / tasks.default.yaml
├── world/
│   ├── state.py             # WorldState + Fact + CharState + LocationState + ArcState
│   ├── authority.py         # GameAuthority / DirectorAuthority 策略
│   └── autonomous_agent.py  # NPC 自主（记忆 → 反思 → 计划 → 提案）
├── runtime/
│   ├── intent.py            # PlayerIntent + IntentRouter
│   ├── directive.py         # StageDirective
│   └── renderer.py          # SceneRenderer
├── extensions/
│   ├── manifest.py          # manifest schema + 校验
│   └── host.py              # ExtensionHost = Crew 的 Tool Loader
├── memory/
│   ├── core.py              # LayeredMemory：分层 / 压缩 / 降级 / 回温
│   ├── checkpoint.py        # Checkpoint：快照 + 恢复（**原 saves/service.py 合并进来**）
│   ├── lexical.py           # fts 后端
│   ├── vector.py            # vector 后端
│   ├── hybrid.py            # hybrid 后端
│   ├── indexer.py           # 历史回填
│   └── legacy.py            # CoreMemory + SimpleRAGMemory（作者模式兼容）
├── flows/
│   ├── scene_flow.py        # 导演模式单场景
│   └── turn_flow.py         # 双模式 TurnLoop
├── narrative/
│   └── arc.py               # 起承转合节拍 + 张力 + 信息预算
├── control/                 # 控制论：feedback_loop · robustness · hierarchy
├── llm/                     # providers.py + router.py
├── db/                      # ORM + Repository
├── models.py                # 资产模型 / 伏笔 / 意外 / NovelProject
├── media/                   # render_adapter.py → PresentationAdapter
├── config/memory_config.default.yaml
├── templates/               # 试用模板 + 内嵌扩展
└── frontend/                # Vue 3
```

**删除的模块**：

| 旧路径 | 去向 |
|---|---|
| `saves/service.py` | 合并进 `memory/checkpoint.py`，`SaveService` 改为 `CheckpointStore` |
| `world/game_master.py` | 移进 `crews/scene_crew/deterministic/gm.py`，GM 成为 Crew Agent |
| `extensions/host.py` | 保留路径不变，重新定位为 Crew 的 Tool Loader |

---

## 7. 控制论

控制论层完整保留，并重新定位：

| 原理 | 新位置 |
|---|---|
| 反馈闭环 | GM Agent 裁决 + ConsistencyChecker + ModerationGate 三重闭环 |
| 统计滤波 | 关键裁决多次采样 / 投票（M0 后） |
| 灵敏度分析 | 按 `importance_tier` 决定 tick 频率与审核强度 |
| 解耦控制 | `PlayerIntent` / `StageDirective` / `Fact` 三层解耦 |
| 分层管控 | Layer 3 Crew（LLM+Deterministic+Tools）+ Layer 2 状态 + Layer 1 运行时 |
| 人机结合 | 关键裁决、审核不确定、命运收束转人工 |

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
| M0 | 双模式纵切：WorldState / GM Agent / 双总线 / TurnLoop / Authority + 模式切换 / NPC 自主 / LayeredMemory + Checkpoint / Mod v1 / 游戏前端 | ✅ |
| M1 | TFC 五档、审核 Gate 实装、图片/音频媒体、Flag/Choice/好感度、章节化收束 | 🔲 |
| M2 | 命运、Casting、路线图、日程、POV、Belief 全量、ADV/NVL | 🔲 |
| M3 | 视频、生成式媒体、TTS | 🔲 |
