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

strategy:
  mode: "balanced"        # cost_optimized / quality_first / balanced
  auto_fallback: true
  max_cost_per_scene: 0.50
```

用户无需改代码，只改 YAML 即可调整分配策略。

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
- `quality_first`：优先 primary
- `cost_optimized`：在 primary / fallback 中选每千 token 成本更低者

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
