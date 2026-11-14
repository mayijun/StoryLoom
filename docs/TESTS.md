# 后端测试用例清单

> 运行：`uv run pytest -q`（根目录）。
> 当前基线：**28 个文件 / 238 个用例全部通过**。
> 进度口径见 [MVP.md](MVP.md)；性能基线见 `scripts/bench_m0.py`。

| 文件 | 用例数 | 覆盖范围 |
|---|---|---|
| `api/test_author.py` | 16 | P1：伏笔流转 / 导出 / 指标 / 配置迁移 |
| `api/test_game.py` | 10 | 游戏回合、存档、模式切换、版本化路由 |
| `api/test_engine.py` | 4 | 运行时超时 / 配额 / Key 注入 / 压缩角色 |
| `api/test_agents.py` | 4 | Agent 配置 API |
| `api/test_tasks.py` | 5 | Task 配置 API |
| `api/test_scenes.py` | 6 | 场景编辑与单场景重跑 |
| `api/test_memory.py` | 2 | 记忆查看 / 后端切换 / 压缩方角色选择 |
| `api/test_extensions.py` | 1 | 扩展解析 API |
| `crews/test_character_wake.py` | 15 | 角色唤醒与在场校验 |
| `crews/test_packet.py` | 5 | Agent JSON 包解析与舞台编排 |
| `db/test_projects.py` | 24 | 项目落库、迁移、外键、级联 |
| `db/test_scene_assets.py` | 17 | 场景与资产持久化 |
| `db/test_chapters.py` | 13 | 章节结构与场景归属 |
| `db/test_config.py` | 7 | Agent/Task 配置种子与迁移 |
| `db/test_memory_migration.py` | 1 | 旧库 `visibility` + `known_by` → `visible_to` 迁移 |
| `engine/test_narrative_flow.py` | 6 | 作者模式 Flow 与伏笔操作 |
| `engine/test_runtime.py` | 3 | 回合运行时、自由输入、NPC 自主、导演模式 |
| `engine/test_world_context.py` | 2 | 世界简报信息迷雾 |
| `engine/test_foreshadow_conflicts.py` | 1 | 伏笔回溯补录一致性校验 |
| `memory/test_compression.py` | 23 | 记忆分层压缩 / 按 `visible_to` 分区 / 无损溢出 / 文言双轨 / 降级回温 / 按层阈值 |
| `memory/test_layered_memory.py` | 12 | 双模式统一记忆 / 世界书召回 / 数据库回填 / 层级流转 |
| `memory/test_visibility.py` | 7 | `Fact` / secrets / 伏笔真相的可见性隔离；旧快照字段迁移 |
| `memory/test_models.py` | 4 | 资产模型默认值 |
| `memory/test_checkpoint.py` | 1 | 存档、读档与回放 |
| `memory/test_world_state.py` | 2 | 世界改写审计与模式切换 |
| `templates/test_templates.py` | 31 | 模板注册 / 应用 / 引擎 / 路由 |
| `templates/test_integration.py` | 14 | 模板端到端集成 |
| `extensions/test_manifest.py` | 2 | manifest 校验与旅行覆盖 |
| **合计** | **238** | |

---

## 1. 作者模式 P0 — 数据闭环

对应 [MVP.md](MVP.md) §1 P0 第 1–8、11 项。

### 1.1 多项目管理 — `db/test_projects.py`（24）

