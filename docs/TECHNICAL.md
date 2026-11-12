# 织章 StoryLoom — 技术细节

> 本文档描述**当前已经实现**的技术细节。
> 架构与演进方向见 [ARCHITECTURE.md](ARCHITECTURE.md)，
> M0（双模式动态世界纵切 + 分层记忆 v2）已实现，验收见 `tests/test_m0*.py`。
> 后续阶段与差距见 [MVP.md](MVP.md)。

---

## ✅ 已实现功能

### 🤖 Crew 协作引擎（CrewAI）

Crew 是整个 StoryLoom 的核心协作单元，包含两种角色：

**LLM Agents**（需要模型调用）：

| Agent | 职责 | 默认模型 | 灵敏度 |
|-------|------|---------|--------|
| 🎬 导演 director | 场景意图规划，间接引导而非操控角色 | DeepSeek V4 Pro | 🔴 CRITICAL |
| 🎭 主角 protagonist | 独立人格，基于动机自主行动 | Claude Sonnet | 🟠 HIGH |
| 👥 群演 ensemble | 多个次要角色共享 1 实例，压缩成本 | DeepSeek Flash | 🟢 LOW |
| 🎲 意外 surprise | 提出「预期之外、情理之中」的事件提案 | Claude Sonnet | 🟠 HIGH |
| 📌 伏笔 foreshadowing | 伏笔全生命周期管理 | DeepSeek V4 Pro | 🟠 HIGH |
| ✅ 一致性 consistency | 校验人设/时间线/设定冲突 | GPT-4o | 🔴 CRITICAL |
| ✍️ 润色 prose | 行动日志 → 文学化正式正文 | Claude Sonnet | 🟡 MEDIUM |
| 📋 大纲 outline | 章节级结构规划 | DeepSeek V4 Pro | 🟡 MEDIUM |

**裁决与质量 Agents**（统一 JSON 输出，按段消费）：

| Agent | 职责 | 位置 |
|-------|------|------|
| 🎬 世界裁决（DirectorAgent） | 行动裁决：允许 / 拒绝 + `state_delta` | `crews/scene_crew/crew.py` |
| ✅ ConsistencyChecker | 冲突校验（确定性子检查 + LLM 语义辅助） | `crews/scene_crew/crew.py` |
| 🛡️ ModerationGate | 内容审核闸门 | 接口预留，默认 passthrough |

> 世界裁决由导演 Agent 输出统一 JSON 完成；没有模型时退化为最小自由叙事兜底。
> ExtensionHost 是 Crew 的 Tool Loader，把 mod/skill/policy 注册为 Crew 可用的工具。

- **YAML 种子**：`crews/scene_crew/config/agents.default.yaml` + `tasks.default.yaml` 首次运行导入数据库，
  之后数据库是唯一事实来源；
- **任务模板单一来源**：Flow 内的单 Agent 步骤直接 `Agent.kickoff()`，提示词按 key 从
  数据库 `task_configs` 读取（`task_prompt()` / `task_expected_output()`），与标准 Crew
  共用同一份 description / expected_output，避免两处各写一遍导致漂移；
- **迭代上限兜底**：无工具的单次创作 Agent 由 `AGENT_DEFAULTS` 收紧 `max_iter`
  （主角 6、群演 4、导演 6、大纲 8、一致性 6、润色 4、意外 6、伏笔 6），
  数据库里配置的同名字段优先；
- **可配置**：每个项目可独立增删改 Agent / Task、调整执行顺序、启停。

### 🔀 统一叙事引擎（NarrativeEngine）

- `src/storyloom/engine/narrative.py` 合并了原 `flows/scene_flow.py`（导演模式）与
  `flows/turn_flow.py`（游戏模式）的叙事链；
- 两个公开入口：`generate_scene()`（导演）与 `play_turn()`（游戏），
  内部共享 `_narrate()` 与 `_advance_world()`；
