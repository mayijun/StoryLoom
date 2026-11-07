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
│ Layer 5  表现层        PresentationAdapter                   │
│          TextAdapter / AdvAdapter / NvlAdapter / 未来 3D       │
├──────────────────────────────────────────────────────────────┤
│ Layer 4  叙事导演层    NarrativeDirector + TFC + Fate         │
│          节奏、张力、伏笔、命运、信息预算（全部可扩展）          │
├──────────────────────────────────────────────────────────────┤
│ Layer 3  角色层        AutonomousAgent / Actor / Ensemble      │
│          记忆 → 反思 → 计划 → 行动；只拿 view(agent_id)        │
├──────────────────────────────────────────────────────────────┤
│ Layer 2  世界层        WorldState + GameMaster                │
│          Fact 真相 / Belief 认知 / 时间 / 地点 / Flag / 裁决    │
├──────────────────────────────────────────────────────────────┤
│ Layer 1  基座层        IntentRouter + ExtensionHost + Save     │
│          PlayerIntent / StageDirective / manifest / 快照       │
├──────────────────────────────────────────────────────────────┤
│ Layer 0  模型与存储    llm/router + db/repository             │
│          DeepSeek / OpenAI / Anthropic / Ollama + SQLite       │
└──────────────────────────────────────────────────────────────┘
```

依赖方向自上而下，扩展包只能挂在 Layer 1 定义的接口上，不修改核心层。

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
| `Fact` | 客观真相 | GM，唯一 | 裁决 |
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

### 3.3 裁决：`GameMaster`

```
ActionProposal
  → 存在性 / 在场性 / 可见性
  → allowed_actions(地点, 角色)
  → 资源、能力、世界规则
  → 在场 NPC 反应（只读工具）
  → AdjudicationResult { success, outcome, state_delta, time_delta }
```

LLM 决定「想做什么」，GM 决定「能不能发生」。规则缺口策略可配：
`reject | llm_referee | human_review`。

### 3.4 输出总线：`StageDirective`

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

### 3.5 扩展宿主：`ExtensionHost`

统一 manifest，四种 `kind`：

| kind | 权限 | 作用 |
|---|---|---|
| `skill` | 只读 | prompt / 知识 / 文风 |
| `mod` | 可写 | 状态、规则、确定性工具 |
| `policy` | 只读 | 审核策略包 |
| `asset` | 只读 | 图片 / 音频资源 |

```yaml
id: map_basic
kind: mod
api_version: 1
requires: { time_resolution: minute }
contributes:
  state: { namespace: map, fields: [locations, routes] }
  rules:
    - { id: map.move, access: gm_only, handler: builtin.map.move }
  tools:
    - { id: map.route, access: llm_tool, read_only: true, handler: builtin.map.route }
```

mod 纪律：状态变更必须走 builtin handler；暴露给 LLM 的工具一律 `read_only`；
v1 为 YAML + 白名单 handler，v2 的 Python 包与 `capabilities` 声明只预留接口。

### 3.6 能力分级

| 能力 | 谁触发 | LLM 可 function call |
|---|---|---|
| `read` / `simulate` | 任意 Agent | ✅ |
| `random` / `mutate` | 仅 GM | ❌ |
| `authoring` | 仅导演模式 | 只出提案 |
| `render` | 仅渲染层 | ❌ |

LLM 的工具结果只作提案依据，GM 裁决时用 `WorldState` 复核。

### 3.7 双模式权限策略

```python
class AuthorityPolicy(Protocol):
    def adjudicate(self, proposal, world, frame) -> Adjudication: ...
    def may_write_state_directly(self, actor: str) -> bool: ...
    def apply_override(self, override, world, snapshot_id) -> WorldState: ...
```

- `GameAuthority`：GM 全权裁决；玩家与 NPC 同权，玩家提案来自外部输入；
- `DirectorAuthority`：导演指令优先级最高，GM 降级为事实检查器；允许带审计的改写。

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

执行前写快照，执行后写审计日志（含 before / after）；触发连带一致性扫描，受影响的
伏笔 / 关系 / 事件标记为 `needs_review`；`rollback(override_id)` 回到
`base_snapshot_id`；只允许改事实层，不允许绕过 `WorldState` 直接改渲染文本。

### 3.8 稳定钩子点

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
 → adjudicate          （GM 规则、随机、时间推进）
 → consistency_check   （冲突 → retry ≤ N）
 → moderation_gate     （暂存态审核）
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

```
WorldState
├── time_minutes / precision
├── characters: CharState（位置 / 情绪 / 健康 / 知识 / 目标 / 背包）
├── locations: LocationState（出口 / 旅行耗时 / 在场角色）
├── facts: Fact（truth / known_by / asserted_by）
├── flags / relationships
├── arc: ArcState（phase / tension_target / beats_remaining / info_budget）
└── pending_promises（伏笔 / 命运承诺）

CoreMemory（直接拼入 prompt）
├── 当前场景状态
├── 最近 2~3 个场景摘要
└── 导演当前参数

SimpleRAGMemory（按需检索）
├── 世界观 / 角色背景 / 场景细节
├── ChromaDB，按项目隔离
└── 未安装时退化为关键词检索
```

原则：**关键记忆直接给，背景记忆按需取**；Agent 只拿自己的 `view`。
`WorldEvent` 记录已发生事件，`Promise` 记录承诺与期限。

---

## 6. 与现有实现的映射

| 现有模块 | 在新架构中的位置 | 状态 |
|---|---|---|
| `api/engine.py` | 项目 / 资产运行时，新增 game 方法 | 复用 + 扩展 |
| `crews/scene_crew/` | 导演模式渲染管道 | 保留 |
| `flows/scene_flow.py` | 导演模式的单场景子流程 | 保留 |
| `control/` | 全层质量控制 | 保留 |
| `memory.py` | Layer 3 记忆 | 复用 |
| `llm/router.py` | Layer 0 模型路由 | 复用 |
| `models.py` | 资产模型 | 复用 |
| `db/repository.py` | Layer 0 持久化 | 复用 + 新增 `saves` |
| `media/render_adapter.py` | Layer 5 表现层雏形 | 重构为 `PresentationAdapter` |

新增模块：

```
src/storyloom/
├── world/        # state.py / rules.py / game_master.py / authority.py / autonomous_agent.py
├── runtime/      # intent.py / directive.py / renderer.py
├── extensions/   # manifest.py / host.py
├── narrative/    # arc.py
├── flows/        # turn_flow.py
├── saves/        # service.py
└── examples/world_demo/
```

---

## 7. 控制论

控制论层完整保留，并重新定位：

| 原理 | 新位置 |
|---|---|
| 反馈闭环 | GM 裁决 + 一致性 + 审核三重闭环 |
| 统计滤波 | 关键裁决多次采样 / 投票（M0 后） |
| 灵敏度分析 | 按 `importance_tier` 决定 tick 频率与审核强度 |
| 解耦控制 | `PlayerIntent` / `StageDirective` / `Fact` 三层解耦 |
| 分层管控 | 基座 / 扩展 / 导演 / 表现四层 |
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
| M0 | 双模式纵切：世界状态、GM、双总线、TurnLoop、authority + 模式切换、NPC 自主、Mod v1、存档、游戏前端 | 🔲 |
| M1 | 游戏前端、TFC、审核、媒体、Flag/Choice | 🔲 |
| M2 | 命运、Casting、路线图、POV、Belief 全量 | 🔲 |
| M3 | 视频、生成式媒体、TTS | 🔲 |