| 用例 | 验证点 |
|---|---|
| `test_create_project_persists_to_db` | 创建项目后可从 DB 读到 |
| `test_create_project_auto_seeds_agents_and_tasks` | 新项目自动播种默认 8 agent + 6 task |
| `test_create_project_duplicate_raises` | 重复 project_id 抛 ValueError |
| `test_create_project_no_sqlite_lock` | 回归：session 嵌套 seed 不再死锁 |
| `test_update_project_stats` | 生成场景后统计字段写回 |
| `test_update_project_stats_missing_returns_none` | 不存在项目返回 None 不抛异常 |
| `test_foreign_key_rejects_orphan_agent_insert` | 孤儿 agent_config 被外键拒绝 |
| `test_foreign_key_rejects_orphan_task_insert` | 孤儿 task_config 被外键拒绝 |
| `test_delete_project_cascades_agents_and_tasks` | 删项目级联清理配置 |
| `test_delete_project_isolates_other_projects` | 删项目 A 不影响项目 B |
| `test_delete_demo_project_forbidden` | demo 内置项目禁止删除 |
| `test_delete_nonexistent_project_returns_false` | 删不存在项目返回 False |
| `test_legacy_db_with_project_id_but_no_fk_migrates` | 旧库（有 project_id 无外键）迁移 |
| `test_migration_preserves_multiple_projects` | 多项目旧库迁移后互不串扰 |
| `test_legacy_db_without_project_id_column_migrates_to_demo` | 最老形态旧库归入 demo |
| `test_fresh_db_creates_tables_without_migration` | 全新库只建表不迁移不 seed |
| `test_reopening_migrated_db_is_idempotent` | 重启后 create_all 幂等 |
| `test_pragma_foreign_keys_enabled_per_connection` | SQLite 外键逐连接开启 |
| `test_upsert_project_explicit_update_still_works` | 显式更新仍生效 |
| `test_legacy_migration_skips_empty_project_id_rows` | 跳过 project_id='' 垃圾行 |
| `test_migration_when_only_task_table_is_legacy` | 仅 task 表为旧形态的部分迁移 |
| `test_ensure_project_creates_placeholder` | 缺行时补占位记录 |
| `test_ensure_project_idempotent` | 重复调用不覆盖已有数据 |
| `test_regression_ensure_project_must_not_overwrite_metadata` | 回归：ensure 不得误用 UPDATE 语义 |

### 1.2 Agent / Task 可视化配置 — `api/test_agents.py`（4）+ `api/test_tasks.py`（5）+ `db/test_config.py`（7）

| 用例 | 验证点 |
|---|---|
| `test_list_agents_comes_from_database` | 列表来自 DB 而非代码常量 |
| `test_create_conflict_and_get`（agents） | 创建冲突检测与读取 |
| `test_update_merges_settings_and_delete` | 更新合并 settings、可删除 |
| `test_projects_have_isolated_agents` | 跨项目 Agent 隔离 |
| `test_list_tasks_comes_from_database` | Task 列表来自 DB |
| `test_create_conflict_and_get`（tasks） | Task 创建冲突检测与读取 |
| `test_create_rejects_unknown_agent` | 拒绝引用不存在的 Agent |
| `test_update_and_delete` | Task 更新与删除 |
| `test_projects_have_isolated_tasks` | 跨项目 Task 同名 key 独立 |
| `test_seed_from_yaml` | YAML 种子落库 |
| `test_load_shapes_for_crewai` | 配置形态适配 CrewAI |
| `test_update_agent_is_persisted` | Agent 更新持久化 |
| `test_add_agent_and_task_without_code_change` | 不改代码新增 Agent/Task |
| `test_disabled_task_is_skipped` | 禁用 Task 被跳过 |
| `test_project_isolation` | 配置按项目隔离，默认 demo |
| `test_legacy_db_migrated_into_demo_project` | 旧库数据归入 demo |

### 1.3 资产模型 — `memory/test_models.py`（4）

| 用例 | 验证点 |
|---|---|
| `test_character_importance_tier` | 角色重要性分档 |
| `test_foreshadowing_defaults` | 伏笔默认值 |
| `test_project_lookup_and_defaults` | 项目查找与默认值 |
| `test_surprise_type_values` | 意外类型枚举 |

### 1.4 场景 / 资产持久化 — `db/test_scene_assets.py`（17）

