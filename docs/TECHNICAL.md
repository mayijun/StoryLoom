# 织章 StoryLoom — 技术细节

> 本文档汇集 README 之外的所有技术实现信息。
> 想了解项目原理请看 [README.md](../README.md)。

---

## ✅ 已实现功能

### 🤖 多 Agent 协作引擎（CrewAI）

| Agent | 职责 | 默认模型 | 灵敏度 |
|-------|------|---------|--------|
| 🎬 导演 director | 场景意图规划，间接引导而非操控角色 | DeepSeek V4 Pro | 🔴 CRITICAL |
| 🎭 主角 protagonist | 独立人格，基于动机自主行动 | Claude Sonnet | 🟠 HIGH |
| 👥 群演 ensemble | 多个次要角色共享 1 实例，压缩成本 | DeepSeek Flash | 🟢 LOW |
| 🎲 意外 surprise | 提出"预期之外、情理之中"的事件提案 | Claude Sonnet | 🟠 HIGH |
| 📌 伏笔 foreshadowing | 伏笔全生命周期管理 | DeepSeek V4 Pro | 🟠 HIGH |
| ✅ 一致性 consistency | 校验人设/时间线/设定冲突 | GPT-4o | 🔴 CRITICAL |
| ✍️ 润色 prose | 行动日志 → 文学化正式正文 | Claude Sonnet | 🟡 MEDIUM |
| 📋 大纲 outline | 章节级结构规划 | DeepSeek V4 Pro | 🟡 MEDIUM |

- **YAML 种子**：`crews/scene_crew/config/agents.yaml` + `tasks.yaml` 首次运行导入数据库，之后数据库是唯一事实来源
- **可配置**：每个项目可独立增删改 Agent / Task、调整执行顺序、启停

### 🔀 多模型路由 + 自动降级

- `config/model_config.yaml` 配置提供商与 Agent→模型映射，改配置不改代码
- 支持 DeepSeek / OpenAI / Anthropic / Ollama（本地）
- 主模型不可用时自动切到 fallback

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

显式状态机，解决长篇写作"伏笔遗忘"：

```
PLANTED ──→ REINFORCED ──→ ACTIVATED ──→ RESOLVED
 (埋下)       (强化暗示)     (触发揭示)     (完成回收)
                  └──→ SUBVERTED（与意外Agent联动的颠覆回收）
```

- 超时预警（超过 N 场景未提及）
- 密度控制（同时活跃伏笔上限）
- 伏笔 × 意外联动

### 🧠 分层记忆

- **CoreMemory**（直接拼入 prompt）：当前场景状态、最近 2~3 场景摘要、导演指令包
- **VectorMemory**（RAG，ChromaDB）：世界观设定 / 角色背景 / 历史章节

### 🎲 可控随机性

意外 Agent 提"合理但未被预期"的事件：5 种类型（角色/信息/环境/关系/时间）、
四重约束（合理/可追溯/有后果/节制）、冷却期、导演审批。

### 🗄️ 持久化与多项目隔离

- 三张表：`projects`（项目元数据）/ `agent_configs` / `task_configs`
- `agent_configs` / `task_configs` 对 `projects.project_id` 外键 `ON DELETE CASCADE`
- SQLite 默认（`data/storyloom.db`），设 `STORYLOOM_DATABASE_URL` 可切 PostgreSQL/MySQL
- SQLite 连接自动 `PRAGMA foreign_keys = ON`
- 旧库自动迁移（缺 `project_id` 列或缺外键 → 重建补全，数据不丢）

> ⚠️ 角色 / 场景 / 伏笔等**资产当前只存在引擎内存中，未落库**，服务重启后丢失。
> 见末尾「MVP 缺口」P0 项。

### 🌐 Web 界面（Vue 3 单页）

