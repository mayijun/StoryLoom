# 最小可行目标（MVP）

> 本文档是进度的唯一口径：
> 已完成的写在「当前阶段」，未完成的写在「差距清单」。
> 架构依据见 [ARCHITECTURE.md](ARCHITECTURE.md)。

---

## 1. 当前阶段：作者模式 MVP（已完成）

目标：把「输入场景描述 → 生成正文 → 落库 → 可回看/重跑」这条链路跑通。

### P0 — 数据闭环 ✅

| # | 能力 | 状态 | 落点 |
|---|---|---|---|
| 1 | 多项目管理 | ✅ | `projects` 表 + `/api/projects` |
| 2 | Agent / Task 可视化配置 | ✅ | `agent_configs` / `task_configs` + 前端双栏 |
| 3 | 角色 / 地点 / 伏笔落库 | ✅ | `characters` / `locations` / `foreshadowings` |
| 4 | 场景正文落库（brief / prose / 质量分 / 耗时） | ✅ | `scenes` 表 |
| 5 | 章节结构 + 场景归属 | ✅ | `chapters` 表 + `/chapters` `/scenes/{id}/chapter` |
| 6 | 场景编辑 / 删除 / 单场景重跑 | ✅ | `/scenes` 路由 |
| 7 | 一致性校验失败回退重试 | ✅ | `scene_flow.py` |
| 8 | 伏笔状态机（种植 / 强化 / 揭示 / 回收 / 颠覆） | ✅ | `models.py` + Flow 内 `apply_foreshadow_ops` |
| 9 | 多模型路由 + 自动降级 | ✅ | `llm/router.py` |
| 10 | 控制论质量管控 | ✅ | `control/` |
| 11 | 记忆基础版 | ✅ | `memory.py`（平铺 `CoreMemory` + Chroma；分层 v2 见 M0-14） |
| 12 | Vue 作者工作台 | ✅ | `frontend/` |

### P1 — 创作体验（未完成，不阻塞 M0）

- 伏笔状态流转 API（激活 / 回收 / 颠覆的显式接口）；
- 小说导出 Markdown / TXT；
- 成本与质量指标前端展示；
- Agent / Task 配置导入导出与跨项目复制。

> 原「多场景上下文进 RAG」已升级为 M0-14 分层记忆 v2，不再作为独立的 P1 项。
> 其余项属于作者模式的完善项，排在 M0 之后，与游戏模式基座并行推进。

---

## 2. 下一阶段 M0：双模式动态世界纵切（含分层记忆 v2）

### 2.1 目标

一次交付**游戏 / 扮演模式 + 导演模式共用同一 TurnLoop** 的纵切，证明六件事：

1. 玩家自由输入能被 GM 裁决并改变世界状态；
2. 导演指令能驱动同一个世界，改写事实带审计、快照与回滚；
3. 世界状态可存档、读档、回放且一致；
4. 扩展包能改变世界行为（至少一个 `skill` + 一个 `mod`）；
5. 前端可玩，真实人能做测试评价；
6. 记忆可分层、可压缩、可降级：短期记忆压缩进长期，冷记忆降级到检索库并可回温，历史场景可检索。

### 2.2 范围

| # | 模块 | 必须交付 |
|---|---|---|
| M0-1 | `world/state.py` | `WorldState` + `Fact` + `CharState` + `LocationState` + `ArcState` · 可序列化 · 支持 `state_delta` 合并 · 世界时间 |
| M0-2 | `world/game_master.py` | 在场校验 / 移动 + 旅行耗时 / 简单行动判定 · 输出结构化结果 · 地图只做 Tier 1 静态图 · `gap_policy`（`reject \| llm_referee \| human_review`） |
| M0-3 | `runtime/` | `PlayerIntent` · `IntentRouter` · `StageDirective` · `TextAdapter` · 全部可 JSON 序列化 |
| M0-4 | `flows/turn_flow.py` | 双模式 TurnLoop：`boot → perceive → classify_input → interpret_* → director_frame → actor_round → adjudicate → consistency_check → moderation_gate → render_scene → commit → plan_next` · **async** · retry ≤ N · 四个出口 · **超时控制** |
| M0-5 | `extensions/` | 统一 manifest · `ExtensionHost` · `skill` 注入 · `mod` 规则注册 · `policy`/`asset` 解析 · **per-instance 隔离** · 状态变更必须走 builtin handler，LLM 工具一律 `read_only` |
| M0-6 | `saves` | `SaveService` · 本地快照 + 回放（先文件，M0 后接 DB） |
| M0-7 | API（**全部 async**） | `POST /game/{pid}/turn` · `GET /game/{pid}/state` · `POST/GET /game/{pid}/saves` · `POST /extensions/resolve` · `PATCH/GET /api/projects/{pid}/memory` |
| M0-8 | 前端扩展 | 游戏模式：对话框 / 选项 / backlog / 存档读取 |
| M0-9 | Demo | `examples/world_demo/`：1 skill + 1 map mod + 2 角色 / 2 地点 |
| M0-10 | 测试 | GM 裁决、`Fact` 过滤、存档回放、manifest 校验、导演模式回归、记忆分层 / 压缩 / 降级、三后端检索 |
| M0-11 | `world/authority.py` | `GameAuthority` / `DirectorAuthority` 策略 · 模式切换 checkpoint · `FactOverride` 审计与回滚 |
| M0-12 | `narrative/arc.py` | 起承转合节拍 · 张力目标 · 信息预算 |
| M0-13 | `world/autonomous_agent.py` | NPC 记忆 → 反思 → 计划 → 提案 |
| M0-14 | `memory/` 分层记忆 v2 | 核心层 `working → short_term → long_term → canon`（层数可配）· 短期超阈值压缩进长期 · 长期低重要性且与活跃伏笔无关时降级到检索库 · 命中后可回温 · `fts` 默认 / `vector` / `hybrid` 同级可选 · 历史场景与资产回填 · 重启恢复 · `secrets` 可见性过滤 |