| 用例 | 验证点 |
|---|---|
| `test_create_scene_persists` | 场景落库（brief/prose/质量分/耗时） |
| `test_list_scenes_isolated_by_project` | 场景按项目隔离 |
| `test_update_scene_prose` | 正文更新 |
| `test_update_nonexistent_scene_returns_none` | 不存在返回 None |
| `test_delete_scene` | 场景删除 |
| `test_scene_foreign_key_rejects_orphan` | 孤儿场景被外键拒绝 |
| `test_delete_project_cascades_scenes` | 删项目级联场景 |
| `test_upsert_character_persists` | 角色落库 |
| `test_upsert_character_update_existing` | 角色更新 |
| `test_delete_character` | 角色删除 |
| `test_character_foreign_key_rejects_orphan` | 孤儿角色被外键拒绝 |
| `test_characters_isolated_by_project` | 角色按项目隔离 |
| `test_upsert_location_persists` | 地点落库 |
| `test_delete_location_cascades_with_project` | 地点随项目级联 |
| `test_upsert_foreshadowing_persists` | 伏笔落库 |
| `test_foreshadowing_cascades_with_project` | 伏笔随项目级联 |
| `test_engine_rebuilds_assets_from_db` | 重启后资产从 DB 恢复 |

### 1.5 章节结构 — `db/test_chapters.py`（13）

| 用例 | 验证点 |
|---|---|
| `test_create_chapter_persists` | 章节落库 |
| `test_auto_position_increments` | 位置自增 |
| `test_explicit_position_allowed` | 允许显式位置 |
| `test_update_chapter` | 章节更新 |
| `test_delete_chapter` | 章节删除 |
| `test_chapter_foreign_key_rejects_orphan` | 孤儿章节被外键拒绝 |
| `test_delete_project_cascades_chapters` | 删项目级联章节 |
| `test_assign_scene_to_chapter` | 场景归属章节 |
| `test_assign_scene_to_nonexistent_chapter_raises` | 归属不存在章节报错 |
| `test_unassign_scene` | 解除归属 |
| `test_delete_chapter_sets_scene_chapter_null` | ON DELETE SET NULL：删章节不丢场景 |
| `test_list_unassigned_scenes` | 未归属场景列表 |
| `test_migrate_scenes_without_chapter_fk` | 旧库 scenes 无章节外键的迁移 |

### 1.5.1 旧库可见范围迁移 — `db/test_memory_migration.py`（1）

| 用例 | 验证点 |
|---|---|
| `test_legacy_visibility_backfills_visible_to` | `visibility` / `known_by` 回填 `visible_to`；`canon` → `key_events`；重复启动不重复迁移 |

### 1.6 场景编辑 / 重跑 — `api/test_scenes.py`（6）

| 用例 | 验证点 |
|---|---|
| `test_edit_scene_prose_persists` | 编辑正文落库 |
| `test_edit_scene_ignores_unknown_fields` | 忽略未知字段 |
| `test_regenerate_route_passes_original_scene_id` | 重跑透传原 scene_id |
| `test_regenerate_nonexistent_scene_404` | 重跑不存在场景 404 |
| `test_regenerate_flow_skips_scene_count_increment` | 重跑不递增 scene_count |
| `test_normal_flow_increments_scene_count` | 正常生成递增 scene_count |

### 1.7 Flow 与伏笔操作 — `engine/test_narrative_flow.py`（6）

| 用例 | 验证点 |
|---|---|
| `test_parse_json_block_extracts_object` | JSON 块提取 |
| `test_parse_json_block_raises_without_json` | 无 JSON 抛错 |
| `test_apply_reinforce_resets_dormancy` | 强化重置休眠计数 |
| `test_apply_plant_adds_foreshadow` | 种植新增伏笔 |
| `test_apply_resolve_closes_foreshadow` | 回收关闭伏笔 |
| `test_advance_scene_counters_increments` | 场景计数推进 |

### 1.8 分层记忆 — `memory/test_layered_memory.py`（12）