- `_narrate()` 是 2~3 次 LLM kickoff 的统一链：DirectorAgent JSON → 可选动态 Crew →
  ProseAgent，一致性 major 冲突按 `max_retries` 重试；
- `TurnLoop` / `SceneGenerationFlow` 仅作为兼容 shim，保留旧签名与 quota / timeout / trace；
- API 门面 `StoryEngine`（`api/engine.py`）负责项目、资产、存档、扩展，叙事委托 `NarrativeEngine`。

### 🔀 多模型路由 + 自动降级

- `src/storyloom/config/model_config.yaml` 配置提供商与 Agent→模型映射，改配置不改代码；
- 支持 DeepSeek / OpenAI / Anthropic / Ollama（本地）；
- 主模型不可用时自动切到 fallback。

### 🎛️ Flow 控制配置（前端）

控制不再是独立后端模块：灵敏度、采样次数与质量闸门作为 Flow 节点 / 连线参数维护，
位于 `frontend/src/components/flow/controls.ts`。调整控制策略 = 修改 Flow。

| 原理 | 实现 |
|------|------|
| 反馈闭环 | Flow 节点 `decision='feedback_loop'` + 导演裁决 / 一致性检查 / 审核闸门 |
| 统计滤波 | Flow 节点 `nSamples` / `decision='multi_sample'` |
| 整体优化 | `SceneCrew` 端到端质量评分与趋势追踪 |
| 灵敏度分析 | `AGENT_CONTROL_PROFILES` 按 Agent 风险等级分配控制策略 |
| 解耦控制 | 结构化中间格式防级联误差 |
| 分层管控 | Flow 图分层编排 Agent / 资产 / 控制节点 |
| 人机结合 | Flow 节点 `decision='human_review'` |

### 📌 伏笔生命周期管理

```
PLANTED ──→ REINFORCED ──→ ACTIVATED ──→ RESOLVED
 (埋下)       (强化暗示)     (触发揭示)     (完成回收)
                  └──→ SUBVERTED（与意外 Agent 联动的颠覆回收）
```

- 超时预警（超过 N 场景未提及）；
- 密度控制（同时活跃伏笔上限）；
- 伏笔 × 意外联动；
- 状态推进在 `engine/narrative.py` 的 `_advance_world()` 内完成。

### 🧠 记忆（分层 v2）

- **分层核心记忆**（`memory/core.py`）：`working → short_term → long_term → key_events`，
  `archive` 作为按需检索库；核心三层固定（层名受 `MemoryTier` 枚举约束），
  各层容量 / 压缩由 `tiers` 有序列表定义，降级 / 回温由 `demotion` 配置；
  默认种子来自 `src/storyloom/config/memory_config.default.yaml`，每个项目可独立覆盖；
- **按项目配置**：记忆配置落 SQLite `memory_configs` 表（`MemoryConfigRow`），
  新建项目时自动从 YAML 播种，旧项目首次读取或运行迁移脚本时补种；
  `GET /api/projects/{id}/memory` 返回生效中的 `settings`；`PATCH` 按字段更新，
  `key_events` / `demotion` / `retrieval` 递归合并、`tiers` 整体替换，合并结果经
  `MemorySettings` 校验后整体落库；`scripts/migrate_config_store.py` 可为已有项目补种或重置；
- **生命周期**：短期超 `max_items` 取最旧 `compress_batch` 条压缩进长期；
  长期超限压缩进 key_events；长期记忆与历史事件都可按各自阈值冷却到 archive：
  `demotion.long_term` / `demotion.key_events` 分别配置 `importance_threshold` 与
  `miss_scenes`（重要度低于阈值且连续 N 场景未命中，且非 pinned / 无活跃伏笔）；
  archive 命中 `reheat_hits` 次 → 回温为 long_term；
- **持久化**：SQLite `memory_items` 表（`db/models.py`），按 `project_id + id` 隔离；
  重启后自动恢复；作品数据是事实来源，索引可重建；
