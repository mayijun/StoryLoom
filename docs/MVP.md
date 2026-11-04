# 织章 StoryLoom — MVP 功能清单

> 当前系统**能生成单个场景**，但场景不落库、无章节结构、资产重启丢失，
> 无法支撑"写完一整本小说"。本清单按**闭环形成顺序**排优先级：
> 先有数据闭环（不丢），再有创作闭环（能写完整），最后质量闭环（写得好）。

---

## 优先级排序原则

1. **不丢东西比多写东西重要** — 生成的内容、资产必须能持久化，否则长篇无法积累
2. **先打通主流程，再补体验** — 章节→场景→正文的串联优先于编辑/导出等增强
3. **质量管控依赖数据沉淀** — 评分、指标、上下文衔接都需要历史场景落库后才能做

---

## P0 — 数据闭环（不丢东西）

### 1. 场景正文与生成历史落库 ✅

| 项 | 内容 |
|---|---|
| **价值** | 现在生成的场景只返回响应，刷新即失。落库后才能回顾、串联、导出、RAG 检索 |
| **范围** | 新建 `scenes` 表：`scene_id, project_id, chapter_id(预留), brief, present_characters, prose, quality_score, duration_ms, model_usage, created_at` |
| **验收** | 生成场景后 DB 有对应行；刷新前端能看到历史场景列表；按项目隔离 |
| **依赖** | 无（独立） |
| **状态** | ✅ 已实现：`SceneRow` + `repo.create_scene/update_scene/delete_scene` + `engine.generate_scene` 落库 + `/api/projects/{pid}/scenes` CRUD |

### 2. 章节 / 大纲结构 ✅

| 项 | 内容 |
|---|---|
| **价值** | 现在只有孤立的"场景生成"，没有"这本书有哪些章节、每章几个场景"的组织，无法写完整小说 |
| **范围** | 新建 `chapters` 表：`chapter_id, project_id, title, outline, position, status(草稿/锁定/已写)`；`scenes` 表加 `chapter_id` 外键（ON DELETE SET NULL）；前端加章节树视图 |
| **验收** | 能创建章节、给章节排场景；生成场景时归属到某章 |
| **依赖** | 依赖 #1（场景要能落库才能归属章节） |
| **状态** | ✅ 已实现：`ChapterRow` + 章节 CRUD + `assign_scene_to_chapter` + 按章节查询场景 + `GenerateSceneRequest.chapter_id` + 旧库自动迁移 scenes 外键 |

### 3. 资产落库（角色 / 场景 / 伏笔）✅

| 项 | 内容 |
|---|---|
| **价值** | 现在角色/场景/伏笔只在引擎内存 `NovelProject` 里，服务重启全丢。长篇创作中资产是核心，必须持久化 |
| **范围** | 新建 `characters` / `locations` / `foreshadowings` 三表，对 `projects.project_id` 外键级联；改写 `assets.py` 路由从 DB 读写；`engine._build_project` 启动时从 DB 重建 `NovelProject` 运行时对象 |
| **验收** | 重启服务后角色/场景/伏笔仍在；伏笔状态字段正确持久化 |
| **依赖** | 无（可与 #1 并行） |
| **状态** | ✅ 已实现：三张表 + CRUD + 引擎加载/落库 + 资产路由走 DB |

---

## P1 — 创作闭环（能写完整小说）

### 4. 生成结果人工编辑 + 单场景重跑 ✅

| 项 | 内容 |
|---|---|
| **价值** | AI 生成的正文用户需要微调；不满意要能重跑而不改其他场景 |
| **范围** | `PUT /api/projects/{pid}/scenes/{id}` 改 prose/brief/quality_score 等；`POST /api/projects/{pid}/scenes/{id}/regenerate` 用原 brief+在场角色+章节重新生成并覆盖 |
| **验收** | 编辑后持久化；重跑生成新 prose 覆盖原场景，scene_count 不递增 |
| **依赖** | #1（场景必须先落库） |
| **状态** | ✅ 已实现：scene_flow 加 `is_regenerate` 标志（重跑跳过计数递增）；engine.generate_scene 支持 `scene_id` 参数覆盖；scenes 路由 `/regenerate` 端点 |

### 5. 小说导出

| 项 | 内容 |
|---|---|
| **价值** | 写完的小说要能拿出去——否则产物永远锁在系统里 |
| **范围** | `GET /api/projects/{id}/export?format=md\|txt`：按章节→场景顺序拼接 prose，生成 Markdown 或纯文本下载 |
| **验收** | 导出的 .md 按章节标题分节，场景正文完整保留 |
| **依赖** | #1 + #2 |

### 6. 多场景上下文衔接

| 项 | 内容 |
|---|---|
| **价值** | 现在 `CoreMemory` 只滚动最近 2~3 场景摘要，但历史场景没库，RAG 检索不到旧内容，长文容易前后脱节 |
| **范围** | 生成新场景时把 `scenes` 表中该项目已落库的历史场景摘要喂给 `CoreMemory` / 灌入 ChromaDB 供 RAG 检索 |
| **验收** | 生成第 N 个场景时，导演/一致性 Agent 能"记得"第 1 个场景发生了什么 |
| **依赖** | #1 |

---

## P2 — 质量闭环（写得好）

### 7. 伏笔状态流转 API

| 项 | 内容 |
|---|---|
| **价值** | 伏笔状态机已在内存模型里实现（PLANTED→REINFORCED→ACTIVATED→RESOLVED/SUBVERTED），但没有接口触发状态变更，等于死代码 |
| **范围** | `PATCH /api/assets/foreshadowings/{id}/transition?to=ACTIVATED`；校验合法跃迁；配合 #3 落库后状态可持久化 |
| **验收** | 伏笔能按状态机推进；非法跃迁被拒；前端显示当前状态 |
| **依赖** | #3 |

### 8. 成本与质量指标前端展示

| 项 | 内容 |
|---|---|
| **价值** | 控制论评分、token 消耗、耗时在后端已产生，但 UI 没暴露，用户看不到"这段花了多少钱/质量几分" |
| **范围** | 前端场景卡片加指标区：质量分 / token / 耗时 / 参与的 Agent；控制论模块的统计数据也展示 |
| **验收** | 生成完一个场景，前端能看到这次的质量分和成本 |
| **依赖** | #1（指标随场景记录持久化） |

### 9. Agent · Task 配置导入导出 / 跨项目复制

| 项 | 内容 |
|---|---|
| **价值** | 每个项目现在独立有一套 Agent/Task 配置，从零开始太慢。需要能把调优好的配置备份或复制到新项目 |
| **范围** | `POST /api/projects/{id}/export-config` 导出 YAML；`POST /api/projects/{id}/import-config` 导入；或 `POST /api/projects/{id}/copy-config?from={other_id}` |
| **验收** | 导出的 YAML 可重新导入到新项目并生效 |
| **依赖** | 无 |

---

## 依赖关系

```
P0:  #1 场景落库 ──┬─→ #2 章节结构
                   ├─→ #4 编辑重跑 ─→ P1
                   └─→ #6 上下文衔接 ─→ P1
     #3 资产落库 ──→ #7 伏笔流转 ─→ P2
P1:  #1+#2 ──→ #5 导出
P2:  #1 ──→ #8 指标展示
     (无) ──→ #9 配置复制
```

**推荐实施顺序**：#1 → #3 → #2 → #4 → #5 → #6 → #7 → #8 → #9

其中 #1 和 #3 可并行（分别建 scenes 表和 assets 三表，互不阻塞）。
