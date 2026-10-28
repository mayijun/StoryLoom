<div align="center">

# 🧵 织章 StoryLoom

**多Agent协作 × 系统控制论 × 智能小说生成**

*Multi-Agent Collaboration × Systems Control Theory × Intelligent Novel Generation*

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![CrewAI](https://img.shields.io/badge/CrewAI-0.121+-green.svg)](https://crewai.com)
[![License](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](#-参与贡献)

[English](#english) | [中文](#中文)

</div>

---

<a name="中文"></a>

## 📖 项目简介

**织章 (StoryLoom)** 是一个基于多Agent协作架构的智能小说生成系统。
系统中每个Agent扮演不同角色——角色扮演者、导演、伏笔管理师、
意外策划师、一致性检测员、润色叙事者——它们各自调用最适合的AI模型，
通过系统控制论指导的反馈闭环、统计滤波与分层管控机制协同工作，
将"不完美的AI组件"组合为"足够好的创作整体"。

> "不追求单项技术的先进性，而追求设计总体的合理性。"
> —— 钱学森《工程控制论》

### 🎯 核心理念

传统AI写作 = 一个模型从头写到尾（开环系统）→ 误差累积、人设崩塌、伏笔遗忘

**织章** = 多个专业Agent分工协作（闭环系统）→ 反馈纠错、冗余校验、整体最优

```
单模型写作:    [用户输入] ──→ [GPT] ──→ [输出]          ← 开环，误差累积

织章系统:      [用户输入] ──→ [8类Agent协作] ──→ [输出]   ← 闭环，误差收敛
                                  ↑ 反馈 ↓ 校验
                             [控制论质量管控层]
```

---

## ✨ 核心特性

### 🤖 多Agent专业分工

| Agent | 职责 | 默认模型 | 灵敏度 |
|-------|------|---------|--------|
| 🎬 **导演Agent** | 场景意图规划，间接引导而非操控角色 | DeepSeek-V4-Pro | 🔴 CRITICAL |
| 🎭 **主角Agent** | 独立人格，基于动机自主行动 (1角色=1实例) | Claude Sonnet | 🟠 HIGH |
| 👥 **群演Agent** | 多个次要角色共享1实例，压缩成本 | DeepSeek-Flash | 🟢 LOW |
| 🎲 **意外Agent** | 提出"预期之外、情理之中"的事件提案 | Claude Sonnet | 🟠 HIGH |
| 📌 **伏笔Agent** | 管理伏笔全生命周期：种植→强化→回收→颠覆 | DeepSeek-V4-Pro | 🟠 HIGH |
| ✅ **一致性Agent** | 校验人设/时间线/设定冲突 | GPT-4o | 🔴 CRITICAL |
| ✍️ **润色Agent** | 行动日志 → 文学化正式正文 | Claude Sonnet | 🟡 MEDIUM |
| 📋 **大纲Agent** | 章节级/卷级结构规划 | DeepSeek-V4-Pro | 🟡 MEDIUM |

### 🔀 不同Agent调用不同AI

**每个Agent自动获得最适合它的AI模型：**

```yaml
# config/model_config.yaml
agent_model_mapping:
  director:      { primary: "deepseek.v4pro",           temperature: 0.7  }  # 强推理
  protagonist:   { primary: "anthropic.claude_sonnet",  temperature: 0.9  }  # 创意人格
  ensemble:      { primary: "deepseek.flash",           temperature: 0.7  }  # 便宜快速
  surprise:      { primary: "anthropic.claude_sonnet",  temperature: 0.95 }  # 发散创意
  foreshadowing: { primary: "deepseek.v4pro",           temperature: 0.5  }  # 精确追踪
  consistency:   { primary: "openai.gpt4o",             temperature: 0.2  }  # 结构化输出
  prose:         { primary: "anthropic.claude_sonnet",  temperature: 0.85 }  # 文学表现力
```

- **YAML驱动配置**，修改配置文件即可调整模型分配，无需改代码
- **自动降级**：当某AI提供商不可用时，自动切换到备选模型
- 支持 **DeepSeek / OpenAI / Anthropic / Ollama(本地)** 等多种后端

### 🎛️ 系统控制论质量管控

将钱学森《工程控制论》的7大原理应用于AI系统质量控制：

| 控制论原理 | 系统实现 | 效果 |
|-----------|---------|------|
| ① 反馈闭环 > 开环 | 生成→批评→修正多轮循环 | 每轮误差被纠正而非累积 |
| ② 统计滤波 | 多次采样 + 投票聚合 | 方差随采样数下降 |
| ③ 整体优化 > 局部最优 | 端到端质量评分 | 避免过度优化单个Agent |
| ④ 灵敏度分析 | 识别高杠杆Agent加强校验 | 资源精准投放 |
| ⑤ 解耦控制 | 结构化中间格式防级联 | 隔离误差传播 |
| ⑥ 分层大系统 | Orchestrator层级化管控 | 顶层统筹一致性 |
| ⑦ 人机结合 | 关键节点人工审核闸门 | 最后一道滤波器 |

```
🔴 导演Agent (CRITICAL)  → 反馈闭环 + 多次采样    ← 误差影响全局
🟠 主角Agent (HIGH)      → 反馈闭环              ← 误差影响情节
🟠 意外Agent (HIGH)      → 多次采样供导演选择      ← 误差影响体验
🟢 群演Agent (LOW)       → 单次直接通过           ← 误差影响有限
```

### 📌 伏笔生命周期管理

业界首创的**显式伏笔状态机**，彻底解决长篇写作中"伏笔遗忘"问题：

```
PLANTED ──→ REINFORCED ──→ ACTIVATED ──→ RESOLVED
 (埋下)       (强化暗示)     (触发揭示)     (完成回收)
                  │
                  └──→ SUBVERTED (颠覆：与意外Agent联动)
```

- **超时预警**：伏笔超过N个场景未被提及时自动提醒
- **密度控制**：同时活跃伏笔不超过设定上限
- **伏笔×意外联动**：以意外方式回收伏笔 = 最高级叙事手法

### 🎲 可控的随机性

意外Agent不是"掷骰子"，而是提出**"合理但未被预期"**的事件：

- **5种意外类型**：角色意外 / 信息意外 / 环境意外 / 关系意外 / 时间意外
- **四重约束**：合理性、可追溯性、后果性、节制性
- **冷却期机制**：防止每个场景都有意外导致读者疲劳
- **导演审批**：意外只是"提案"，导演有权否决

### 🧠 分层记忆架构

```
CoreMemory (核心记忆 → 直接拼入prompt)
├── 当前场景状态 (地点、在场角色、时间)
├── 最近2~3个场景摘要 (滚动压缩)
└── 导演当前指令包

VectorMemory (RAG记忆 → 按需检索)
├── 世界观设定 / 角色背景 (ChromaDB)
├── 历史章节全文
└── 按资产类型分collection，独立控制top_k
```

### 🔌 多模态渲染预留

结构化中间表示，未来无缝接入多模态生成：

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

| 渲染目标 | 适配器 | 状态 |
|---------|--------|------|
| 纯文本小说 | `TextOnlyAdapter` | ✅ 已实现 |
| 语音小说 (TTS) | `TTSAdapter` | 🔲 接口预留 |
| 插图 / 分镜 | `ImageAdapter` | 🔲 接口预留 |
| 短剧视频 | `VideoAdapter` | 🔲 接口预留 |

---

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        织章 StoryLoom 系统架构                       │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Layer 7: Web界面层                                           │  │
│  │  FastAPI + Streamlit | 项目管理 | 资产编辑 | 生成控制 | 历史回溯 │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Layer 6: 多模态渲染层                                         │  │
│  │  RenderAdapter → TextOnly / TTS / Image / Video               │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Layer 5: 控制论管控层 (SystemOrchestrator)                    │  │
│  │  灵敏度分析 | 反馈闭环 | 统计滤波 | 质量闸门 | 人机结合         │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Layer 4: 工作流编排层 (CrewAI Flow)                           │  │
│  │  SceneGenerationFlow: start → plan → act → check → write      │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Layer 3: Agent层 (SceneCrew + ModelRouter)                   │  │
│  │  Director | Protagonist | Ensemble | Surprise | Foreshadow   │  │
│  │  Consistency | Prose | Outline                                │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────┐  ┌────────────────────────────────────┐  │
│  │  Layer 2: 记忆层      │  │  Layer 2: 资产层                   │  │
│  │  CoreMemory (prompt)  │  │  CharacterAsset | LocationAsset   │  │
│  │  VectorMemory (RAG)   │  │  Foreshadowing  | LoreAsset       │  │
│  └──────────────────────┘  └────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Layer 1: 模型路由层 (ModelRegistry + AgentModelRouter)        │  │
│  │  DeepSeek | OpenAI | Anthropic | Ollama | 自动降级             │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Layer 0: 项目层 (NovelProject)                                │  │
│  │  多项目隔离 | 资产库 | 记忆实例 | 大纲树 | 历史记录              │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 场景生成 Pipeline

```
         ┌──────────────────────────────────────────────────┐
         │             Pre-Scene Planning                    │
         │                                                   │
         │  ┌──────────────┐    ┌────────────────────────┐  │
         │  │ 🎲 Surprise  │    │ 📌 Foreshadowing      │  │
         │  │    Agent     │───▶│    Agent               │  │
         │  │ (3次采样)    │    │ (反馈闭环)             │  │
         │  └──────────────┘    └────────────────────────┘  │
         └────────────────────────┬─────────────────────────┘
                                  │ 提案
                                  ▼
                        ┌──────────────────┐
                        │ 🎬 Director Agent│ ← 反馈闭环
                        │   综合裁决        │   (CRITICAL)
                        └────────┬─────────┘
                                 │ 场景意图包
                                 ▼
                   ┌─────────────────────────┐
                   │ 🎭 Protagonist / 👥 Ensemble │ ← 反馈闭环
                   │    自主角色扮演           │
                   └────────┬────────────────┘
                            │ 行动日志
                            ▼
                   ┌─────────────────────────┐
                   │ ✅ Consistency Checker  │ ← 多次采样投票
                   └────────┬────────────────┘
                            │ 通过 / 重试
                            ▼
                   ┌─────────────────────────┐
                   │ ✍️ Prose Writer         │ ← 反馈闭环
                   └────────┬────────────────┘
                            │ 正式正文
                            ▼
                   ┌─────────────────────────┐
                   │ 📈 End-to-End Evaluator │ ← 整体优化
                   │    质量趋势追踪          │
                   └─────────────────────────┘
```

---

## 📁 项目结构

```
StoryLoom/
│
├── pyproject.toml                 # 包定义：依赖 + 入口脚本（pip install -e .）
│
├── src/storyloom/
│   ├── __init__.py
│   ├── main.py                    # 基础版 CLI 入口 (python -m storyloom.main)
│   ├── main_controlled.py         # 控制论增强版 CLI 入口（实验性）
│   ├── models.py                  # 资产模型: Character/Location/Foreshadowing/Surprise
│   ├── memory.py                  # CoreMemory (prompt) + SimpleRAGMemory (ChromaDB)
│   │
│   ├── config/
│   │   └── model_config.yaml      # 模型配置：提供商 + Agent→模型映射
│   │
│   ├── llm/
│   │   ├── providers.py           # ModelRegistry + 统一适配层
│   │   └── router.py              # AgentModelRouter + 自动降级
│   │
│   ├── crews/                     # 🧩 CrewAI 官方约定 Crew
│   │   └── scene_crew/
│   │       ├── crew.py            # @CrewBase SceneCrew: 8种Agent + 标准任务序列
│   │       └── config/
│   │           ├── agents.yaml    # Agent 角色定义 (role/goal/backstory)
│   │           └── tasks.yaml     # 标准任务序列
│   │
│   ├── flows/
│   │   ├── scene_flow.py          # 基础版场景生成Flow
│   │   └── controlled_scene_flow.py  # 控制论增强版场景生成Flow
│   │
│   ├── control/                   # 🎛️ 系统控制论模块
│   │   ├── feedback_loop.py       # 原理①②③: 反馈闭环 + 统计滤波 + 端到端评估
│   │   ├── robustness.py          # 原理④⑤: 灵敏度分析 + 解耦校验
│   │   └── hierarchy.py           # 原理⑥⑦: 分层管控 + 人机结合
│   │
│   ├── media/
│   │   └── render_adapter.py      # 多模态渲染接口: Text/TTS/Image/Video
│   │
│   └── api/
│       ├── main.py                # FastAPI 入口
│       ├── engine.py              # CrewAI 引擎桥接
│       ├── schemas.py             # 前后端数据契约
│       └── routers/               # projects / agents / assets / generation
│
├── docs/
│   ├── ARCHITECTURE.md            # 详细架构文档
│   ├── CONTROL_THEORY.md          # 控制论原理详解
│   └── MODEL_SELECTION.md         # 模型选择指南
│
├── examples/
│   ├── minimal_demo.py            # 最小化Demo (仅需DeepSeek)
│   ├── multi_model_demo.py        # 多模型Demo
│   └── controlled_demo.py         # 控制论增强Demo
│
├── tests/
│   ├── test_assets.py
│   ├── test_memory.py
│   ├── test_control.py
│   └── test_flow.py
│
├── app.py                         # Web 模式启动器（默认入口）
├── requirements.txt
├── .env.example
├── LICENSE
└── README.md
```

---

## 🚀 快速开始

### 环境要求

- Python 3.10+
- 至少一个AI提供商的API Key

### 安装

```bash
# 克隆项目
git clone https://github.com/yourname/storyloom.git
cd storyloom

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 安装依赖（requirements.txt 会以 editable 模式安装项目本体及全部依赖，
# 依赖的单一来源是 pyproject.toml）
pip install -r requirements.txt
# 也可以分开执行：
# pip install -e .
# pip install pytest
```

> Windows PowerShell 若提示"禁止运行脚本"，先执行：
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### 配置API密钥

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
# 至少配置一个（系统会自动降级）
DEEPSEEK_API_KEY=sk-your-deepseek-key

# 可选：配置多个以发挥多模型优势
OPENAI_API_KEY=sk-your-openai-key
ANTHROPIC_API_KEY=sk-ant-your-anthropic-key
```

### 运行Demo

```bash
# 最小化Demo（仅需DeepSeek API Key）
python examples/minimal_demo.py

# 多模型Demo（配置多个API Key后效果最佳）
python examples/multi_model_demo.py

# 基础版 CLI 演示
python -m storyloom.main

# 控制论增强版（完整体验）
python -m storyloom.main_controlled
```

> `pip install -e .` 之后也可以直接使用入口脚本 `storyloom` /
> `storyloom-controlled`（见 pyproject.toml 的 [project.scripts]）。
>
> 项目采用 CrewAI 官方约定的 src/ 包布局：Crew 用 `@CrewBase` + 同级
> `config/agents.yaml`、`config/tasks.yaml` 定义；Flow 基于
> `crewai.flow`（Pydantic 结构化状态 + `@start`/`@listen`/`@router`
> 装饰器），因此支持 `crewai flow plot` 风格的 Flow 结构可视化，
> 以及 `crewai` CLI 对项目的标准识别。

### 预期输出

```
=================================================================
🤖 Agent → 模型分配表
=================================================================
  director        → deepseek.v4pro                  ✅
  protagonist     → anthropic.claude_sonnet          ✅
  ensemble        → deepseek.flash                   ✅
  surprise        → anthropic.claude_sonnet          ✅
  foreshadowing   → deepseek.v4pro                   ✅
  consistency     → openai.gpt4o                     ✅
  prose           → anthropic.claude_sonnet          ✅
=================================================================

🎛️  系统灵敏度分析
  🔴 director          采样=2次 闭环=✅
  🟠 protagonist       采样=1次 闭环=✅
  🟠 surprise          采样=3次 闭环=❌
  🟢 ensemble          采样=1次 闭环=❌

🎬 开始生成场景...

  📊 统计滤波: 3个采样, 选择版本2 (分数0.85)
  🔄 反馈闭环 第1轮: 评分=0.65 ❌
  🔄 反馈闭环 第2轮: 评分=0.82 ✅
  📊 一致性投票: 2/2通过 → ✅
  🌱 新伏笔已种下: 阿泽手腕纹身与姐姐照片吻合

  📈 端到端质量评分: 0.81

============================================================
📖 最终正文
============================================================
（AI生成的小说段落……）
```

---

## ⚙️ 配置指南

### 模型配置 (`config/model_config.yaml`)

```yaml
# 注册AI提供商
providers:
  deepseek:
    api_base: "https://api.deepseek.com"
    env_key: "DEEPSEEK_API_KEY"
    models:
      flash: { model_id: "deepseek/deepseek-flash", cost_per_1k_tokens: 0.001 }
      v4pro: { model_id: "deepseek/deepseek-v4-pro", cost_per_1k_tokens: 0.01 }

  openai:
    api_base: "https://api.openai.com/v1"
    env_key: "OPENAI_API_KEY"
    models:
      gpt4o: { model_id: "openai/gpt-4o", cost_per_1k_tokens: 0.005 }

  anthropic:
    api_base: "https://api.anthropic.com"
    env_key: "ANTHROPIC_API_KEY"
    models:
      claude_sonnet: { model_id: "anthropic/claude-sonnet-4-20250514", cost_per_1k_tokens: 0.003 }

  ollama:                          # 本地模型，免费
    api_base: "http://localhost:11434"
    models:
      qwen3_8b: { model_id: "ollama/qwen3:8b", cost_per_1k_tokens: 0.0 }

# Agent → 模型映射（可随时调整）
agent_model_mapping:
  director:      { primary: "deepseek.v4pro",          fallback: "deepseek.flash" }
  protagonist:   { primary: "anthropic.claude_sonnet", fallback: "deepseek.v4pro" }
  ensemble:      { primary: "deepseek.flash",          fallback: "ollama.qwen3_8b" }
  surprise:      { primary: "anthropic.claude_sonnet", fallback: "deepseek.v4pro" }
  foreshadowing: { primary: "deepseek.v4pro",          fallback: "openai.gpt4o" }
  consistency:   { primary: "openai.gpt4o",            fallback: "anthropic.claude_haiku" }
  prose:         { primary: "anthropic.claude_sonnet", fallback: "deepseek.v4pro" }
```

### 成本预估

| 场景 | API Key配置 | 单场景成本 | 说明 |
|------|------------|-----------|------|
| 💰 最低成本 | 仅DeepSeek | ~¥0.05 | 全部Agent用DeepSeek-Flash |
| ⚖️ 平衡方案 | DeepSeek + OpenAI | ~¥0.15 | 关键Agent用GPT-4o |
| 🏆 最高质量 | 全部配置 | ~¥0.50 | 每个Agent用最优模型 |
| 🆓 完全免费 | Ollama本地 | ¥0.00 | 质量取决于本地模型能力 |

---

## 📚 使用场景

> 下方的 `StoryLoom` 高层封装 API 属于 **Phase 2 规划**。
> Phase 1 请直接使用 `SceneGenerationFlow` / `ControlledSceneFlow`（参见 `main.py` 与 `main_controlled.py`）。

### 场景1：交互式小说创作

```python
from storyloom import StoryLoom

loom = StoryLoom.from_config("config/model_config.yaml")
project = loom.create_project(
    title="雾中旅人",
    style="克制、悬疑",
    characters=[...],
)

# 逐场景生成，用户可以在每个场景后调整方向
for i in range(10):
    scene = loom.generate_scene(
        project,
        brief=input("请描述下一个场景的大致方向: "),
    )
    print(scene.prose)

    # 查看伏笔状态
    loom.print_foreshadowing_status(project)
```

### 场景2：批量生成章节

```python
# 从大纲批量生成
outline = loom.generate_outline(project, n_chapters=10)
for chapter in outline.chapters:
    for scene_brief in chapter.scene_briefs:
        scene = loom.generate_scene(project, brief=scene_brief)
        project.append_scene(scene)

# 导出完整小说
project.export("output/雾中旅人.md")
```

### 场景3：动态交互游戏（未来）

```python
# 用户实时选择分支 → 动态生成不同走向
scene = loom.generate_scene(project, brief="...")
choices = scene.get_branch_choices()  # AI生成的分支选项
user_choice = get_user_input(choices)
next_scene = loom.generate_scene(project, brief=user_choice)
```

---

## 🧪 控制论实验对比

| 指标 | 无控制论 (v1) | 有控制论 (v3) | 提升 |
|------|-------------|-------------|------|
| 角色一致性 | 0.62 | 0.85 | +37% |
| 情节逻辑性 | 0.58 | 0.80 | +38% |
| 伏笔回收率 | 30% | 85% | +183% |
| 单场景API调用数 | 6 | 14 | +133% |
| 单场景成本 | ¥0.08 | ¥0.25 | +213% |
| **质量/成本比** | **7.75** | **3.40** | — |

> **结论**：控制论增强版用约3倍成本换取了约37%的质量提升。
> 用户可通过 `model_config.yaml` 中的 `strategy.mode` 在
> `cost_optimized` / `balanced` / `quality_first` 间切换。

---

## 🗺️ 路线图

```
Phase 1 — 核心引擎 ✅
  ✅ 多Agent协作架构 (CrewAI Flow + Crew)
  ✅ 多模型路由 + 自动降级
  ✅ 伏笔生命周期管理
  ✅ 意外事件可控生成
  ✅ 系统控制论质量管控 (7大原理)
  ✅ 分层记忆 (CoreMemory + RAG)

Phase 2 — 产品化 🔲
  🔲 Web界面 (FastAPI + Streamlit/Next.js)
  🔲 多项目管理 + 资产库
  🔲 多场景/章节串联生成
  🔲 生成历史回溯 + 分支重跑
  🔲 SQLite/Postgres 持久化

Phase 3 — 多模态 🔲
  🔲 TTS语音小说 (Fish-TTS / CosyVoice)
  🔲 插图生成 (DALL-E / Midjourney)
  🔲 短剧视频 (Seedance / Kling)
  🔲 结构化中间表示 → 多渲染器

Phase 4 — 交互式 🔲
  🔲 实时分支选择 → 动态交互叙事
  🔲 多人协作创作
  🔲 读者反馈驱动情节调整
  🔲 游戏引擎集成 (Unity/Godot)
```

---

## 🤝 参与贡献

欢迎所有形式的贡献！

1. **Fork** 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送分支 (`git push origin feature/amazing-feature`)
5. 创建 **Pull Request**

### 特别欢迎

- 🌐 新的AI模型适配器 (Gemini, Llama, Mistral...)
- 🎨 多模态渲染器实现 (TTS, Image, Video)
- 📊 更多控制论算法 (PID控制, 卡尔曼滤波...)
- 🧪 质量评估基准测试
- 🌍 多语言支持
- 📖 文档改进与教程

---

## 📄 开源协议

本项目采用 **GNU General Public License v3.0 (GPL v3)** 开源协议。
项目著作权由 [Ma Yijun](mailto:ma.yijun@outlook.com) 保留。

你可以自由地复制、修改、分发本项目，但衍生作品必须以相同协议开源，
且必须保留原始版权声明。详见 [LICENSE](LICENSE) 文件。

---

## 🙏 致谢

### 理论基础
- **钱学森**《工程控制论》(1954) — 系统控制论核心思想
- **钱学森** 开放的复杂巨系统理论 — "人机结合综合集成法"

### 学术参考
- **StoryWriter** (清华KEG, 2025) — 多Agent故事评估体系
- **Showrunner Agents** (Fable Studio, 2024) — 戏剧算子注入机制
- **CreAgentive** — 知识图谱式伏笔约束
- **BookWorld** (2025) — 从小说构建角色Agent社会
- **MAGNET + ATLAS** (2025) — 批评Agent + 图结构矛盾检测
- **StoryBox** (2025) — 沙盒模拟式长篇生成

### 技术框架
- [CrewAI](https://crewai.com) — 多Agent编排框架
- [LiteLLM](https://github.com/BerriAI/litellm) — 多LLM统一接口
- [ChromaDB](https://www.trychroma.com/) — 向量数据库
- [Pydantic](https://docs.pydantic.dev/) — 数据校验

---

<div align="center">

**织章 StoryLoom** — 让不完美的AI组件，织出足够好的故事。

*Weaving imperfect AI components into stories good enough to matter.*

⭐ 如果觉得有用，请给个Star！

</div>

---

<a name="english"></a>

## 📖 Overview (English)

**StoryLoom (织章)** is a multi-agent intelligent novel generation system
where each AI agent plays a distinct role — Director, Protagonist,
Foreshadowing Manager, Surprise Planner, Consistency Checker, and
Prose Writer — each powered by the AI model best suited for its task.

Inspired by **Qian Xuesen's Engineering Cybernetics**, the system applies
7 control theory principles (feedback loops, statistical filtering,
sensitivity analysis, decoupling, hierarchical control, and human-in-the-loop)
to achieve reliable creative output from inherently imperfect AI components.

### Key Features

- **8 Specialized Agents** with distinct roles and personalities
- **Multi-Model Routing**: Each agent automatically uses the optimal AI model
  (DeepSeek for reasoning, Claude for creativity, GPT-4o for structured output)
- **Control Theory Quality Management**: Feedback loops, multi-sampling with
  voting, sensitivity-based resource allocation
- **Foreshadowing Lifecycle**: Explicit state machine tracking
  (Plant → Reinforce → Activate → Resolve/Subvert)
- **Controlled Randomness**: "Surprising yet justified" plot events
  with cooldown periods and director approval
- **Layered Memory**: Core memory (in-prompt) + Vector memory (RAG/ChromaDB)
- **Multi-Modal Ready**: Structured intermediate representation for future
  TTS, image, and video generation

### Quick Start

```bash
git clone https://github.com/yourname/storyloom.git
cd storyloom
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys
python -m storyloom.main_controlled
```

### Philosophy

> "Don't pursue the advancement of individual technologies;
> pursue the rationality of the overall design."
> — Qian Xuesen, *Engineering Cybernetics*

Traditional AI writing = one model, start to finish (open-loop) → errors accumulate

**StoryLoom** = specialized agents with systematic quality control (closed-loop) → errors converge

The system doesn't require each AI component to be perfect. Instead, through
feedback, redundancy, decoupling, and hierarchical control, it composes
"imperfect components" into a "good enough whole."

---

<div align="center">

Made with 🧵 by the StoryLoom community

</div>

---

## 项目名称释义

| | 中文 | English |
|---|------|---------|
| **名称** | **织章** (zhī zhāng) | **StoryLoom** |
| **含义** | 织 = 编织；章 = 篇章/乐章 | Loom = 织布机 |
| **隐喻** | 多个Agent如同经纬线，交织成完整篇章 | A loom weaves threads into fabric, as agents weave plot threads into stories |
| **呼应** | 伏笔Agent在系统中被称为"织网者" | The foreshadowing agent is literally a "web weaver" |
| **气质** | 兼具工匠精神（系统控制论）与文学气质 | Combines engineering rigor with creative artistry |