- **检索后端**：`fts`（默认，SQLite LIKE + 中文二元组打分）/ `vector`（需显式注入
  embedding，否则不可用）/ `hybrid`（RRF 融合，向量不可用时自动退化为 fts）；
- **历史回填**：`MemoryIndexer` 把旧项目场景与资产写入 archive，支持中文专名检索；
  已有分层场景时跳过场景回填，但仍从数据库刷新角色与地点资产，并清理已删除或改名的
  角色、秘密、地点条目（未传入的资产类别不参与清理）；
- **隐私**：`secrets` 以 `visibility=private:<角色>` 写入检索库，只对本人可见；
- **双模式共用**：导演模式与游戏模式使用同一个项目级 `LayeredMemory`；
  核心层通过 `prompt_block()` 注入，世界书通过 `retrieval_block()` 按需召回，
  正文落库后只写入一次；旧 `CoreMemory` / `SimpleRAGMemory` 与独立 Chroma 索引已移除。

```yaml
tiers:
  - name: short_term
    max_items: 6          # 短期记忆存量阈值
    compress_batch: 3     # 每次压缩几条进长期
  - name: long_term
    max_items: 8          # 长期记忆存量阈值
    compress_batch: 4     # 每次压缩几条进历史事件
demotion:
  long_term: { importance_threshold: 0.35, miss_scenes: 10 }
  key_events:     { importance_threshold: 0.30, miss_scenes: 20 }
  reheat_hits: 2
```

### 🎲 可控随机性

意外 Agent 提「合理但未被预期」的事件：5 种类型（角色/信息/环境/关系/时间）、
四重约束（合理/可追溯/有后果/节制）、冷却期、导演审批。

### 🗄️ 持久化与多项目隔离

SQLite 默认（`data/storyloom.db`），设 `STORYLOOM_DATABASE_URL` 可切 PostgreSQL/MySQL。

当前 9 张表（另有 M0 的 `memory_items`）：

| 表 | 作用 |
|---|---|
| `projects` | 项目元数据 |
| `agent_configs` | 每项目 Agent 配置 |
| `task_configs` | 每项目 Task 配置 |
| `memory_configs` | 每项目记忆层配置（tiers / key_events / demotion / retrieval） |
| `chapters` | 章节目录 |
| `scenes` | 已生成场景（brief / prose / 质量分 / 耗时 / 章节归属） |
| `characters` | 角色资产 |
| `locations` | 地点资产 |
| `foreshadowings` | 伏笔资产与状态 |

- `agent_configs` / `task_configs` / `memory_configs` 对 `projects.project_id` 外键 `ON DELETE CASCADE`；
- SQLite 连接自动 `PRAGMA foreign_keys = ON`；
- 旧库自动迁移（缺 `project_id` 列或缺外键 → 重建补全，数据不丢）。

M0 新增：

| 表 / 存储 | 作用 |
|---|---|
| `memory_items` | 分层记忆条目（层 / 重要性 / 命中 / 可见性 / 来源） |
| `data/saves/*.json` | Checkpoint 快照（WorldState + 渲染历史 + memory_snapshot，**已合并进 `memory/checkpoint.py`**） |

> `WorldState` 不落库：每回合由请求传入、返回 `state_delta`；
> 导演改写审计写在 `WorldState.overrides` 中，回滚只恢复被改字段。
> Checkpoint 与 `memory_items` 统一为 SessionState 的快照机制：
> 玩家手动存档、模式切换前自动 checkpoint、事实改写前快照，
> 都是 WorldState + Memory + 渲染历史的冻结状态，和分层记忆共用持久化后端。

### 🌐 Web 界面（Vue 3 单页）

- 顶栏：项目选择 / 新建项目 / API 在线状态；
- 左栏：Agent · Task 双栏编辑（增删改、拖拽排序、启停）；
- 主区：场景剧场（场景描述 + 在场角色 → 流式生成 → Agent 消息流 → 正文）；
- 右栏：资产（角色 / 地点 / 伏笔）；
- 场景历史与章节管理。

