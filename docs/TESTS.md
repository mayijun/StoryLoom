# 后端测试用例清单

> 运行：`uv run pytest -q`（根目录）。
> 当前基线：**17 个文件 / 189 个用例全部通过**。
> 进度口径见 [MVP.md](MVP.md)；性能基线见 `scripts/bench_m0.py`。

| 文件 | 用例数 | 覆盖范围 |
|---|---|---|
| `test_project_persistence.py` | 24 | 项目落库、迁移、外键、级联 |
| `test_templates.py` | 26 | 模板注册 / 应用 / 引擎 / 路由 |
| `test_scene_asset_persistence.py` | 17 | 场景与资产持久化 |
| `test_author_p1.py` | 16 | P1：伏笔流转 / 导出 / 指标 / 配置迁移 |
| `test_templates_integration.py` | 14 | 模板端到端集成 |
| `test_chapter_structure.py` | 13 | 章节结构与场景归属 |
| `test_m0.py` | 19 | M0 验收 A1–A15 + 运行时保护 |
| `test_memory_compression.py` | 13 | 记忆分层压缩 / 降级回温 / 按层阈值 |
| `test_m0_api.py` | 7 | M0 API（game / memory / extensions） |
| `test_db_config.py` | 7 | Agent/Task 配置种子与迁移 |
| `test_flow.py` | 6 | 作者模式 Flow 与伏笔操作 |
| `test_scene_edit_regenerate.py` | 6 | 场景编辑与单场景重跑 |
| `test_api_tasks.py` | 5 | Task 配置 API |
| `test_control.py` | 5 | 控制论模块 |
| `test_api_agents.py` | 4 | Agent 配置 API |
| `test_assets.py` | 4 | 资产模型默认值 |
| `test_memory.py` | 3 | 记忆基础版（CoreMemory + RAG） |
| **合计** | **189** | |

---

## 1. 作者模式 P0 — 数据闭环

对应 [MVP.md](MVP.md) §1 P0 第 1–8、11 项。

### 1.1 多项目管理 — `test_project_persistence.py`（24）

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

### 1.2 Agent / Task 可视化配置 — `test_api_agents.py`（4）+ `test_api_tasks.py`（5）+ `test_db_config.py`（7）

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

### 1.3 资产模型 — `test_assets.py`（4）

| 用例 | 验证点 |
|---|---|
| `test_character_importance_tier` | 角色重要性分档 |
| `test_foreshadowing_defaults` | 伏笔默认值 |
| `test_project_lookup_and_defaults` | 项目查找与默认值 |
| `test_surprise_type_values` | 意外类型枚举 |

### 1.4 场景 / 资产持久化 — `test_scene_asset_persistence.py`（17）

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

### 1.5 章节结构 — `test_chapter_structure.py`（13）

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

### 1.6 场景编辑 / 重跑 — `test_scene_edit_regenerate.py`（6）

| 用例 | 验证点 |
|---|---|
| `test_edit_scene_prose_persists` | 编辑正文落库 |
| `test_edit_scene_ignores_unknown_fields` | 忽略未知字段 |
| `test_regenerate_route_passes_original_scene_id` | 重跑透传原 scene_id |
| `test_regenerate_nonexistent_scene_404` | 重跑不存在场景 404 |
| `test_regenerate_flow_skips_scene_count_increment` | 重跑不递增 scene_count |
| `test_normal_flow_increments_scene_count` | 正常生成递增 scene_count |

### 1.7 Flow 与伏笔操作 — `test_flow.py`（6）

| 用例 | 验证点 |
|---|---|
| `test_parse_json_block_extracts_object` | JSON 块提取 |
| `test_parse_json_block_raises_without_json` | 无 JSON 抛错 |
| `test_apply_reinforce_resets_dormancy` | 强化重置休眠计数 |
| `test_apply_plant_adds_foreshadow` | 种植新增伏笔 |
| `test_apply_resolve_closes_foreshadow` | 回收关闭伏笔 |
| `test_advance_scene_counters_increments` | 场景计数推进 |

### 1.8 控制论质量管控 — `test_control.py`（5）

| 用例 | 验证点 |
|---|---|
| `test_sensitivity_profiles` | 灵敏度档位 |
| `test_orchestrator_decisions` | 编排决策 |
| `test_quality_gate` | 质量门 |
| `test_decoupling_validator_detects_undeclared_dependency` | 检出未声明依赖 |
| `test_human_review_auto_mode` | 人工审核自动模式 |

### 1.9 记忆基础版 — `test_memory.py`（3）

| 用例 | 验证点 |
|---|---|
| `test_core_memory_prompt_block` | 核心记忆 prompt 块 |
| `test_add_scene_summary_truncates` | 场景摘要截断 |
| `test_rag_fallback_returns_matching_docs` | RAG 兜底检索命中 |

---

## 2. 作者模式 P1 — 创作体验

对应 [MVP.md](MVP.md) §1 P1 第 1–4 项，全部在 `test_author_p1.py`（16）。

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

## 3. M0 — 双模式动态世界纵切

对应 [MVP.md](MVP.md) §2.5 验收 A1–A15 与 §2.3 运行时预留。

### 3.1 验收与运行时 — `test_m0.py`（23）

