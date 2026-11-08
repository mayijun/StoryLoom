# 织章 StoryLoom — 技术细节

> 本文档描述**当前已经实现**的技术细节。
> 架构与演进方向见 [ARCHITECTURE.md](ARCHITECTURE.md)，
> M0（双模式动态世界纵切 + 分层记忆 v2）已实现，验收见 `tests/test_m0*.py`。
> 后续阶段与差距见 [MVP.md](MVP.md)。

---

## ✅ 已实现功能

### 🤖 多 Agent 协作引擎（CrewAI）

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

- **YAML 种子**：`crews/scene_crew/config/agents.yaml` + `tasks.yaml` 首次运行导入数据库，
  之后数据库是唯一事实来源；
- **可配置**：每个项目可独立增删改 Agent / Task、调整执行顺序、启停。

### 🔀 多模型路由 + 自动降级

- `config/model_config.yaml` 配置提供商与 Agent→模型映射，改配置不改代码；
- 支持 DeepSeek / OpenAI / Anthropic / Ollama（本地）；
- 主模型不可用时自动切到 fallback。

### 🎛️ 系统控制论质量管控

| 原理 | 实现 |
|------|------|
| 反馈闭环 | 生成→批评→修正多轮（`control/feedback_loop.py`） |
| 统计滤波 | 多次采样 + 投票聚合 |
| 整体优化 | 端到端质量评分 |
| 灵敏度分析 | 按 Agent 风险等级分配采样次数与闭环强度（`control/robustness.py`） |
| 解耦控制 | 结构化中间格式防级联误差 |
| 分层管控 | Orchestrator 层级化管控（`control/hierarchy.py`） |
| 人机结合 | 关键节点人工审核闸门（接口预留） |

### 📌 伏笔生命周期管理

```
PLANTED ──→ REINFORCED ──→ ACTIVATED ──→ RESOLVED
 (埋下)       (强化暗示)     (触发揭示)     (完成回收)
                  └──→ SUBVERTED（与意外 Agent 联动的颠覆回收）
```

- 超时预警（超过 N 场景未提及）；
- 密度控制（同时活跃伏笔上限）；
- 伏笔 × 意外联动；
- 状态推进在 `scene_flow.py` 内完成。

### 🧠 记忆（分层 v2）

- **分层核心记忆**（`memory/core.py`）：`working → short_term → long_term → canon`，
  `archive` 作为按需检索库；层数由 `config/memory_config.yaml` 的有序列表定义；
- **生命周期**：短期超 `max_items` 取最旧 `compress_batch` 条压缩进长期；
  长期超限压缩进 canon；长期记忆与历史事件都可按各自阈值冷却到 archive：
  `demotion.long_term` / `demotion.canon` 分别配置 `importance_threshold` 与
  `miss_scenes`（重要度低于阈值且连续 N 场景未命中，且非 pinned / 无活跃伏笔）；
  archive 命中 `reheat_hits` 次 → 回温为 long_term；
- **持久化**：SQLite `memory_items` 表（`db/models.py`），按 `project_id + id` 隔离；
  重启后自动恢复；作品数据是事实来源，索引可重建；
- **检索后端**：`fts`（默认，SQLite LIKE + 中文二元组打分）/ `vector`（需显式注入
  embedding，否则不可用）/ `hybrid`（RRF 融合，向量不可用时自动退化为 fts）；
- **历史回填**：`MemoryIndexer` 把旧项目场景与资产写入 archive，支持中文专名检索；
- **隐私**：`secrets` 以 `visibility=private:<角色>` 写入检索库，只对本人可见；
- 旧的平铺 `CoreMemory` / `SimpleRAGMemory` 保留在 `memory/legacy.py`，作者模式继续使用。

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
  canon:     { importance_threshold: 0.30, miss_scenes: 20 }
  reheat_hits: 2