M0 新增游戏模式视图：对话框 / 选项 / backlog / 舞台指令 / 存读档 / 记忆后端切换，
位于 `frontend/src/components/GamePanel.vue`，由顶栏「🎮 游戏模式」打开。

### ⚙️ 配置 CLI

```bash
uv run storyloom-config list
uv run storyloom-config show agent director
uv run storyloom-config set agent director backstory "新的背景"
uv run storyloom-config set task prose_polish enabled false
uv run storyloom-config seed --overwrite
```

存储迁移与重置：

```bash
# 为已有项目补种记忆配置、同步任务模板（默认 dry-run）
uv run python scripts/migrate_config_store.py
uv run python scripts/migrate_config_store.py --apply

# 清空数据库 / 存档 / 向量库（默认交互确认）
uv run python scripts/reset_data.py --dry-run
```

#### 配置加载优先级

不同配置的来源不同，运行时从低到高遵循同一原则：**代码兜底 → YAML 种子 → 数据库**。

| 配置 | 1. 代码兜底 | 2. YAML 种子 | 3. 运行时权威 |
|---|---|---|---|
| Agent | `AGENT_DEFAULTS`（如 `max_iter`） | `agents.default.yaml` | 数据库 `agent_configs` |
| Task | `_DEFAULT_TASK_WIRING`（任务的 agent / context） | `tasks.default.yaml` | 数据库 `task_configs` |
| 记忆 | `MemorySettings` 内置默认值 | `memory_config.default.yaml` | 数据库 `memory_configs`（每项目一份） |
| 模型 | 路由兜底 `deepseek.flash`、temperature 0.8 | `model_config.yaml` | —（运行时直接读取，无数据库层） |

要点：

- **数据库非空字段优先**：`null` 字段不会覆盖代码兜底，例如 `max_iter` 为空时使用 `AGENT_DEFAULTS`；
- **种子只在首次生效**：项目还没有任何 Agent 行时才导入 YAML；已有项目改 YAML 不会自动生效，
  需 `storyloom-config seed --overwrite`、配置导入导出，或用迁移脚本（仅同步任务模板与记忆种子）；
- **记忆按项目覆盖**：新建项目自动播种，旧项目首次读取时补种；`PATCH` 写数据库，
  重置接口用 YAML 覆盖数据库；`STORYLOOM_MEMORY_*` 环境变量当前未接入；
- **模型是例外**：`model_config.yaml` 不落库，修改后需重启后端（或重建 registry）生效；
  环境变量只提供各 provider 的 API Key，不改变模型映射；
- **模型 Key 的优先级**：请求体 `provider_api_keys`（仅内存，进程内生效）> `.env` / 环境变量；
  两者都没有时该模型不可用；
- **基础设施配置**：`STORYLOOM_DATABASE_URL`、`STORYLOOM_SAVE_DIR`
  由环境变量读取，项目根目录 `.env` 在启动时加载。

---

## 🛠️ 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.10+ · FastAPI · SQLAlchemy 2 · Pydantic 2 |
| Agent 编排 | CrewAI（`@CrewBase` + Flow） |
| LLM | LiteLLM 统一适配 · DeepSeek / OpenAI / Anthropic / Ollama |
| 检索 | SQLite `memory_items` + LIKE / 中文二元组打分（`fts` 默认）；`hybrid` 做 RRF 融合 |
| 向量库 | 可插拔派生索引（`vector` 后端需显式注入 embedding；不可用时自动退化） |
| Embedding | 通过 `embedding_fn` 注入（OpenAI / Ollama 均可），未配置则 `vector` 不可用 |
| 数据库 | SQLite（默认）/ PostgreSQL / MySQL |
| 前端 | Vue 3 · Vite · Pinia · PrimeVue |
| 测试 | pytest |

---

## 📁 项目结构