| 用例 | 对应验收 | 验证点 |
|---|---|---|
| `test_a1_llm_packet_can_express_guard_intercept` | A1 | 导演 Agent JSON 可表达护卫拦截：位置 / 情绪 / 时间更新 |
| `test_a2_llm_packet_can_reject_teleport_with_available_locations` | A2 | JSON 裁决拒绝非法移动 + `available` 给出可去地点 |
| `test_a3_fact_visibility_filters_by_known_by` | A3 | `Fact` 按 `known_by` 过滤视图 |
| `test_a3b_world_context_fog_hides_unseeable` | A3 | 世界简报不泄露不可见信息 |
| `test_a3b_world_context_gm_sees_everything` | A3 | 裁决视角可读取完整世界简报 |
| `test_a4_save_load_replay_is_identical` | A4 | 存档→读档→回放完全一致 |
| `test_a5_demo_manifests_resolve_and_travel_override` | A5 | skill / map mod 生效，旅行耗时覆盖 |
| `test_a5_bad_manifest_rejected` | A5 | 坏 manifest 被拒绝 |
| `test_a8_override_audit_and_rollback` | A8 | `FactOverride` 审计 + 回滚一致 |
| `test_a9_idle_three_turns_triggers_npc_event` | A9 | 静止 3 回合 NPC 自发事件且不越权 |
| `test_a10_mode_switch_writes_checkpoint` | A10 | 模式切换落 checkpoint |
| `test_a11_short_term_compress_and_restart_recovery` | A11 | 短期压缩进长期 + 重启恢复 |
| `test_a12_demote_and_reheat` | A12 | 低价值长期降级检索库 + 命中回温 |
| `test_a13_backfill_scenes_and_chinese_proper_noun` | A13 | 历史场景回填 + 中文专名可检索 |
| `test_a14_backends_switch_and_degrade` | A14 | fts / vector / hybrid 切换与降级 |
| `test_a15_secrets_visibility` | A15 | secrets 只对本人可见 |
| `test_freeform_text_enters_narrative_pipeline_without_action_parser` | M0-3 | 自由文本无需动作分类即可进入叙事流水线 |
| `test_agent_suggestions_render_as_free_text_choices` | M0-3 | Agent JSON 的 `choices` 渲染为快捷输入 |
| `test_plain_prose_remains_compatible` | M0-3 | 纯文本 Agent 输出退化为 `prose` |
| `test_scene_directives_are_json_serializable` | M0-3 | StageDirective 可 JSON 序列化 |
| `test_timeout_returns_immediately` | M0-4 | 超时控制立即返回 |
| `test_quota_rejects_when_no_turns_left` | §2.3-5 | 请求级配额超限拒绝 |
| `test_director_mode_turn_runs_without_touching_game_entry` | A6 | 导演模式不回归游戏入口 |

### 3.2 API — `test_m0_api.py`（7）

| 用例 | 验证点 |
|---|---|
| `test_game_turn_and_state` | `POST /game/{pid}/turn` + `GET /state` |
| `test_game_saves_roundtrip` | 存档读写往返 |
| `test_mode_switch_endpoint` | 模式切换端点 |
| `test_memory_get_and_patch_backend` | 记忆查看与后端切换 |
| `test_extensions_resolve_endpoint` | `/extensions/resolve` |
| `test_provider_api_keys_injected_in_memory` | Key 只注入运行时内存，不落盘 |
| `test_runtime_v1_routes_registered` | `/runtime/v1/*` 版本化入口 + 旧端点保留 |

### 3.3 记忆分层压缩与配置 — `test_memory_compression.py`（13）

| 用例 | 验证点 |
|---|---|
| `test_short_to_long_uses_llm_compression_prompt` | 短期→长期使用 LLM 压缩提示词 |
| `test_long_to_history_keeps_only_key_events` | 长期→canon 只保留关键事件 |
| `test_fallback_compression_drops_scenery_keeps_key_fact` | LLM 压缩失败时确定性兜底保留关键事实 |
| `test_history_overflow_merges_inside_history_not_world_book` | canon 溢出在正史内部合并，不写世界书 |
| `test_minor_long_term_memory_demotes_to_world_book_and_reheats` | 低价值长期记忆降级 + 命中回温 |
| `test_simulated_31_turn_playthrough_tier_flow` | 31 回合模拟的完整层级流转 |
| `test_prompt_block_separates_history_and_world_book` | prompt 中正史与世界书分区 |
| `test_turn_working_context_uses_player_action_text` | 回合工作记忆使用玩家行动文本 |
| `test_creator_can_configure_each_layer_threshold` | 每层阈值可独立配置 |
| `test_demotion_rules_fall_back_to_global_thresholds` | 分层未配置时回退全局阈值 |
| `test_easiest_threshold_demotes_long_and_canon_to_world_book` | 最宽松阈值下长期与正史均可降级 |
| `test_demotion_skips_pinned_and_active_foreshadowing` | pinned 与活跃伏笔不降级 |
| `test_legacy_pinned_canon_is_normalized_on_load` | 旧配置 pinned canon 加载时归一化 |

---

## 4. Demo 模板（M0-9）

### 4.1 单元 — `test_templates.py`（26）

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

### 4.2 端到端集成 — `test_templates_integration.py`（14）

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