> M0-13 的 NPC 自主消费 M0-14 的分层记忆；M0-14 可与 W1/W2 并行，但必须在 NPC 自主之前完成。

#### M0-14 记忆 v2 的分层与生命周期

| 层 | 内容 | 进入 prompt | 持久化 |
|---|---|---|---|
| L0 `working` | 当前场景状态 / 地点 / 在场角色 / 本轮意图 | 总是 | 否 |
| L1 `short_term` | 最近 K 个场景的详细摘要 | 是 | 是 |
| L2 `long_term` | 压缩后的章节 / 桥段摘要 | 是 | 是 |
| L3 `canon` | 身份、世界规则、活跃伏笔、核心设定 | 是（pinned） | 是 |
| L4 `archive` | 环境、世界观、角色背景、已解决伏笔、被降级旧记忆 | 按需检索 | 是 |

- 短期超过 `max_items`（默认 6）→ 取最旧 batch 压缩为长期；
- 长期超过 `max_items`（默认 8）→ 压缩为 canon / arc；
- 长期重要性低于 0.35、连续 10 场景未命中、无活跃伏笔、非 pinned → 降级到 L4；
- 降级记忆被检索并采用 2 次 → 回温为 `long_term`；
- 检索后端 `fts` 默认，`vector` / `hybrid` 同级可选；无 embedding 时自动降级；
- 层数由 `memory_config.yaml` 的有序列表定义，可在短期与长期之间继续加层。

### 2.3 运行时架构预留（M0 就留对，不大手术）

这些不是 M0 要做的事，是**M0 必须设计成将来能做**的事：

| # | 预留点 | 做法 |
|---|---|---|
| 1 | Runtime 无状态 | `WorldState` 不持久化到 DB；每 turn 从请求体接收、返回 `state_delta` |
| 2 | 扩展包 per-instance | `ExtensionHost` 每个 `instance_id` 独立实例，不做类级缓存 |
| 3 | 所有 endpoint async | FastAPI async endpoint + LiteLLM `completion_async()` |
| 4 | TurnLoop 超时控制 | 每 turn 调用方可传 `max_duration_ms`，超时立即返回 `timeout` |
| 5 | 请求级配额 | bootstrap 传入 `max_turns / max_retries / max_cost`，超限立即拒绝 |
| 6 | 模型 Key 动态注入 | `bootstrap` 请求体传入 `provider_api_keys`，只在 Runtime 内存 |
| 7 | 结构化 JSON 日志 | 带 `instance_id / work_id / turn_id / trace_id` |
| 8 | API 版本化 | 端点路径带 `/v1/`，将来 v2 并行 |

> M0 验收通过后再加 `/runtime/v1/bootstrap` / `/runtime/v1/{instance_id}/turn` 等接口，
> 把 M0 的 `/game/...` 端点重命名并加 deprecation 标记即可，不重构架构。

### 2.4 明确不做（M0 期间）

- TFC 五档动态计算（固定 `L2`，接口预留）；
- Fate / Casting / 好感度 / 路线图；
- Belief 欺骗与误解（只做 `known_by` 过滤）；
- 审核策略执行（只留 `ModerationGate` 接口，默认 passthrough）；
- 图片 / 音频渲染（只解析 `asset` manifest）；
- Mod v2（Python 包 + `capabilities`，只预留接口）；
- 高级控制形式（多采样投票 / 趋势自适应）；
- 地图 Tier 2 / Tier 3（只做 Tier 1 静态图）；
- 记忆手动编辑器 / 层级可视化面板；
- 跨项目记忆共享；
- 实时多人；
- 多模态；
- 账号体系与部署运维不在本仓库范围。