| 用例 | 验证点 |
|---|---|
| `test_layered_memory_separates_core_prompt_and_world_book` | 核心层 `prompt_block` 与世界书 `retrieval_block` 分离 |
| `test_director_flow_retrieves_world_book_from_layered_memory` | 导演流程按需召回世界书 |
| `test_add_condensed_writes_requested_tier_with_scope` | 导演指定的层与 `visible_to` 写入后重启仍保持 |
| `test_pending_side_stage_is_hidden_from_world_book_retrieval` | `visible_to=[]` 的待处理分支不进入任何检索 |
| `test_backfill_refreshes_assets_without_overwriting_layered_scenes` | 历史回填刷新资产，不覆盖已有分层场景；秘密条目不被误清 |
| `test_scene_memory_scopes_by_witnesses_and_crowd` | 场景按在场角色隔离，crowd 只对路人视角可见 |
| `test_world_book_matching_respects_viewer_across_backends` | fts / hybrid / vector 世界书召回都按 viewer 过滤受限条目 |
| `test_sync_foreshadowings_preserves_later_visible_to` | 伏笔描述/真相双投影；后续新增知情者不被资产侧覆盖 |
| `test_short_term_compress_and_restart_recovery` | 短期压缩进长期 + 重启恢复 |
| `test_demote_and_reheat` | 低价值长期降级检索库 + 命中回温 |
| `test_backfill_scenes_and_chinese_proper_noun` | 历史场景回填 + 中文专名可检索 |
| `test_backends_switch_and_degrade` | fts / vector / hybrid 切换与降级 |

---

## 2. 作者模式 P1 — 创作体验

对应 [MVP.md](MVP.md) §1 P1 第 1–4 项，全部在 `api/test_author.py`（16）。

| 用例 | 验证点 |
|---|---|
| `test_foreshadow_transition_reinforce` | 伏笔强化流转 |
| `test_foreshadow_transition_full_lifecycle` | 种植→…→回收全生命周期 |
| `test_foreshadow_transition_illegal_409` | 非法流转 409 |
| `test_foreshadow_transition_not_found` | 伏笔不存在 404 |
| `test_foreshadow_transition_bad_action_422` | 非法 action 422 |
| `test_export_markdown` | 导出 Markdown |
| `test_export_txt` | 导出 TXT |
| `test_export_404` | 项目不存在 404 |
| `test_metrics_aggregation` | 成本 / 质量指标聚合 |
| `test_metrics_empty_project` | 空项目指标 |
| `test_config_export_contains_seeded_agents` | 配置导含播种 Agent |
| `test_config_import_merge_and_overwrite` | 导入 merge / overwrite |
| `test_config_import_invalid_422` | 非法导入 422 |
| `test_config_import_overwrite_empty_agents_422` | overwrite 不允许空 Agent 列表 |
| `test_config_copy_between_projects` | 跨项目复制配置 |
| `test_config_copy_same_project_400` | 同项目复制 400 |

---

## 3. 双模式运行时与跨模块能力

对应 [MVP.md](MVP.md) §2.5 验收项与 §2.3 运行时预留；用例已按所属模块拆分。

### 3.1 角色包与舞台编排 — `crews/test_packet.py`（5）

| 用例 | 验证点 |
|---|---|
| `test_packet_can_express_guard_intercept` | 导演 Agent JSON 可表达护卫拦截：位置 / 情绪 / 时间更新 |
| `test_packet_can_reject_teleport_with_available_locations` | JSON 裁决拒绝非法移动 + `available` 给出可去地点 |
| `test_agent_suggestions_render_as_free_text_choices` | Agent JSON 的 `choices` 渲染为快捷输入 |
| `test_plain_prose_remains_compatible` | 纯文本 Agent 输出退化为 `prose` |
| `test_scene_directives_are_json_serializable` | StageDirective 可 JSON 序列化 |