```
StoryLoom/
├── src/storyloom/
│   ├── api/
│   │   ├── main.py              # FastAPI 入口 + CORS
│   │   ├── engine.py            # StoryEngine：项目/资产/存档/扩展 + 双模式门面
│   │   ├── schemas.py           # Pydantic 数据契约
│   │   └── routers/             # 版本化 API：/runtime/v1/* + /api/*
│   ├── engine/
│   │   └── narrative.py         # NarrativeEngine：generate_scene / play_turn
│   ├── db/                      # ORM + Repository
│   ├── crews/scene_crew/
│   │   ├── crew.py              # @CrewBase SceneCrew：Agent + 世界裁决 + NPC 自主
│   │   ├── packet.py            # 统一 Agent JSON 契约 + 场景装配
│   │   ├── outline.py           # 导演帧：起承转合 + 张力 + 信息预算（OutlineAgent 产出）
│   │   ├── tools.py             # Crew 工具（活跃伏笔查询等）
│   │   └── config/              # agents.default.yaml / tasks.default.yaml（种子）
│   ├── memory/
│   │   ├── models.py            # 资产模型 / 伏笔 / 意外 / NovelProject
│   │   ├── state.py             # WorldState + Fact + FactOverride + 裁决协议
│   │   ├── base.py              # MemoryItem / MemorySettings / MemoryTier
│   │   ├── core.py              # LayeredMemory：分层 / 压缩 / 降级 / 回温
│   │   ├── scoring.py           # 摘要 / 重要性评分 / 降级判定
│   │   ├── compress.py          # 压缩提示词 + 确定性兜底
│   │   ├── checkpoint.py        # CheckpointStore：快照 + 恢复
│   │   ├── lexical.py           # fts 后端
│   │   ├── vector.py            # vector 后端
│   │   ├── hybrid.py            # hybrid 后端
│   │   └── indexer.py           # 历史场景回填与资产刷新
│   ├── extensions/
│   │   ├── manifest.py          # manifest schema + 校验
│   │   └── host.py              # ExtensionHost = Crew 的 Tool Loader
│   ├── llm/                     # providers.py + router.py
│   ├── db/                      # ORM + Repository
│   ├── config/
│   │   ├── memory_config.default.yaml
│   │   └── model_config.yaml
│   └── templates/               # xianxia_system.py / sandbox_life.py + 内嵌扩展
├── frontend/                    # Vue 3 + Vite + Pinia
│   └── src/components/flow/controls.ts   # Flow 控制配置（灵敏度 / 采样 / 闸门）
├── scripts/
├── tests/
├── data/                        # SQLite（已 git 忽略）
└── app.py                       # 启动器
```

> 已完成的模块收敛：
> - `flows/` 整个目录已删除（`scene_flow.py` / `turn_flow.py` 两个 shim 彻底移除），叙事链全部走 `engine/narrative.py`
> - `world/game_master.py` / `world/authority.py` / `world/autonomous_agent.py` 已删除，职责分别并入 `SceneCrew.adjudicate` / `SceneCrew.npc_actions` / `WorldState`
> - `runtime/directive.py` / `runtime/renderer.py` 已删除，由 `crews/scene_crew/packet.py` 的 `compose_scene` 接管
> - `saves/service.py` → `memory/checkpoint.py`（`SaveService` 保留为 `CheckpointStore` 别名）
> - `api/engine.py` `NovelEngine` → `StoryEngine`（运行时门面）
> - `models.py` → `memory/models.py`：资产模型随世界状态一起归入 `memory/`
> - `world/state.py` → `memory/state.py`：世界状态与分层记忆统一为 `memory/` 的状态容器
> - `narrative/arc.py` → `crews/scene_crew/outline.py`：ARC 归入 OutlineAgent，导演帧作为 Crew 生成参数
> - `control/` 已删除：灵敏度 / 采样 / 闸门策略改为 `frontend/src/components/flow/controls.ts` 的 Flow 配置

---

## 🚀 快速开始

### 1. 安装依赖

```bash
uv sync --extra dev
```

### 2. 配置 API Key