- 顶栏：项目选择 / 新建项目 / API 在线状态
- 左栏：**Agent · Task 双栏编辑**——增删改、拖拽排序、启停
- 主区：**场景剧场**——输入场景描述 + 选择在场角色 → 流式生成 → Agent 消息流 → 最终正文
- 右栏：**资产**——角色 / 场景 / 伏笔三标签

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
| 向量库 | ChromaDB |
| 数据库 | SQLite（默认）/ PostgreSQL / MySQL |
| 前端 | Vue 3 · Vite · Pinia · PrimeVue |
| 测试 | pytest（58 passed） |

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
│   │       ├── agents.py        # /api/agents?project_id=
│   │       ├── tasks.py         # /api/tasks?project_id=
│   │       ├── assets.py        # /api/characters · /locations · /foreshadowings
│   │       └── generation.py    # /api/generation/scene · /scene/stream
│   ├── db/
│   │   ├── models.py            # ProjectRow / AgentConfigRow / TaskConfigRow（含外键）
│   │   ├── base.py              # 引擎 + SQLite PRAGMA foreign_keys
│   │   ├── repository.py        # CRUD + 旧库迁移
│   │   ├── config_source.py     # CrewAI 配置描述符（从 DB 加载）
│   │   └── cli.py               # storyloom-config
│   ├── crews/scene_crew/
│   │   ├── crew.py              # @CrewBase SceneCrew
│   │   └── config/              # agents.yaml / tasks.yaml（种子）
│   ├── llm/                     # providers.py（ModelRegistry）+ router.py（自动降级）
│   ├── flows/                   # scene_flow.py / controlled_scene_flow.py
│   ├── control/                 # feedback_loop · robustness · hierarchy
│   ├── memory.py                # CoreMemory + SimpleRAGMemory
│   ├── models.py                # Character/Location/Foreshadowing/Surprise/NovelProject
│   └── config/model_config.yaml
├── frontend/                    # Vue 3 + Vite + Pinia
│   └── src/
│       ├── App.vue              # 单页三栏
│       ├── stores/              # project / agent / task / asset / generation
│       └── composables/useApi.ts
├── tests/
├── data/                        # SQLite（已 git 忽略）
└── app.py                       # 启动器
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
python -m storyloom.main_controlled     # 控制论增强版
```

---

## 🔌 API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 + 可用模型 |
| GET/POST/DELETE | `/api/projects/` | 项目列表 / 新建 / 删除（demo 不可删） |
| GET | `/api/projects/{id}` | 项目详情 |
| GET/POST/PUT/DELETE | `/api/agents/?project_id=` | Agent 配置 CRUD + 排序 |
| GET/POST/PUT/DELETE | `/api/tasks/?project_id=` | Task 配置 CRUD + 排序 |
| GET/POST/DELETE | `/api/assets/characters?project_id=` | 角色（内存） |
| GET/POST | `/api/assets/locations?project_id=` | 场景（内存） |
| GET/POST | `/api/assets/foreshadowings?project_id=` | 伏笔（内存） |
| POST | `/api/generation/scene` | 同步生成场景 |
| POST | `/api/generation/scene/stream` | 流式生成（SSE） |

---

## 🧪 测试

```bash
uv run pytest -q
```

覆盖：项目落库与外键、Agent/Task API、迁移与幂等回归、资产模型、记忆、控制论模块、Flow。

---

## 🎯 MVP 缺口（按优先级）

> 以下为尚未实现、要成为"可用小说生成器"所需的功能。

### P0 — 数据闭环
- **场景正文与生成历史落库**：建 `scenes` 表存 brief / prose / 质量分 / 耗时
- **章节/大纲结构**：书→卷→章→场景的层级组织与串联生成
- **资产落库**：角色/场景/伏笔写入数据库，解决重启丢失

### P1 — 创作体验
- 生成结果**人工编辑**与**单场景重跑**
- 小说**导出**（Markdown / TXT）
- 多场景**上下文衔接**（历史场景进 RAG）

### P2 — 完善
- 伏笔**状态流转** API（激活/回收/颠覆）
- 成本与质量指标**前端展示**
- Agent·Task 配置**导入导出/跨项目复制**