### 3.2 信息隔离 — `memory/test_visibility.py`（7）+ `engine/test_world_context.py`（2）

| 用例 | 验证点 |
|---|---|
| `test_legacy_known_by_migrates_to_visible_to` | 旧记忆快照/旧行的 `visibility` + `known_by` 统一为 `visible_to` |
| `test_legacy_fact_and_foreshadow_migrate_visibility` | 旧 `Fact` / 伏笔快照的字段迁移与全知 token 剥离 |
| `test_fact_visibility_filters_by_visible_to` | `Fact` 按 `visible_to` 过滤视图 |
| `test_multi_viewer_fact_projection_and_sync` | 多知情者保持 restricted，新增知情者原地更新 |
| `test_secrets_visibility` | secrets 只对本人与全知视角可见 |
| `test_character_secret_stored_only_in_memory` | 角色秘密唯一存储在 `secret:<角色>` 记忆条目 |
| `test_foreshadow_truth_visible_to_director_and_known_character` | 伏笔描述/真相按 `visible_to` 过滤，默认仅导演可见 |
| `test_world_context_fog_hides_unseeable` | 世界简报不泄露不可见信息 |
| `test_world_context_gm_sees_everything` | 裁决视角可读取完整世界简报 |

### 3.3 存档与模式切换 — `memory/test_checkpoint.py`（1）+ `memory/test_world_state.py`（2）

| 用例 | 验证点 |
|---|---|
| `test_save_load_replay_is_identical` | 存档→读档→回放完全一致 |
| `test_override_audit` | `FactOverride` 审计 |
| `test_mode_switch_writes_checkpoint` | 模式切换落 checkpoint |

### 3.4 扩展 manifest — `extensions/test_manifest.py`（2）

| 用例 | 验证点 |
|---|---|
| `test_demo_manifests_resolve_and_travel_override` | skill / map mod 生效，旅行耗时覆盖 |
| `test_bad_manifest_rejected` | 坏 manifest 被拒绝 |

### 3.5 叙事运行时 — `engine/test_runtime.py`（3）+ `engine/test_foreshadow_conflicts.py`（1）

| 用例 | 验证点 |
|---|---|
| `test_idle_three_turns_triggers_npc_event` | 静止 3 回合 NPC 自发事件且不越权 |
| `test_freeform_text_enters_narrative_pipeline_without_action_parser` | 自由文本无需动作分类即可进入叙事流水线 |
| `test_director_mode_turn_runs_without_touching_game_entry` | 导演模式不回归游戏入口 |
| `test_foreshadow_retroactive_conflict_blocks` | 回溯补录伏笔：未知角色/历史冲突阻断 |

### 3.6 游戏回合 API — `api/test_game.py`（10）

| 用例 | 验证点 |
|---|---|
| `test_game_turn_and_state` | `POST /game/{pid}/turn` + `GET /state` |
| `test_game_saves_roundtrip` | 存档读写往返 |
| `test_mode_switch_endpoint` | 模式切换端点 |
| `test_freeform_api_text_does_not_require_intent` | 自由文本请求无需 `intent` 字段 |
| `test_runtime_v1_routes_registered` | `/runtime/v1/*` 版本化入口 + 旧端点保留 |
| `test_turn_advances_arc_and_returns_frame` | 回合推进节拍并返回舞台帧 |
| `test_turn_mode_switch_writes_checkpoint` | 回合内切换模式写 checkpoint |
| `test_turn_applies_overrides_before_narrative` | 叙事前应用 `FactOverride` |
| `test_turn_timeout_returns_timeout_status` | 回合超时返回 timeout 状态 |
| `test_turn_quota_exceeded` | 回合配额耗尽拒绝 |

### 3.7 运行时引擎 — `api/test_engine.py`（4）