### 2.5 验收

| # | 场景 | 预期 |
|---|---|---|
| A1 | 玩家「拔剑刺向国王」，护卫在场 | 护卫拦截，玩家入狱；位置 / 情绪 / 时间正确更新 |
| A2 | 玩家「瞬移到王宫」 | GM 拒绝，返回 `not_found` + 可去地点，给出叙事化替代 |
| A3 | 玩家不在场的密室事实 | 不出现在玩家视图；狱卒不知道玩家早期经历 |
| A4 | 存档 → 读档 → 回放 | 文本与状态完全一致，不重新生成 |
| A5 | 关闭 style skill / 启用 map mod | 文风变化 / 旅行耗时生效；坏 manifest 被拒绝 |
| A6 | 导演模式生成场景 | 原 `scene_brief` 流程不回归，现有数据不受影响 |
| A7 | 前端游戏模式 | 对话框展示 StageDirective，玩家可输入行动，存档/读档可用 |
| A8 | 导演改写已发生事实 | `FactOverride` 写入快照与审计；`rollback` 后世界状态一致 |
| A9 | 玩家静止 3 回合 | NPC 自发事件出现，且不越权改状态 |
| A10 | 游戏模式切导演模式（及反向） | 切换前落 checkpoint；切换后世界状态与记忆一致 |
| A11 | 连续生成超过短期上限（默认 6）的场景 | 短期记忆溢出并压缩为长期；重启后分层记忆恢复 |
| A12 | 低重要性长期记忆，连续 10 场景未命中且无活跃伏笔 | 自动降级到检索库；再次检索命中 2 次后回温 |
| A13 | 旧项目已有历史场景 | 索引自动回填；中文专名（如「航海图」）可检索到对应场景 |
| A14 | 切换 `fts` / `vector` / `hybrid` | 后端可切换；无 embedding 时 `vector` / `hybrid` 自动降级，生成不中断 |
| A15 | 角色 `secrets` | 只对本人可见；其他角色 prompt 不出现 |

### 2.6 性能指标（M0 后压测）

| 指标 | 目标 |
|---|---|
| 单 turn P95 延迟 | ≤ 10s（含 LLM 调用） |
| 冷启动 | ≤ 3s |
| 单实例并发 turn 数 | ≥ 100 |
| 记忆检索 P95 | ≤ 200ms（FTS，1k 文档/项目） |
| 性能扩展 | 增加实例 ≈ 线性增加吞吐 |

### 2.7 设计纪律

- **确定性优先**：能用代码确定性完成的不交给 LLM；GM、时间、随机、算术、配额都在代码层。
- **写状态只走一条路**：状态变更必须走 builtin handler；暴露给 LLM 的工具一律 `read_only`。
- **游戏模式零交互**：质量下降走兜底叙事并打质量标记，不阻塞玩家。
- **内化 vs 扩展**：可选的是玩法，不可选的是秩序；玩法进 `mod`，秩序留内核。
- **地图分级**：M0 只做 Tier 1 静态图，Tier 2/3 留到后续阶段。
- **记忆分层**：近期高保真、远期高压缩、冷记忆可召回、再命中可回温；关键记忆常驻，背景记忆按需检索。
- **遗忘不是删除**：低价值长期记忆降级到检索库，而不是直接丢弃；活跃伏笔与 pinned 记忆不降级。
- **检索库边界**：只承载环境、世界观、角色背景、已解决伏笔与被降级旧记忆；active 核心记忆不重复放入。
- **向量库是派生索引**：SQLite 是事实来源，索引可删除重建。
- **压缩可降级**：LLM 压缩失败时走确定性拼接 + 截断，不阻断生成。

---

## 3. 差距清单

### 3.1 基座（M0 必须补齐）

