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
| 7 | 一致性校验失败回退重试 | ✅ | `scene_flow.py` / `controlled_scene_flow.py` |
| 8 | 伏笔状态机（种植 / 强化 / 揭示 / 回收 / 颠覆） | ✅ | `models.py` + Flow 内 `apply_foreshadow_ops` |
| 9 | 多模型路由 + 自动降级 | ✅ | `llm/router.py` |
| 10 | 控制论质量管控 | ✅ | `control/` |
| 11 | 分层记忆 | ✅ | `memory.py` |
| 12 | Vue 作者工作台 | ✅ | `frontend/` |

### P1 — 创作体验（未完成，不阻塞 M0）

- 多场景上下文进 RAG（当前记忆只覆盖单次生成过程）；
- 伏笔状态流转 API（激活 / 回收 / 颠覆的显式接口）；
- 小说导出 Markdown / TXT；
- 成本与质量指标前端展示；
- Agent / Task 配置导入导出与跨项目复制。

> 这些属于作者模式的完善项，排在 M0 之后，与游戏模式基座并行推进。

---

## 2. 下一阶段 M0：动态文字世界基座

### 2.1 目标

一个**纯文本、单世界、游戏模式**的最小纵切，证明：

1. 玩家自由输入能被 GM 裁决并改变世界状态；
2. 世界状态可存档、读档、回放且一致；
3. 扩展包能改变世界行为（至少一个 `skill` + 一个 `mod`）；
4. 前端可玩，真实人能做测试评价。

### 2.2 范围

| # | 模块 | 必须交付 |
|---|---|---|
| M0-1 | `world/state.py` | `WorldState` + `Fact` + `CharState` + `LocationState` · 可序列化 · 支持 `state_delta` 合并 · 世界时间 |
| M0-2 | `world/game_master.py` | 在场校验 / 移动 + 旅行耗时 / 简单行动判定 · 输出结构化结果 |
| M0-3 | `runtime/` | `PlayerIntent` · `IntentRouter` · `StageDirective` · `TextAdapter` · 全部可 JSON 序列化 |
| M0-4 | `flows/turn_flow.py` | TurnLoop 七阶段 · **async** · retry ≤ N · 四个出口 · **超时控制** |
| M0-5 | `extensions/` | 统一 manifest · `ExtensionHost` · `skill` 注入 · `mod` 规则注册 · `policy`/`asset` 解析 · **per-instance 隔离** |
| M0-6 | `saves` | `SaveService` · 本地快照 + 回放（先文件，M0 后接 DB） |
| M0-7 | API（**全部 async**） | `POST /game/{pid}/turn` · `GET /game/{pid}/state` · `POST/GET /game/{pid}/saves` · `POST /extensions/resolve` |
| M0-8 | 前端扩展 | 游戏模式：对话框 / 选项 / backlog / 存档读取 |
| M0-9 | Demo | `examples/world_demo/`：1 skill + 1 map mod + 2 角色 / 2 地点 |
| M0-10 | 测试 | GM 裁决、`Fact` 过滤、存档回放、manifest 校验、导演模式回归 |

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
> 把 Step A 的 `/game/...` 端点重命名加 deprecation 标记即可，不重构架构。

### 2.4 明确不做（M0 期间）

- TFC 五档动态计算（固定 `L2`，接口预留）；
- Fate / Casting / 好感度 / 路线图；
- Belief 欺骗与误解（只做 `known_by` 过滤）；
- 审核策略执行（只留 `ModerationGate` 接口，默认 passthrough）；
- 图片 / 音频渲染（只解析 `asset` manifest）；
- 实时多人；
- 多模态。

### 2.5 验收

| # | 场景 | 预期 |
|---|---|---|
| A1 | 玩家「拔剑刺向国王」，护卫在场 | 护卫拦截，玩家入狱；位置 / 情绪 / 时间正确更新 |
| A2 | 玩家「瞬移到王宫」 | GM 拒绝，给出可行替代 |
| A3 | 玩家不在场的密室事实 | 不出现在玩家视图；狱卒不知道玩家早期经历 |
| A4 | 存档 → 读档 → 回放 | 文本与状态完全一致，不重新生成 |
| A5 | 关闭 style skill / 启用 map mod | 文风变化 / 旅行耗时生效；坏 manifest 被拒绝 |
| A6 | 导演模式生成场景 | 原 `scene_brief` 流程不回归，现有数据不受影响 |
| A7 | 前端游戏模式 | 对话框展示 StageDirective，玩家可输入行动，存档/读档可用 |

### 2.6 性能指标（M0 后压测）

| 指标 | 目标 |
|---|---|
| 单 turn P95 延迟 | ≤ 10s（含 LLM 调用） |
| 冷启动 | ≤ 3s |
| 单实例并发 turn 数 | ≥ 100 |
| 性能扩展 | 增加实例 ≈ 线性增加吞吐 |

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
| API | 项目 / 资产 / 场景 / 章节 | `/game/...` 三个端点 + `/extensions/resolve` · 全部 async | P0 |
| 前端 | 只有作者工作台 | 游戏模式：对话框 / 选项 / backlog / 存档 | P0 |
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

### 3.3 文档与实现对齐（已完成）

- `TECHNICAL.md`：修正过时描述；
- `ARCHITECTURE.md`：补充双模式与基座抽象；
- `README.md`：更新定位与当前状态；
- `CONTROL_THEORY.md` / `MODEL_SELECTION.md`：补充新架构下的角色定位。

---

## 4. 实施顺序

```
W1  world/ + saves          状态、裁决、快照
W2  runtime/ + TurnLoop     意图、指令、async 循环
W3  extensions + API        扩展宿主 + 端点（全部 async）
W4  前端游戏模式 + demo     可玩界面 + 示例世界
W5  tests + 压测 + docs     验收
```

W3 / W4 可并行。M0 完成的判定以 §2.5 七条验收全部通过 + §2.6 压测指标达标为准。

---

## 5. 非目标（M0 期间不做）

- 不做完整 mod 市场与沙箱；
- 不做实时多人；
- 不做视频生成；
- 不做特定 galgame 的全套演出；
- 不重构作者模式的 8 个 Agent；
- 不做云部署脚本（先本地 Docker Compose 跑通）。