| 用例 | 验证点 |
|---|---|
| `test_timeout_returns_immediately` | 超时控制立即返回 |
| `test_quota_rejects_when_no_turns_left` | 请求级配额超限拒绝 |
| `test_provider_api_keys_injected_in_memory` | Key 只注入运行时内存，不落盘 |
| `test_compression_provider_selects_role` | `compression.provider` 按 `visible_to` 选择独立压缩者 / 导演 / 角色模型 |

### 3.8 记忆 / 扩展 API — `api/test_memory.py`（1）+ `api/test_extensions.py`（1）

| 用例 | 验证点 |
|---|---|
| `test_memory_get_and_patch_backend` | 记忆查看与后端切换 |
| `test_extensions_resolve_endpoint` | `/extensions/resolve` |

### 3.9 记忆分层压缩与配置 — `memory/test_compression.py`（23）

| 用例 | 验证点 |
|---|---|
| `test_short_to_long_uses_llm_compression_prompt` | 短期→长期使用 LLM 压缩提示词 |
| `test_long_to_history_keeps_only_key_events` | 长期→key_events 只保留关键事件 |
| `test_fallback_compression_drops_scenery_keeps_key_fact` | LLM 压缩失败时确定性兜底保留关键事实 |
| `test_key_events_overflow_cools_coldest_without_losing_information` | 两种旧配置均无损迁出冷事件，持久化后保留全文并回温到 key_events |
| `test_key_event_overflow_uses_embedding_relevance` | embedding 根据近期剧情语义相关性保留热事件 |
| `test_protected_key_events_may_exceed_capacity_without_data_loss` | pinned 与活跃伏笔可超容量常驻，不压缩或丢弃 |
| `test_classical_compression_keeps_vernacular_for_display` | 文言压缩后 prompt / 检索 / 存档均保留白话展示版 |
| `test_classical_compression_without_display_falls_back_to_vernacular` | 模型未返回白话版时退回白话压缩，展示面不出现文言 |
| `test_agent_memory_fact_uses_display_text_in_classical_mode` | Agent fact 的 display_text 进入展示摘要 |
| `test_agent_memory_fact_without_display_falls_back_to_prose` | 缺少 display_text 时跳过 fact 并回退到白话场景摘要 |
| `test_minor_long_term_memory_demotes_to_world_book_and_reheats` | 低价值长期记忆降级 + 命中回温 |
| `test_simulated_31_turn_playthrough_tier_flow` | 31 回合模拟的完整层级流转 |
| `test_prompt_block_separates_history_and_world_book` | prompt 中关键事件与世界书分区 |
| `test_turn_working_context_uses_player_action_text` | 回合工作记忆使用玩家行动文本 |
| `test_creator_can_configure_each_layer_threshold` | 每层阈值可独立配置 |
| `test_demotion_rules_fall_back_to_global_thresholds` | 分层未配置时回退全局阈值 |
| `test_easiest_threshold_demotes_long_and_key_events_to_world_book` | 最宽松阈值下长期与关键事件均可降级 |
| `test_demotion_skips_pinned_and_active_foreshadowing` | pinned 与活跃伏笔不降级 |
| `test_compression_never_merges_different_visible_to` | 不同可见范围各自独立压缩，绝不跨组合并或取交集 |
| `test_compression_preserves_same_scope` | 同一 `visible_to` 组压缩后完整保留该可见范围 |
| `test_empty_compress_output_falls_back_without_losing_sources` | 压缩模型返回空时确定性兜底，不丢源记忆 |
| `test_all_pinned_overflow_does_not_loop` | 无可压缩同组批次且全部受保护时退出循环，不降级 pinned |

---

## 4. Demo 模板（M0-9）

### 4.1 单元 — `templates/test_templates.py`（31）