| 模块 | 现状 | 缺口 | 优先级 |
|---|---|---|---|
| 世界状态 | 只有 `NovelProject` 资产与 `scene_count` | `WorldState` / `Fact` / 时间 / 地点 / 角色状态 · 可序列化 | P0 |
| 裁决 | 只有一致性检查 | `GameMaster`：合法性、`state_delta`、`time_delta` | P0 |
| 输入 | `scene_brief` 字符串 | `PlayerIntent` + `IntentRouter` | P0 |
| 输出 | `prose` 字符串 | `StageDirective` + `StageRenderer` + `TextAdapter` · 可序列化 | P0 |
| 循环 | 一次性 `@start → @listen` 管道 | `TurnLoop` 回环 + 四个出口 + 上限保护 + async + 超时 | P0 |
| 扩展 | Agent/Task YAML 种子 | 统一 manifest + `ExtensionHost` + 四类扩展加载 · per-instance | P0 |
| 存档 | 无 | `SaveService`（快照 + 回放） | P0 |
| 信息隔离 | prompt 直接拼项目资产 | `view(agent_id)` 按 `known_by` 过滤 | P0 |
| 记忆生命周期 | 平铺 `CoreMemory` + Chroma；历史场景未回填 | 分层核心记忆 / 压缩 / 降级回温 / 三后端检索 | P0 |
| 记忆隐私 | `secrets` 未索引也未注入 | `visibility` + `include_private_for` | P0 |
| API | 项目 / 资产 / 场景 / 章节 | `/game/...` 端点 + `/extensions/resolve` · 全部 async | P0 |
| 前端 | 只有作者工作台 | 游戏模式：对话框 / 选项 / backlog / 存档 | P0 |
| 双模式策略 | 无 | `AuthorityPolicy` / 模式切换 checkpoint / `FactOverride` 回滚 | P0 |
| 叙事节拍 | 导演 prompt 内隐式 | `ArcState`：起承转合 + 张力目标 + 信息预算 | P0 |
| NPC 自主 | 群演被动响应 | `AutonomousAgent`：记忆 → 反思 → 计划 → 提案 | P0 |
| Demo | 无 | `examples/world_demo` | P1 |

### 3.2 游戏模式玩法（M1 / M2）

| 模块 | 缺口 | 阶段 |
|---|---|---|
| TFC | 五档动态计算 + 信号 | M1 |
| 审核 | `policy` pack + 规则 / 分类器 | M1 |
| 媒体 | 图片 / 音频资源调度 | M1 |
| Flag / Choice / Affection | 数值 + 选项效果 | M1 |
| 命运 | `FateThread` + 预兆 + 收束 | M2 |
| Casting | `extra / supporting / principal` + 配额 | M2 |
| 路线 | `RouteGraph` + 锁线 + 多结局 | M2 |
| 视角 | `POVController` + `Belief` 全量 | M2 |
| 多模态 | 视频 / 生成式媒体 / TTS | M3 |

### 3.3 文档与实现对齐（本次更新）

- `MVP.md`：M0 增补 M0-14 分层记忆 v2、A11–A15 与记忆纪律；P0 把「分层记忆」修正为「记忆基础版」；
- `ARCHITECTURE.md`：§5 改为「世界状态 + 分层记忆 + 检索库」，补记忆生命周期、三后端与角色视图边界；
- `TECHNICAL.md`：区分「已实现记忆」与「记忆 v2 设计目标」，补 2 张记忆表、配置与 API；
- `MODEL_SELECTION.md`：新增 `memory` 记忆压缩角色；
- `CONTROL_THEORY.md`：补记忆生命周期的分层控制 / 滞回说明；
- `README.md`：核心原理新增记忆分层，状态更新为「基础记忆已可用，v2 在 M0」。

---

## 4. 实施顺序

```
W1    步骤 1–2    Flow 骨架 + WorldState / GM / saves
W1.5  记忆 v2 基座  分层核心 + 压缩/降级/回温 + 持久化 + FTS + 历史回填
W2    步骤 3–5    双模式策略 + FactOverride 回滚 + 导演帧 / 节拍
W3    步骤 6–7    NPC 自主（消费分层记忆）+ Mod v1（YAML）
W4    API + 前端   /game/* async 端点 + 记忆后端切换 + 游戏模式界面
W5    测试 + 压测 + 文档   验收
```

依赖顺序为 W1 → W2 → W3 → W4 → W5；W1.5 可与 W1 / W2 并行，但必须在 W3 前完成；
W3 / W4 可并行。M0 完成的判定以 §2.5 十五项验收全部通过 + §2.6 压测指标达标为准。

---

## 5. 非目标（M0 期间不做）

- 不做完整的 mod 生态与沙箱；
- 不做实时多人；
- 不做视频生成；
- 不做特定 galgame 的全套演出；
- 不重构作者模式的 8 个 Agent；
- 不做云部署脚本（先本地 Docker Compose 跑通）；
- 不做高级控制形式（多采样投票 / 趋势自适应）；
- 不做地图 Tier 2 / Tier 3；
- 不做记忆手动编辑器 / 层级可视化面板；
- 不做跨项目记忆共享；
- 账号体系与部署运维不在本仓库范围。