```

### 🎲 可控随机性

意外 Agent 提「合理但未被预期」的事件：5 种类型（角色/信息/环境/关系/时间）、
四重约束（合理/可追溯/有后果/节制）、冷却期、导演审批。

### 🗄️ 持久化与多项目隔离

SQLite 默认（`data/storyloom.db`），设 `STORYLOOM_DATABASE_URL` 可切 PostgreSQL/MySQL。

当前 8 张表：

| 表 | 作用 |
|---|---|
| `projects` | 项目元数据 |
| `agent_configs` | 每项目 Agent 配置 |
| `task_configs` | 每项目 Task 配置 |
| `chapters` | 章节目录 |
| `scenes` | 已生成场景（brief / prose / 质量分 / 耗时 / 章节归属） |
| `characters` | 角色资产 |
| `locations` | 地点资产 |
| `foreshadowings` | 伏笔资产与状态 |

- `agent_configs` / `task_configs` 对 `projects.project_id` 外键 `ON DELETE CASCADE`；
- SQLite 连接自动 `PRAGMA foreign_keys = ON`；
- 旧库自动迁移（缺 `project_id` 列或缺外键 → 重建补全，数据不丢）。

M0 新增：

| 表 / 存储 | 作用 |
|---|---|
| `memory_items` | 分层记忆条目（层 / 重要性 / 命中 / 可见性 / 来源） |
| `data/saves/*.json` | 存档快照（世界状态 + 已渲染指令 + 文本，不走 DB） |

> `WorldState` 不落库：每回合由请求传入、返回 `state_delta`；
> 导演改写审计写在 `WorldState.overrides` 中，回滚只恢复被改字段。
> `turn_logs` 与 `world_states` 表留到 M0 之后按需引入。

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
│   │   ├── engine.py            # NovelEngine：项目/资产运行时 + 场景生成桥接
│   │   ├── schemas.py           # Pydantic 数据契约
│   │   └── routers/
│   │       ├── projects.py      # /api/projects
│   │       ├── agents.py        # /api/agents
│   │       ├── tasks.py         # /api/tasks
│   │       ├── assets.py        # /api/projects/{id}/assets
│   │       ├── generation.py    # /api/generate
│   │       ├── scenes.py        # /api/projects/{id}/scenes
│   │       ├── chapters.py      # /api/projects/{id}/chapters
│   │       ├── config.py        # /api/projects/{id}/config（导入导出 / 跨项目复制）
│   │       └── runtime_v1.py    # /runtime/v1 版本化入口（复用 game/extensions/memory）
│   ├── db/
│   │   ├── models.py            # 当前 8 张表的 ORM 模型
│   │   ├── base.py              # 引擎 + SQLite PRAGMA foreign_keys
│   │   ├── repository.py        # CRUD + 旧库迁移
│   │   ├── config_source.py     # CrewAI 配置描述符（从 DB 加载）
│   │   └── cli.py               # storyloom-config
│   ├── crews/scene_crew/
│   │   ├── crew.py              # @CrewBase SceneCrew
│   │   └── config/              # agents.yaml / tasks.yaml（种子）
│   ├── llm/                     # providers.py + router.py
│   ├── flows/                   # scene_flow.py（导演模式单场景）
│   ├── control/                 # feedback_loop · robustness · hierarchy
│   ├── memory/                  # 分层记忆 v2 + 旧版兼容
│   │   ├── core.py              # LayeredMemory：分层 / 压缩 / 降级 / 回温
│   │   ├── lexical.py           # fts 后端（SQLite LIKE + 中文二元组）
│   │   ├── vector.py            # vector 后端（需显式注入 embedding）
│   │   ├── hybrid.py            # hybrid 后端（RRF 融合，向量不可用退化为 fts）
│   │   ├── indexer.py           # 历史场景 / 资产回填
│   │   └── legacy.py            # CoreMemory + SimpleRAGMemory（作者模式）
│   ├── models.py                # 资产模型 / 伏笔 / 意外 / NovelProject
│   ├── media/                   # render_adapter.py（表现层雏形）
│   └── config/model_config.yaml
├── frontend/                    # Vue 3 + Vite + Pinia
│   └── src/
│       ├── App.vue
│       ├── stores/              # project / agent / task / asset / generation
│       └── composables/useApi.ts
├── scripts/
│   └── bench_m0.py              # M0 性能基线压测
├── tests/
├── data/                        # SQLite（已 git 忽略）
└── app.py                       # 启动器
```

M0 已新增（均已实现）：

```
├── world/        # state.py · game_master.py · authority.py · autonomous_agent.py
├── runtime/      # intent.py · directive.py · renderer.py
├── extensions/   # manifest.py · host.py
├── narrative/    # arc.py
├── flows/        # scene_flow.py（导演模式） + turn_flow.py（双模式 TurnLoop）
├── saves/        # service.py（文件快照 + 回放）
├── config/memory_config.yaml    # 记忆层数 / 压缩 / 降级 / 检索后端
├── examples/                    # 扩展 manifest 扫描目录（可空）
├── templates/xianxia_system.py  # 试用模板：资产 + 内嵌 map/skill 扩展
└── frontend/src/components/GamePanel.vue   # 游戏模式面板
```

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

# 以下记忆 v2 选项通过 config/memory_config.yaml 与
# PATCH /api/projects/{id}/memory 配置；环境变量暂不读取

# 可选：记忆检索后端（fts / vector / hybrid），默认 fts
# STORYLOOM_MEMORY_BACKEND=fts
# 可选：向量后端 embedding（不配置则 vector 不可用，hybrid 自动退化为 fts）
# STORYLOOM_EMBEDDING_PROVIDER=openai
# STORYLOOM_EMBEDDING_MODEL=text-embedding-3-small
# 或 Ollama：
# STORYLOOM_EMBEDDING_PROVIDER=ollama
# STORYLOOM_EMBEDDING_MODEL=bge-m3
# OLLAMA_BASE_URL=http://localhost:11434
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

### 5. CLI 演示（可选）

```bash
python -m storyloom.main                # 基础版
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

M0 已交付（**全部 async**）：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/game/{pid}/turn` | 提交一次玩家行动，返回演出指令 / 状态增量 |
| GET | `/game/{pid}/state` | 当前世界状态（玩家视图） |
| POST/GET | `/game/{pid}/saves` | 创建存档 / 列出存档 |
| POST | `/game/{pid}/saves/{save_id}/load` | 读档并回放（不重新生成） |
| POST | `/game/{pid}/mode` | 切换游戏 / 导演模式（切换前落 checkpoint） |
| POST | `/extensions/resolve` | 解析并加载扩展包 manifest |
| GET | `/api/projects/{id}/memory` | 记忆层级与后端状态（只读调试） |
| PATCH | `/api/projects/{id}/memory` | 切换记忆检索后端（`fts` / `vector` / `hybrid`） |

**版本化入口**：以上运行端点同时挂在 `/runtime/v1/*`（推荐新接入使用）：

| 方法 | 路径 |
|---|---|
| POST | `/runtime/v1/{pid}/turn` |
| GET | `/runtime/v1/{pid}/state` |
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
记忆基础版、控制论模块、Flow。共 **176 个用例**，逐条清单见 [TESTS.md](TESTS.md)。

M0 覆盖（`tests/test_m0*.py`）：GM 裁决与守卫拦截、移动可达性、`Fact` 可见性、
存档回放、manifest 校验与 map mod 旅行覆盖、导演改写审计回滚、idle NPC 事件、
模式切换 checkpoint、记忆分层 / 压缩 / 降级回温 / 三后端检索 / 历史回填 / secrets、
意图路由、超时与配额、`/game/*` 与 `/memory` `/extensions` API、版本化入口与 Key 注入。

性能基线：

```bash
uv run python scripts/bench_m0.py
```

覆盖冷启动、确定性单 turn P95、并发 100 turn、1k 文档 fts 检索 P95；
不含真实 LLM 调用。

---

## 🎯 下一步

M0 双模式动态世界纵切已完成：`WorldState` / `GameMaster`、`PlayerIntent` /
`StageDirective` 双总线、双模式 `TurnLoop`、`FactOverride` 审计回滚、NPC 自主、
叙事节拍、分层记忆 v2、Mod v1 与存档回放均已落地，作者模式 `scene_brief → prose`
流程保持不回归。

下一阶段 M1 面向玩法与审核（详见 [MVP.md](MVP.md) §3.2）：

- TFC 五档动态计算与信号；
- `policy` pack：规则 / 分类器审核；
- 图片 / 音频资源调度；
- Flag / Choice / Affection 数值与选项效果；
- 章节边界与自动收束。