```bash
cp .env.example .env
# 至少配置一个，系统会自动降级
DEEPSEEK_API_KEY=sk-xxx
# 可选
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-ant-xxx

# 记忆配置不走环境变量：默认种子见 src/storyloom/config/memory_config.default.yaml，
# 运行时按项目存于 memory_configs，通过
# PATCH /api/projects/{id}/memory 调整。
# 向量检索需要显式注入 embedding 函数；未注入时 vector 不可用，
# hybrid 会自动退化为 fts。
# Ollama 的 base_url 在 src/storyloom/config/model_config.yaml 的 providers.ollama 中配置
```

### 3. 启动后端

```bash
uv run uvicorn storyloom.api.main:app --reload --port 8000
```

### 4. 启动前端

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173
```

---

## 🔌 API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 + 可用模型 |
| GET/POST/DELETE | `/api/projects/` | 项目列表 / 新建 / 删除（demo 不可删） |
| GET | `/api/projects/{id}` | 项目详情 |
| GET/POST/PUT/DELETE | `/api/agents` | Agent 配置 CRUD + 排序（按 `project_id`） |
| GET/POST/PUT/DELETE | `/api/tasks` | Task 配置 CRUD + 排序（按 `project_id`） |
| GET/POST/DELETE | `/api/projects/{id}/assets/characters` | 角色资产 |
| GET/POST/DELETE | `/api/projects/{id}/assets/locations` | 地点资产 |
| GET/POST/DELETE | `/api/projects/{id}/assets/foreshadowings` | 伏笔资产 |
| POST | `/api/projects/{id}/assets/foreshadowings/{fid}/transition` | 伏笔状态显式流转（`reinforce / activate / resolve / subvert / abandon / replant`，非法流转 409） |
| POST | `/api/generate/scene` | 同步生成场景 |
| POST | `/api/generate/scene/stream` | 流式生成（SSE） |
| GET/PUT/DELETE | `/api/projects/{id}/scenes` | 场景列表 / 编辑 / 删除 |
| GET | `/api/projects/{id}/scenes/{scene_id}` | 场景详情 |
| PATCH | `/api/projects/{id}/scenes/{scene_id}/chapter` | 场景归属章节 |
| POST | `/api/projects/{id}/scenes/{scene_id}/regenerate` | 单场景重跑 |
| GET/POST/PUT/DELETE | `/api/projects/{id}/chapters` | 章节 CRUD |
| GET | `/api/projects/{id}/export?format=md\|txt` | 导出整本小说（按章节组织，附未归属场景），文件下载 |
| GET | `/api/projects/{id}/metrics` | 成本与质量指标：场景数 / 平均质量分 / 总与平均耗时 / 模型与 Agent 调用量 / 场景明细 |
| GET | `/api/projects/{id}/config/export` | 导出 Agent / Task 配置快照（JSON，不含库内字段） |
| POST | `/api/projects/{id}/config/import` | 导入配置（`merge` 逐条 upsert / `overwrite` 先清后写；overwrite 不允许空 Agent 列表） |
| POST | `/api/projects/{id}/config/copy_from` | 从同库另一项目复制配置（默认 overwrite） |
| GET | `/api/templates/` | 列出可用试用模板 |
| POST | `/api/templates/{template_id}/apply` | 应用模板生成可删除的普通项目 |

M0 已交付（**全部 async**）：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/game/{pid}/turn` | 提交一次玩家行动，返回演出指令 / 状态增量 |
| GET | `/game/{pid}/state` | 当前世界状态（玩家视图） |
| GET | `/game/{pid}/opening` | 生成开场（世界卡 + 初始选项） |
| POST/GET | `/game/{pid}/saves` | 创建存档 / 列出存档 |
| POST | `/game/{pid}/saves/{save_id}/load` | 读档并回放（不重新生成） |
| POST | `/game/{pid}/mode` | 切换游戏 / 导演模式（切换前落 checkpoint） |
| POST | `/extensions/resolve` | 解析并加载扩展包 manifest |
| GET | `/api/projects/{id}/memory` | 记忆层级、后端与生效配置（`settings` / `items` / `prompt_block`） |
| PATCH | `/api/projects/{id}/memory` | 按字段更新记忆配置（`key_events` / `demotion` / `retrieval` 递归合并，`tiers` 整体替换；`backend` 兼容旧写法） |