| 用例 | 验证点 |
|---|---|
| `test_builtin_template_is_registered` | 内置模板已注册 |
| `test_template_asset_counts_and_order` | 资产数量与顺序 |
| `test_list_templates_returns_summaries` | 列表返回摘要 |
| `test_get_unknown_template_returns_none` | 未知模板返回 None |
| `test_register_custom_template` | 自定义模板可注册 |
| `test_embedded_extensions_are_valid_manifests` | 内嵌扩展 manifest 合法 |
| `test_examples_dir_no_longer_ships_demo_yaml` | examples/ 不再带固定 YAML |
| `test_apply_template_creates_project` | 应用模板建项目 |
| `test_apply_template_writes_all_assets` | 全部资产写入 |
| `test_apply_template_chapters_positions_and_status` | 章节位置与状态 |
| `test_apply_template_syncs_project_stats` | 项目统计同步 |
| `test_apply_template_custom_title` | 自定义标题 |
| `test_apply_template_is_idempotent_and_preserves_edits` | 幂等且保留用户编辑 |
| `test_apply_template_skips_when_project_already_has_characters` | 已有角色时跳过 |
| `test_apply_unknown_template_raises` | 未知模板抛错 |
| `test_two_applied_projects_can_coexist` | 同模板两次应用不冲突 |
| `test_applied_template_project_can_be_deleted` | 试用项目可删除无残留 |
| `test_extension_registry_loads_template_extensions_once` | 扩展只加载一次 |
| `test_extension_registry_reload_after_clear_cache` | 清缓存后可重载 |
| `test_engine_list_templates` | 引擎层列表 |
| `test_engine_apply_template_creates_cached_project` | 引擎层应用并缓存 |
| `test_engine_apply_template_generates_distinct_projects` | 生成不同项目 |
| `test_engine_apply_unknown_template_raises` | 引擎层未知模板抛错 |
| `test_router_list_templates` | 路由层列表 |
| `test_router_apply_template` | 路由层应用 |
| `test_router_apply_unknown_template_returns_404` | 路由层未知模板 404 |
| `test_sandbox_life_template_is_registered` | 都市沙盒模板已注册 |
| `test_sandbox_life_asset_counts_and_order` | 都市沙盒资产数量与顺序 |
| `test_sandbox_life_extensions_are_valid_manifests` | 内嵌 `map_sandbox_life` / `skill_sandbox_life` manifest 合法 |
| `test_apply_sandbox_life_template` | 应用都市沙盒模板建项目并写入资产 |
| `test_apply_sandbox_life_is_idempotent` | 重复应用幂等 |

### 4.2 端到端集成 — `templates/test_integration.py`（14）

| 用例 | 验证点 |
|---|---|
| `test_template_list_endpoint` | 模板列表端点 |
| `test_apply_template_creates_listed_project` | 应用后项目可见 |
| `test_apply_template_with_custom_title` | 自定义标题端到端 |
| `test_apply_unknown_template_returns_404` | 未知模板 404 |
| `test_template_apply_does_not_touch_existing_projects` | 不影响既有项目 |
| `test_applied_assets_visible_through_assets_api` | 资产经 API 可见 |
| `test_applied_chapters_visible_and_ordered` | 章节可见且有序 |
| `test_foreshadow_transition_works_on_template_assets` | 模板伏笔走既有状态机 |
| `test_embedded_extensions_resolved_via_api` | 内嵌扩展经 API 解析 |
| `test_game_mode_moves_using_template_map` | 游戏模式用模板地图移动 |
| `test_export_uses_template_chapters` | 导出使用模板章节 |
| `test_memory_backfill_consumes_template_assets` | 记忆回填消费模板资产 |
| `test_two_template_projects_coexist` | 两个模板项目共存 |
| `test_delete_template_project_cleans_up` | 删除清理干净 |

---

## 5. 未覆盖 / 明确不测

- 真实 LLM 调用：全部测试走确定性链路或 mock，性能基线见 `scripts/bench_m0.py`；
- 前端组件：不在 pytest 范围；
- M0 明确不做的功能（TFC 五档、审核执行、图片/音频渲染等，见 [MVP.md](MVP.md) §2.4）无对应用例。
