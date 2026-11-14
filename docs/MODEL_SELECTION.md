# 模型选择指南

> 核心结论：**一个系统、多个模型**。不同模型家族有不同的推理风格、偏见与优势，
> 按 Agent 职责分配模型，可以同时优化质量与成本。

---

## 1. 为什么每个 Agent 要用不同模型

| Agent 角色 | 需要的模型特质 | 推荐模型 |
|-----------|---------------|---------|
| 导演 | 强逻辑规划 | DeepSeek-V4-Pro / Claude |
| 主角 | 创意与人格表现力 | Claude / GPT-4o |
| 群演 | 简单反应，成本敏感 | DeepSeek-Flash / 本地小模型 |
| 一致性检测 | 严格结构化输出 | GPT-4o（工具调用最稳定） |
| 润色 | 极强文学表现力 | Claude |
| 大纲 | 长上下文 + 结构规划 | Gemini / DeepSeek |
| 意外 | 发散思维、跳跃联想 | Claude（温度 0.95） |
| 伏笔 | 严密状态追踪 | DeepSeek-V4-Pro（温度 0.5） |
| 记忆压缩 | 稳定摘要 + 结构化输出 + 成本敏感 | DeepSeek-Flash / 本地小模型 |

### 实际收益

| 效果 | 原因 |
|------|------|
| 角色对话更有层次感 | 不同模型"说话方式"天然不同，映射到角色即个性差异 |
| 一致性检查更可靠 | 用不同于写作模型的模型做审核 = "第二双眼睛" |
| 成本可控 | 群演用便宜模型，主角用好模型，整体成本显著下降 |
| 单点故障隔离 | 某家 API 挂了自动降级，不阻断流程 |

---

## 2. 配置结构

```yaml
providers:            # 注册可用模型
  deepseek:
    api_base: "https://api.deepseek.com"
    env_key: "DEEPSEEK_API_KEY"
    models:
      flash: { model_id: "deepseek/deepseek-flash", cost_per_1k_tokens: 0.001 }

agent_model_mapping:  # Agent → 模型
  director:
    primary: "deepseek.v4pro"
    fallback: "deepseek.flash"
    temperature: 0.7
  memory:
    primary: "deepseek.flash"
    fallback: "ollama.qwen3_8b"
    temperature: 0.3

strategy:
  mode: "balanced"        # cost_optimized / quality_first / balanced
  # 预留字段：当前路由代码未读取
  auto_fallback: true
  max_cost_per_scene: 0.50
```

用户无需改代码，只改 YAML 即可调整分配策略。

注意：`auto_fallback` 与 `max_cost_per_scene` 目前只是配置占位，代码并未读取——
降级始终启用，也没有单场景成本上限；实际参与选型的只有 `mode`。

---

## 3. 自动降级逻辑

`llm/router.py` 的选择顺序：

```
primary 可用 → 用 primary
primary 不可用 → fallback 可用 → 用 fallback 并打印降级日志
两者都不可用 → 任意已配置 Key 的模型
全不可用 → RuntimeError（提示检查 .env）
```

`strategy.mode` 的影响：
- `balanced`：优先 primary
- `quality_first`：优先 primary（当前与 balanced 行为一致）
- `cost_optimized`：在 primary / fallback 中选每千 token 成本更低者

补充：
- 角色未在 `agent_model_mapping` 中配置时，primary / fallback 都回落到 `deepseek.flash`，
  temperature 默认 `0.8`；
- API Key 从 `providers.*.env_key` 指向的环境变量读取；模型映射本身只读
  `model_config.yaml`，不读环境变量、不落数据库；
- 回合请求体可带 `provider_api_keys`，运行时覆盖内存注册表中的 Key，
  优先级高于环境变量；进程内持续生效，直到重启或被再次覆盖，不写盘、不回显。

---

## 4. 成本预估

| 场景 | API Key 配置 | 单场景成本 | 说明 |
|------|------------|-----------|------|
| 最低成本 | 仅 DeepSeek | ~¥0.05 | 全部 Agent 用 DeepSeek-Flash |
| 平衡方案 | DeepSeek + OpenAI | ~¥0.15 | 关键 Agent 用 GPT-4o |
| 最高质量 | 全部配置 | ~¥0.50 | 每个 Agent 用最优模型 |
| 完全免费 | Ollama 本地 | ¥0.00 | 质量取决于本地模型能力 |

---

## 5. DeepSeek 接入注意点

- DeepSeek 已退役 `deepseek-chat` / `deepseek-reasoner` 旧模型名，
  当前使用 `deepseek/deepseek-flash` 与 `deepseek/deepseek-v4-pro`。
- `deepseek-flash` 默认开启思考模式，延迟与 token 消耗高于旧 chat 模型。
- 推理模型的推理过程通过独立 `reasoning_content` 字段返回。
- 推理模型生成规范工具调用格式不够稳定，因此一致性检测等场景
  统一采用"输出 JSON + 容错解析 + 失败放行"的策略。

---

## 6. 游戏模式基座（M0）的角色与模型

M0 已落地叙事节拍、记忆压缩、Mod v1，以及由 LLM 完成的世界裁决；
以下角色的模型分配按职责预留，后续接入时沿用：

| 新角色 | 职责 | 是否需要 LLM | 建议模型 |
|---|---|---|---|
| NarrativeDirector | 节奏、张力、信息预算、命运预兆 | 是 | DeepSeek V4 Pro（结构化 JSON） |
| PlayerInterpreter | 玩家自由输入 → 结构化 ActionProposal | 是 | Claude Sonnet / GPT-4o |
| WorldAdjudicator | 行动合法性、状态迁移、时间推进（统一 JSON 裁决） | 是 | DeepSeek V4 Pro（结构化 JSON） |
| ModerationReviewer | 只审被标记的文本片段 | 是 | 便宜模型 + 结构化输出 |
| MediaResolver | 意图 → 资源匹配 | **否**（标签检索） | — |
| CastingAdjudicator | 配额、重名、必要性检查 | 部分 | 规则优先，LLM 只做必要性判断 |
| FateManager | 压力计算、倒数器、收束触发 | **否** | 确定性算法 + seed |
| EnsembleAgent | NPC 记忆 → 反思 → 计划 → 提案 | 是 | 按 `importance_tier`：关键角色用中档模型，群演合并一次调用 |
| MemoryCompressor | 按 `visible_to` 分区批量压缩同组短期记忆 → 长期摘要 | 是 | 默认 `dedicated` 用 `memory` 角色；也可配 `director` 或 `character` |
| FactOverrideParser | 导演改写事实 → 结构化 `FactOverride` | 是 | DeepSeek V4 Pro（结构化 JSON） |
| Mod v1 | YAML 规则与钩子注册 | **否** | — |

原则不变：**能用代码确定性完成的，不交给 LLM**。时间、随机、算术、
配额都属于代码层；LLM 只负责理解、裁决、提案、叙述与判断。

成本控制沿用 `detail_level`：

- `L0 / L1`：强模型（主角、关键抉择、收束场景）；
- `L2`：中档模型；
- `L3 / L4`：便宜模型或模板，群演不单独调用。

M0 的实际调用链为 `perceive → director_frame → actor_round → _npc_round → adjudicate → render_scene`；
裁决由导演 Agent 输出 JSON，时间、随机、配额全部确定性执行，非在场角色不 tick。