**版本化入口**：以上运行端点同时挂在 `/runtime/v1/*`（推荐新接入使用）：

| 方法 | 路径 |
|---|---|
| POST | `/runtime/v1/{pid}/turn` |
| GET | `/runtime/v1/{pid}/state` |
| GET | `/runtime/v1/{pid}/opening` |
| POST/GET | `/runtime/v1/{pid}/saves` |
| POST | `/runtime/v1/{pid}/saves/{save_id}/load` |
| POST | `/runtime/v1/{pid}/mode` |
| POST | `/runtime/v1/extensions/resolve` |
| GET/PATCH | `/runtime/v1/projects/{pid}/memory` |

旧 `/game/*` 与 `/extensions/resolve` 保留并标记 deprecated，M1 起逐步迁移。

**Key 注入**：回合请求体可带 `provider_api_keys`（如 `{"deepseek": "sk-..."}`），
仅注入运行时内存注册表，不写环境变量、不落盘、不回显。

---

## 🧪 测试

```bash
uv run pytest -q
```

覆盖：项目落库与外键、Agent/Task API、迁移与幂等回归、资产模型、场景与章节持久化、
分层记忆（LRU 淘汰 / 导演检索 / 历史回填 / 压缩阈值）、Flow 兼容层。共 **194 个用例**，
逐条清单见 [TESTS.md](TESTS.md)。

M0 覆盖（`tests/test_m0*.py` + `test_memory_compression.py`）：导演 Agent 裁决与守卫拦截、移动可达性、`Fact` 可见性、
存档回放、manifest 校验与 map mod 旅行覆盖、导演改写审计回滚、idle NPC 事件、
模式切换 checkpoint、记忆分层 / 压缩 / 降级回温 / 三后端检索 / 历史回填 / secrets、
自由文本输入、超时与配额、`/game/*` 与 `/memory` `/extensions` API、版本化入口与 Key 注入。

性能基线：

```bash
uv run python scripts/bench_m0.py
```

覆盖冷启动、确定性单 turn P95、并发 100 turn、1k 文档 fts 检索 P95；
不含真实 LLM 调用。

---

## 🎯 下一步

M0 双模式动态世界纵切已完成：`WorldState` / 导演 Agent JSON 裁决、自由文本输入 /
`StageDirective` 输出、双模式统一叙事引擎 `NarrativeEngine`、`FactOverride` 审计回滚、NPC 自主、
叙事节拍、分层记忆 v2 + Checkpoint、Mod v1 与 Checkpoint 回放均已落地，作者模式
`scene_brief → prose` 流程保持不回归。

已完成的架构收敛：
- **叙事链合并**：`flows/scene_flow.py` / `flows/turn_flow.py` 合并进 `engine/narrative.py`，旧 Flow 类保留为兼容 shim
- **裁决统一为 Agent JSON**：`SceneCrew.adjudicate` 调用导演 Agent，输出 `decision / state / available`，不再有确定性 GM 规则
- **SaveService → memory/checkpoint**：`saves/service.py` 合并进 `memory/`，Checkpoint 与分层记忆统一为 SessionState 快照机制
- **NovelEngine → StoryEngine**：`api/engine.py` 类名为 `StoryEngine`，表达「整个 StoryLoom 运行时入口」

下一阶段 M1 面向玩法与审核（详见 [MVP.md](MVP.md) §3.2）：

- TFC 五档动态计算与信号；
- `policy` pack：规则 / 分类器审核；
- 图片 / 音频资源调度；
- Flag / Choice / Affection 数值与选项效果；
- 章节边界与自动收束。
