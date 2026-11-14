# 章级大纲：ChapterPlan / SceneExpectation 设计

> 状态：待评审
> 日期：2026-11-13
> 关联：[outline.py](../src/storyloom/crews/scene_crew/outline.py) · [state.py](../src/storyloom/memory/state.py) · [narrative.py](../src/storyloom/engine/narrative.py) · [MVP.md](MVP.md)

---

## 1. 背景

当前大纲能力集中在 [`OutlinePlanner`](../src/storyloom/crews/scene_crew/outline.py)，它维护的是**运行时节奏快照**（`phase / tension_target / beats_remaining / info_budget`），按回合扣减节拍、阶段耗尽后自动循环。它没有章级计划，也不消费伏笔与记忆规划。

同时，导演提示词（[`_build_director_prompt`](../src/storyloom/engine/narrative.py#L1006)）只消费场景简报、记忆检索块与伏笔表，**章级意图并未真正进入导演**。

问题归纳为三点：

1. **职责混装**：章级计划、场景预期、运行时节奏塞在同一个帧结构里，无法各自演化；
2. **注意力无预算**：活跃伏笔与故事线全部平铺，导演每轮面对的信息量不随重要性收敛；
3. **缺少闭环**：生成完一场后，没有任何机制回答“这一场该发生的发生了吗、后面的预期是否失效”。

另外，命运系统在 [MVP.md](MVP.md) 的路线图中排在 M2（`FateThread` + 预兆 + 收束），`FateManager` 被明确为**确定性算法 + seed、不调用 LLM**（见 [MODEL_SELECTION.md](MODEL_SELECTION.md)）。本设计与命运系统共享同一个语义——“必须发生的事情”——因此需要在数据结构与投影层预留接入契约，否则 M2 接入时要改计划模型。

## 2. 目标与非目标

### 目标

- 大纲作为**低频、粗粒度、面向导演的长线注意力**：每章规划一次，每场投影一次，每场结算一次。
- 开启大纲时提供**命运倾向**：叙事债务按期推动，必要结果必须形成，信息揭露受限。
- 关闭大纲时保持**开放沙盒**：现有行为零改动。
- 计划与实际结果分离，可回看“原本想写什么 vs 实际写了什么”。

### 非目标

- 不做完整动态故事图调度（事件依赖图、自动选线）。
- 不在运行中改写已发生的事实；`FactOverride` 仍只属于作者显式操作（见 [MVP.md](MVP.md) M0-11）。
- 不把大纲做成硬剧本：约束落在**变化与必要结果**上，不规定角色台词与具体动作。
- 不做大纲强度滑块（只做开关，强度留给配置里的预算字段）。
- 不实现命运系统本体（`FateThread` / 预兆 / 收束判定归 M2），本设计只定义**只读接入契约**。
- 不覆盖 Casting、`RouteGraph` 多结局与日程系统。

## 3. 核心原则

1. **默认沙盒**：`outline_enabled` 默认 `False`，与当前行为完全一致。
2. **强约束只约束结果**：约束“必须形成的变化 / 不得发生的结果”，不约束路径。
3. **LLM 低频，运行时确定性**：规划与结算用 LLM；投影、预算扣减、指针推进、偏离计数全部用代码。
4. **预期只在场边界修订**：场中不改合同，避免导演边写边改目标。
5. **计划不改写历史**：结算只登记偏离与债务，不回写已发生事实。
6. **命运只读**：命运状态归 `FateManager`，章级计划只读 `FateRef` 快照，不回写压力与阶段。

## 4. 开关语义

`outline_enabled: bool = False`，属于**实例级运行配置**，挂在 `WorldState` 上随 checkpoint 保存；同一作品可以“命运驱动”与“开放沙盒”双开。

| 行为 | 开启：命运驱动 | 关闭：开放沙盒 |
|---|---|---|
| `ChapterPlan` | 章开始时生成或加载 | 不生成、不注入 |
| `SceneExpectation` | 作为本场合同进入导演帧 | 不提供 |
| 章内目标 | 主动推动，具备约束力 | 由玩家 / NPC 目标 / 世界事件自然形成 |
| 伏笔与承诺 | 安排推进窗口与回收顺序 | 正常记录，不预定回收 |
| ARC | 与场景预期联动 | 保留现有相位循环，仅作局部节奏建议 |
| 偏离计划 | 记录并累计债务，必要时重规划 | 无“偏离”概念 |
| 章节收束 | 满足 `end_conditions` 才结束 | 不自动收束 |

**强约束不等于强行改判。** 玩家躲开债主时，命运约束的是“债主必须在本章形成压力”，实现方式可以是追踪、书信、代理人，而不是把玩家的逃避改判成失败。

**大纲开关与命运开关相互独立。** `outline_enabled` 决定章级计划是否运行；命运系统使用 M2 的独立开关 `fate_enabled`。两者组合：

| 大纲 | 命运 | 运行形态 |
|---|---|---|
| 关 | 关 | 开放沙盒（当前行为） |
| 开 | 关 | 作者大纲驱动，命运倾向来自 `author_intent` 中的必要结果 |
| 开 | 开 | 命运压力参与选线与收束，章级计划负责章内投影 |
| 关 | 开 | 只保留世界级命运压力，不产生章内预期序列 |

大纲开启而命运关闭时，本章的“命运感”完全由 `required_outcomes` 提供；命运开启后，`FateManager` 的压力与收束窗口成为 `required_outcomes` 的额外来源，两者在投影层合并、不重复计数。

## 5. 数据结构

### 5.1 ChapterPlan

| 字段 | 类型 | 含义 |
|---|---|---|
| `chapter_id` | `str` | 对应章节 |
| `version` | `int` | 重规划递增，用于追踪与回放 |
| `status` | `draft / active / completed / abandoned` | 生命周期 |
| `author_intent` | `str` | 作者原始意图，AI 重规划不得覆盖 |
| `based_on_scene` | `int` | 制定计划时的场景序号，用于判断计划是否过期 |
| `source_refs` | `list[str]` | 依据的记忆 / 事实 / 伏笔 / 承诺稳定 ID |
| `fate_refs` | `list[FateRef]` | 本章相关命运线的只读压力快照，见 5.5 |

**章核心意图**

| 字段 | 类型 | 含义 |
|---|---|---|
| `chapter_goal` | `str` | 本章总体目标 |
| `dramatic_question` | `str` | 吸引读者继续读的戏剧问题 |
| `value_shift` | `ValueShift` | 章首到章尾的核心变化 |
| `stakes` | `str` | 失败或拖延的代价 |
| `closing_hook` | `str` | 章末希望留下的新问题、压力或余味 |

`ValueShift { axis: str, before: str, after: str }`。

**边界与约束**

| 字段 | 类型 | 含义 |
|---|---|---|
| `entry_conditions` | `list[str]` | 计划成立所需的前置处境 |
| `end_conditions` | `list[str]` | 本章可结束的可观察条件 |
| `required_outcomes` | `list[str]` | 命运约束：本章必须形成的结果 |
| `preferred_outcomes` | `list[str]` | 希望发生但允许被 emergent 事件替代 |
| `non_goals` | `list[str]` | 本章不负责解决的问题 |
| `forbidden_outcomes` | `list[str]` | 本章不得提前发生的结果 |

语义区分：`end_conditions` 判断“能不能结束”，`required_outcomes` 判断“是否完成叙事职责”，`non_goals` 是“不必做”，`forbidden_outcomes` 是“不能做”。

**长线注意力**

| 字段 | 类型 | 含义 |
|---|---|---|
| `focus_threads` | `list[ThreadFocus]` | 本章选择推进的故事线 |
| `focus_characters` | `list[str]` | 本章重点角色 |
| `max_new_questions` | `int` | 允许新增的大问题数，默认 1 |
| `max_major_reveals` | `int` | 允许的重要揭示数，默认 1 |
| `max_foreshadow_ops` | `int` | 重要伏笔操作预算，默认 1 |

`ThreadFocus`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `target_ref` | `str` | `foreshadow:fs_xxx` / `promise:prm_xxx` / `fate:ft_xxx` / `thread:*` |
| `kind` | `main_plot / character / relationship / foreshadow / promise / fate / mystery / world` | 故事线类型 |
| `intent` | `introduce / advance / reinforce / resolve / subvert / withhold` | 本章处理方式 |
| `priority` | `primary / secondary` | 主 / 辅注意力 |
| `required` | `bool` | 是否必须完成 |
| `rationale` | `str` | 为什么现在需要处理它 |

`withhold` 是一等意图：明确表达“这条线很急，但本章继续压着”。

**场景安排**

| 字段 | 类型 | 含义 |
|---|---|---|
| `scene_expectations` | `list[SceneExpectation]` | 预期场景序列，非强制剧本 |
| `scene_budget` | `int \| None` | 软场景预算，不作机械截止 |
| `allow_emergent_scenes` | `bool` | 是否允许插入计划外场景，默认 `True` |
| `max_emergent_scenes` | `int` | 连续计划外场景预算 |
| `active_expectation_id` | `str \| None` | 当前激活预期指针（运行时状态） |
| `settlement_log` | `list[SettlementRecord]` | 场后结算历史（仅追加） |

> `active_expectation_id` 与 `settlement_log` 是运行时字段：前者是确定性指针，后者只追加、不参与规划生成，用于区分“计划过什么”与“实际发生了什么”。

### 5.2 SceneExpectation

**定位与职能**

| 字段 | 类型 | 含义 |
|---|---|---|
| `expectation_id` | `str` | 预期 ID，不等于最终场景 ID |
| `ordinal` | `int` | 章内顺序 |
| `phase` | `setup / rising / climax / resolution` | 章级 ARC 位置 |
| `purpose` | `str` | 为什么需要这一场 |
| `required` | `bool` | 该场景职能是否可跳过 |
| `focus_characters` | `list[str]` | 重点角色 |
| `location_hint` | `str` | 地点建议，不强制改位置 |

**冲突与变化**

| 字段 | 类型 | 含义 |
|---|---|---|
| `entry_conditions` | `list[str]` | 场景开始需满足的处境 |
| `opposition` | `str` | 阻力来源 |
| `expected_changes` | `list[str]` | 期望发生的认知 / 关系 / 目标 / 局势变化 |
| `required_changes` | `list[str]` | 无论路径都必须保留的变化 |
| `exit_conditions` | `list[str]` | 可转场的可观察条件 |
| `skip_conditions` | `list[str]` | 该场景已无需发生的条件 |

**路径与失败容忍**

| 字段 | 类型 | 含义 |
|---|---|---|
| `preferred_outcome` | `str` | 默认最期待的结果 |
| `alternate_outcomes` | `list[str]` | 同样能完成职能的结果 |
| `failure_outcome` | `str` | 行动失败时仍能形成的有效变化 |
| `allow_emergent` | `bool` | 是否接受计划外事件改变路径 |
| `must_not_happen` | `list[str]` | 场景级禁令 |

**信息与伏笔**

| 字段 | 类型 | 含义 |
|---|---|---|
| `information_plan` | `list[InformationPlan]` | 本场释放的信息 |
| `conceal` | `list[str]` | 本场必须继续隐藏的信息 |
| `thread_intents` | `list[ThreadFocus]` | 预期推进的线 |

`InformationPlan { source_ref, viewer, depth: hint/partial/confirm, content, required }`。

`information_plan` 描述的是**导演意图**，实际进入角色上下文仍受 `visible_to` 约束（A15 语义不变）。

**节奏与余味**

| 字段 | 类型 | 含义 |
|---|---|---|
| `tone` | `str` | 场景基调 |
| `emotional_shift` | `str` | 如“戒备 → 短暂信任” |
| `tension_hint` | `float \| None` | 覆盖 ARC 张力基线 |
| `aftertaste` | `str` | 场景结束后希望留下的感受或疑问 |

### 5.3 叙事债务账本

`NarrativeDebtLedger` 统一管理伏笔之外的长期未决项：

| 字段 | 类型 | 含义 |
|---|---|---|
| `debt_id` | `str` | 债务 ID |
| `kind` | `foreshadow / promise / character_goal / relationship / question / world_event` | 债务类型 |
| `target_ref` | `str` | 指向伏笔、承诺、事实等稳定 ID |
| `urgency` | `float` | 0~1，越接近到期越高 |
| `importance` | `float` | 0~1，长期重要性 |
| `last_touched_scene` | `int` | 上次被推进的场景序号 |
| `due_window` | `str` | 建议推进窗口，如“本章内” |
| `status` | `open / advancing / settled / abandoned` | 状态 |

伏笔自身状态仍由现有状态机维护（`apply_foreshadow_ops`），账本只做**调度视图**，不复制真相，也不绕过 `visible_to`。

### 5.4 计划与结果分离

`SceneExpectation` 只保存“预期”，**不得**写入：实际正文、实际变化、玩家真实行动、偏离原因、完成度评价。这些属于 `SettlementRecord`：

| 字段 | 含义 |
|---|---|
| `scene_id / expectation_id` | 对应关系 |
| `status` | `fulfilled / partial / skipped / diverged` |
| `observed_changes` | 实际发生的变化 |
| `required_missed` | 未完成的必要变化 |
| `thread_ops_applied` | 实际推进的线 |
| `debt_updates` | 账本变更（经代码校验后落地） |
| `expectation_revisions` | 对后续预期的增量修订 |
| `created_at` | 结算时间 |

### 5.5 命运接入契约

命运系统本体（`FateThread`、压力计算、收束动画）不在本设计实现，章级计划只消费其**只读快照** `FateRef`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `fate_id` | `str` | 命运线 ID，对应 M2 `FateThread` |
| `theme` | `str` | 该线要表达的命题，如“逃避的代价终会追上” |
| `pressure` | `float` | 0~1，确定性压力值 |
| `stage` | `latent / foreshadowed / pressing / converged` | 命运阶段 |
| `current_omen` | `str` | 当前预兆的一句话描述 |
| `convergence_chapter` | `str \| None` | 收束窗口所在章，未定时为空 |

约定：

1. `FateRef` 是只读快照，规划、投影、结算均不得写回；
2. `pressure` 与 `stage` 只能由 `FateManager` 确定性更新（含 seed），LLM 不参与；
3. 收束（`converged`）是章级 `required_outcomes` 的来源之一，优先级高于普通叙事债务；
4. 预兆进入 `InformationPlan` 时固定 `depth=hint`，不得直接给 `confirm`；
5. 命运关闭（`fate_enabled=False`）时 `fate_refs` 为空，全部逻辑自然退化。

## 6. 开启时的生成逻辑

### 6.1 总生命周期

```
章开始 / 重规划触发
  └─ OutlineAgent 生成 ChapterPlan（1 次 kickoff，含全部 SceneExpectation）
       └─ 每场前：OutlinePlanner 确定性投影 → DirectorFrame（0 次 LLM）
            └─ 演出（perceive → adjudicate → _narrate → _advance_world，链路不变）
                 └─ 场后：确定性预检 →（需要时）SettlementAgent（≤1 次快模型）
                      └─ 账本更新 + 计划状态推进 → 命中重规划条件则回到顶部
```

LLM 频次：每章 1 次规划 + 每场最多 1 次结算，其余全为代码。

### 6.2 触发条件（全部确定性判定）

| 触发 | 判定 |
|---|---|
| 章开始 | `scene_count` 跨过章节边界（复用现有 `chapters` 归属），或 `active_plan is None` |
| 目标提前完成 | 结算判定全部 `required_outcomes` 已满足 |
| 重大事实改写 | 发生 `FactOverride` / rollback |
| 偏离超限 | 连续 `max_emergent_scenes` 场计划外，或连续 2 场 `diverged` |
| 章预算耗尽 | `scene_budget` 用完但 `end_conditions` 未满足 |

自动全量重规划**每章至多 1 次**，其余偏离走增量修订。

### 6.3 输入组装（按优先级，全部带稳定 ID）

1. `author_intent`：该章作者原文大纲，只读；
2. 命运线压力快照：`FateRef` 按 `pressure` 降序，`converged` / `pressing` 优先；命运未启用时为空；
3. 叙事债务账本：活跃伏笔、承诺、未解决冲突、读者问题、世界逼近事件，按 `urgency × importance` 排序取前 N；
4. 上一章收尾：`key_events` 层最近摘要 + 上章 `closing_hook` 是否兑现；
5. 世界当前处境：`WorldState` 快照（地点、在场角色、活跃 override）；
6. 卷级位置：本章在整卷 ARC 中的大阶段，决定章的张力基线。

### 6.4 输出校验与降级

- Pydantic 校验 `ChapterPlan`，硬上限：`scene_expectations ≤ 12`、`focus_threads ≤ 5`、`conceal ≤ 8`；
- 解析或校验失败 → **确定性降级计划**：
  - `chapter_goal = author_intent`；
  - `focus_threads` 由到期债务机械生成（`urgency` 最高 1 条 primary + 2 条 secondary）；
  - `required_outcomes = []`，`status = draft`；
- 降级计划仍走完整投影与结算，只是约束更弱；**任何情况下不阻塞游戏回合**。

## 7. 约束机制：四级梯度

约束按强度递进，且**永不直接改写已发生事实**。

| 级别 | 机制 | 时机 | 实现 |
|---|---|---|---|
| L1 提示 | 场景合同进入 `DirectorFrame.hints` | 每场 prompt | 确定性投影，零成本 |
| L2 引导 | 导演被指示“命运会找上门”：逃避债主 → 追踪 / 书信 / 代理人 | adjudicate | 提示词策略；NPC 提案可被计划播种议程 |
| L3 债务累积 | 未完成 `required_changes` → 登记债务，`urgency` 上升，下一场催办 | 结算后 | 确定性账本更新 |
| L4 回轨 | 连续偏离 / 预算耗尽 / 命运收束窗口到期 → 激活最近的 `required=True` 预期 + 全量重规划 | 场边界 | 确定性触发 |

### 7.1 预期激活

章开始时一次性生成整条预期序列，但**按条件激活，不按顺序盲走**：

1. 每场前检查下一未完成预期的 `entry_conditions`（粗判用 ID / 关键词匹配，精判交给结算 Agent）；
2. 满足 → 激活；
3. 不满足但命中 `skip_conditions` → 标记 `skipped`，指针前移；
4. 都不命中 → `allow_emergent_scenes` 且未超预算时为计划外场景；预算耗尽 → 强制激活最近的 `required=True` 预期。

**预期只在场边界修订**，场中不换合同。

### 7.2 forbidden_outcomes 的执行

不做生成前置拦截（避免阻塞与剧透式硬闸），改为：

1. 结算 Agent 判定是否触犯；
2. 触犯 → 本场标 `diverged`，后续预期注入补救意图（如“本章不得揭示债主”被破，重规划改为“把暴露转化为新的戏剧问题”）；
3. 作者模式额外提供“结算不合格 → 重跑本场”，复用现有单场景重跑。

### 7.3 conceal 是唯一前置硬约束

`conceal` 拼进导演提示词的禁令区，并延续 `visible_to` 过滤：计划只能引用导演可见的信息，秘密对无权角色永不出现。

### 7.4 命运收束

命运提供比普通叙事债务更硬的“未来约束”，但仍然只约束结果：

1. **触发**：`FateRef.stage == converged`，或 `convergence_chapter` 等于当前章且 `pressure` 超过阈值；
2. **转化**：收束写入本章 `required_outcomes`，并激活对应 `SceneExpectation`（`required=True`）；
3. **自由度**：只规定“必须发生什么”，不规定“怎么发生”，玩家仍可经不同路径抵达；
4. **不回溯**：收束只作用于未来，不修改已发生事实；
5. **人工闸门**：作者模式命中收束时，转 [CONTROL_THEORY.md](CONTROL_THEORY.md) 描述的 `human_review_gate`。

收束通过后，`FateManager` 自行把 `stage` 推到终态；章级计划只读取结果，不回写命运状态。

## 8. 投影到 DirectorFrame

扩展现有 [`OutlinePlanner.frame()`](../src/storyloom/crews/scene_crew/outline.py#L53-L71)，**接口签名不变**，`SceneCrew.adjudicate(frame=...)` 无感知：

```
frame = ARC 快照（phase / tension_target / beats_remaining / info_budget）
      + goal = chapter_goal + 当前预期 purpose
      + hints 追加：
          - 反对力量（opposition）
          - conceal 列表（“本场不得揭示：…”）
          - thread_intents（“准备强化 / 回收：fs_xxx”）
          - must_not_happen（场级禁令）
          - 债务催办（urgency 最高且超阈值的一条）
          - 命运压力（pressure 超阈值时：“<theme> 正在收束”）
          - 当前预兆（若有，按 hint 措辞）
```

- `tension_hint` 非空时覆盖 `_PHASE_TENSION` 基线；
- 命运压力给出张力下限：`tension_target = max(tension_target, 0.5 + 0.4 × pressure)`，无命运时该式不生效；
- `info_budget` 按 `information_plan` 中 `required` 项数归一化；
- 关闭大纲时 `frame()` 保持现有相位循环逻辑，一行不改。

## 9. 场后结算

### 9.1 确定性预检（先省调用）

`state_delta` 为空、无伏笔操作、本场预期无 `required_changes` → 直接记 `partial`，不调 LLM。

### 9.2 SettlementAgent

输入：本场 `SceneExpectation` + `state_delta` + 新事实 + 伏笔操作 + 压缩后的 prose 摘要。
输出（1 次 kickoff，Pydantic 校验）：

```
status: fulfilled / partial / skipped / diverged
observed_changes: [...]
required_missed: [...]
thread_ops_applied: [...]
debt_updates: [...]
expectation_revisions: [...]
fate_signals: [...]            # 如“玩家违背/顺应命运命题”，只提议
```

### 9.3 落地

- `debt_updates` 经代码校验后写入账本；
- 伏笔状态只能通过现有状态机 `apply_foreshadow_ops` 变更，结算只提议；
- `expectation_revisions` 仅在下一个场边界生效；
- `fate_signals` 交由 `FateManager` 确定性消费，结算不直接修改 `pressure` 或 `stage`。

## 10. 存储与存档

| 数据 | 位置 | 说明 |
|---|---|---|
| `outline_enabled` | `WorldState` | 实例级运行配置 |
| `chapter_plan` | `WorldState` | 含指针、版本、结算日志 |
| `narrative_debt` | `WorldState` | 叙事债务账本 |

均随 checkpoint 序列化，读档后计划、指针与账本一致（延伸 A4 语义）。`NovelProject` 只保留作者资产（章原文、伏笔），不承载运行计划。

命运线本体（`FateThread` / `pressure` / `stage`）由 M2 命运系统持有，本设计不复制、不落库；`chapter_plan.fate_refs` 只是制定计划时的快照，读档后由 `FateManager` 重新提供当前值。

## 11. 成本与降级

| 环节 | 频率 | 模型档位 | 失败降级 |
|---|---|---|---|
| ChapterPlan 生成 | 每章 1 次 | 强模型 | 确定性降级计划 |
| DirectorFrame 投影 | 每场 | 无 LLM | 不会失败 |
| 结算预检 | 每场 | 无 LLM | 自动 `partial` |
| SettlementAgent | 每场 ≤1 次 | 快模型 | 跳过结算，债务机械衰减 |
| 全量重规划 | 每章 ≤1 次 | 强模型 | 沿用现有计划，仅记账 |
| 命运压力计算 | 每场 | 无 LLM（`FateManager` 确定性 + seed） | 保持当前值，不阻断 |

关闭开关时：不生成、不注入、不结算，沙盒路径零改动。

## 12. 代码落点

| 文件 | 改动 |
|---|---|
| [`crews/scene_crew/outline.py`](../src/storyloom/crews/scene_crew/outline.py) | 新增 `ChapterPlan` / `SceneExpectation` / `ThreadFocus` / `InformationPlan` / `NarrativeDebtLedger`；扩展 `OutlinePlanner.frame()` 与 `advance()` 的大纲分支 |
| [`memory/state.py`](../src/storyloom/memory/state.py) | `WorldState` 增加 `outline_enabled` / `fate_enabled` / `chapter_plan` / `narrative_debt` |
| [`engine/narrative.py`](../src/storyloom/engine/narrative.py#L422-L550) | `play_turn` 的 arc 段接入投影；`_advance_world` 后接结算；`_build_director_prompt` 注入计划块 |
| [`crews/scene_crew/crew.py`](../src/storyloom/crews/scene_crew/crew.py#L331) | 无签名改动，`frame` 已支持 |
| `tests/` | 新增开关、降级、偏离、存档回放四组用例 |

> 命运接入只在 `outline.py` 定义 `FateRef` 与只读投影规则；`FateManager` / `FateThread` 的实现在 M2，本设计不引入依赖。`fate_enabled` 与 `outline_enabled` 同层，均为 `WorldState` 运行配置。

## 13. 验收

| # | 场景 | 预期 |
|---|---|---|
| O1 | 关闭开关跑现有 M0 用例 | 全量通过，输出无变化 |
| O2 | 开启后进入新章 | 生成 `ChapterPlan`，`scene_expectations` 非空且满足上限 |
| O3 | 规划 LLM 返回坏 JSON | 使用降级计划继续，回合不阻塞 |
| O4 | 玩家规避 `required_outcomes` | 债务 `urgency` 上升，下一场 hints 出现催办，事实不被改判 |
| O5 | 连续计划外场景超预算 | 激活 `required=True` 预期，最多触发 1 次全量重规划 |
| O6 | 结算发现触犯 `forbidden_outcomes` | 本场 `diverged`，后续预期被增量修订 |
| O7 | 存档 → 读档 | 计划、指针、账本一致，不重新生成 |
| O8 | 秘密信息被写入 `conceal` | 无权角色上下文不出现，A15 语义保持 |
| F1 | 大纲开、命运关 | 计划照常生成，`fate_refs` 为空，行为与无命运系统一致 |
| F2 | 命运开、大纲关 | 只保留世界级压力，不生成章内预期序列，回合链路不变 |
| F3 | 命运 `pressure` 升高 | `focus_threads` 排序与 `DirectorFrame.hints` 出现对应催办，张力不低于压力下限 |
| F4 | 收束窗口到期 | 收束写入 `required_outcomes` 并激活对应预期；只约束未来，不修改已发生事实 |

## 14. 后续可选（不在本次范围）

- 大纲强度配置（约束梯度默认档位）；
- 卷级 `VolumePlan` 与跨章债务调度；
- 作者模式计划可视化与手工编辑面板；
- 命运压力与预兆的调试面板（配合 M2 `FateManager`）；
- 动态故事图自动选线。

## 15. 实施规划

> 本文档只记录规划，尚未执行任何代码改动。按阶段推进，每个阶段独立可验收；默认关闭开关，沙盒路径零回归。

### 15.1 现状确认

| 结论 | 依据 |
|---|---|
| 大纲 Agent 入口已存在 | `SceneCrew.outline()`，[crew.py](../src/storyloom/crews/scene_crew/crew.py#L282-L289) |
| 导演 Agent 构建入口 | `SceneCrew.build_director()`，[crew.py](../src/storyloom/crews/scene_crew/crew.py#L207-L258) |
| 章节模型已有 `outline` 字段 | `ChapterRow`，[db/models.py](../src/storyloom/db/models.py#L188-L195) |
| 场景归属章节 | `assign_scene_to_chapter()` / `list_scenes_by_chapter()`，[repository.py](../src/storyloom/db/repository.py#L738-L765) |
| 回合接入点 | `play_turn()`，[narrative.py](../src/storyloom/engine/narrative.py#L382-L547) |
| 世界推进入口 | `_advance_world()`，[narrative.py](../src/storyloom/engine/narrative.py#L847-L909) |
| 命运系统 | `src/` 内无任何 `FateThread` / `FateManager` 实现，仅本设计预留契约 |

### 15.2 阶段 0：契约与开关（纯确定性）

**任务**

1. [outline.py](../src/storyloom/crews/scene_crew/outline.py) 新增：`ValueShift`、`ThreadFocus`、`InformationPlan`、`SceneExpectation`、`SettlementRecord`、`ChapterPlan`、`DebtItem`、`NarrativeDebtLedger`、`FateRef`。
2. [state.py](../src/storyloom/memory/state.py) 的 `WorldState` 增加 `outline_enabled=False`、`fate_enabled=False`、`chapter_plan=None`、`narrative_debt`。
3. `OutlinePlanner.frame()` 与 `advance()` 增加大纲分支；关闭时逐行保持现有逻辑。

**测试**：`tests/test_outline_plan.py`

- 默认值全部关闭；
- `WorldState` 序列化 round-trip，旧存档可加载；
- 关闭时 `frame()` 输出与当前一致（快照对比）。

**验收**：O1。

### 15.3 阶段 1：章计划生成

**任务**

1. 新增 `OutlinePlanner.plan_chapter(project, state, chapter_outline, memory_block)`，复用 `SceneCrew.outline()`。
2. 输入按 §6.3 组装，全部使用稳定 ID，列表先截断。
3. 输出 Pydantic 校验 + 硬上限；失败走确定性降级计划。
4. 章开始判定：复用章节归属；无章节信息时退回 `scene_budget`。
5. 计划写入 `WorldState.chapter_plan`。

**测试**

- O2：新章生成、上限校验；
- O3：坏 JSON 降级且回合不阻塞；
- 使用离线 LLM stub，不调真实模型。

**依赖**：阶段 0。

### 15.4 阶段 2：场边界投影与导演接入

**任务**

1. 场景前调用 `planner.begin_scene(state)`：推进 / 跳过预期、处理预算、返回当前 `SceneExpectation`。
2. 扩展 `OutlinePlanner.frame()`，把 `goal / opposition / conceal / thread_intents / must_not_happen / 债务催办` 投影进 `DirectorFrame`。
3. `play_turn()` 在构造 `arc_frame` 后叠加计划，函数签名不变。
4. `_build_director_prompt()` 仅在 `outline_enabled` 时追加计划块。

**测试**

- O4（部分）：`conceal` 进入 hints，且无权角色上下文不出现；
- F1 / F2 / F3：开关组合、压力催办与张力下限。

**依赖**：阶段 1。

### 15.5 阶段 3：场后结算

**任务**

1. `play_turn()` 在 `_advance_world()` 之后调用新增 `_settle_scene()`。
2. 确定性预检：`state_delta` 为空且无 `required_changes` → 直接记 `partial`。
3. SettlementAgent 输出校验；`debt_updates` 经代码落地，`fate_signals` 只传递。
4. 伏笔仍只走 `apply_foreshadow_ops`。
5. `expectation_revisions` 缓存到下一个场边界生效。

**测试**：O6；结算失败降级。

**依赖**：阶段 2。

### 15.6 阶段 4：重规划与回轨

**任务**

1. 实现 §6.2 的五个确定性触发；全量重规划每章至多 1 次。
2. 偏离计数、`max_emergent_scenes`、L4 强制激活。
3. 重规划保留 `author_intent`，`version` 递增。

**测试**：O5、O7（计划版本与指针）。

**依赖**：阶段 3。

### 15.7 阶段 5：存档 / 回放 / 对外可见

**任务**

1. 确认 checkpoint 自动包含新字段，旧存档缺字段使用默认值。
2. `/runtime/v1/game/{pid}/state` 返回计划摘要（只读）。
3. 前端暂不改造，仅保留字段。

**测试**：O7 全链路：存档 → 读档 → 不重新生成。

**依赖**：阶段 3。

### 15.8 阶段 6：命运契约落地（不含本体）

**任务**

1. `FateRef` 定义在 `outline.py`，不引入 `FateManager`。
2. 计划生成与投影读取 `fate_refs`，来源可由 extension / state 注入。
3. 收束转 `required_outcomes` 实现为纯函数。
4. 无命运时全部为空，逻辑自然退化。

**测试**：F1–F4，使用假 `FateRef`。

**依赖**：阶段 0，可与阶段 1–4 并行。

### 15.9 顺序与验证

```
阶段 0 → 阶段 1 → 阶段 2 → 阶段 3 → 阶段 4 → 阶段 5
              └→ 阶段 6（并行）
```

每阶段结束运行：

```bash
uv run pytest tests/test_outline_plan.py -q
uv run pytest tests/test_m0.py tests/test_chapter_structure.py -q   # 回归
uv run pytest -q                                                    # 全量
```

### 15.10 风险与对策

| 风险 | 对策 |
|---|---|
| `play_turn()` 已较长，继续内联会失控 | 新逻辑放 `OutlinePlanner` 与私有 async 方法，`play_turn()` 只加 3 处调用 |
| 计划块撑大导演 prompt | 硬上限 + 每场只注入当前预期，不注入整章 |
| 章边界判定不准 | 优先用章节归属，缺失时退回 `scene_budget`，不报错 |
| 旧存档不兼容 | 新字段全部有默认值，读档后计划为空即等同关闭 |
| 游戏模式被规划阻塞 | 规划 / 结算失败一律降级，不影响回合返回 |
| 与 M2 命运实现耦合 | 只保留 `FateRef` 只读入口，不 import 命运模块 |

### 15.11 建议的第一步

先完成阶段 0：代码量小、可完全离线验证，并先锁定数据结构，避免后续返工。

