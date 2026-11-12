# 双模式 Demo 剧本 ·《青云宗 · 签到有债》

> 用途：作为**作者模式 + 游戏模式**的功能测试基线。
> 标注「确定性」的断言不依赖 LLM，可直接在本地跑；标注「LLM」的断言需要至少配置一个模型 Key。
> 本文只描述测试输入与预期，不新增代码。接口路径以当前实现为准。

---

## 1. Demo 概览

| 项 | 值 |
|---|---|
| 项目标题 | 青云宗 · 签到有债 |
| 文风 `style` | `仙侠世界 · 现实后果 · 群像` |
| 项目描述 | 青云宗外门杂役林凡被一纸「签到契」绑住：每一次看似白得的机缘，都会在第九格记下一笔债。大比在即，管事、师姐、首席各有各的账，没人有义务救他，也没人会等他长大。 |
| `project_id` | 由「试用模板」应用时生成，形如 `tpl_xianxia_system_<8位hex>`（普通项目，可删除）；游戏模式实例用 `xianxia_demo_001` |
| 主角命名 | **必须叫「玩家」**。前端状态栏与 `WorldState.present_characters()` 以「玩家」为视角锚点，真实姓名「林凡」写进 `persona`。 |
| 篇幅 | 3 章 / 6 个场景；游戏模式 17 个回合（18 个操作步骤） |

### 1.1 世界节拍（作者模式写作用）

| 节拍 | 位置 | 世界状态变化 | 功能 |
|---|---|---|---|
| 起 | 场景 1 | 林凡第一次签到，第九格记下第一笔 | 建立「收益与代价同时发生」 |
| 承 | 场景 2 | 管事克扣、妹妹的账被翻出 | 让玩家看见世界有自己的账 |
| 转 | 场景 3-4 | 大比规则被秦无咎利用，苏清雪试探 | NPC 各自行动，不围着玩家转 |
| 压 | 场景 5 | 林凡被押地牢，债主第一次开口 | 后果落地，信息不一次性泄底 |
| 合 | 场景 6 | 噬灵钉让所有暗账曝光 | 冲突收束，但留下「还债 / 转债 / 查账」三选一 |

### 1.2 测试范围

- 作者模式：项目管理、角色/地点/伏笔落库、章节结构、6 次场景生成、伏笔状态机、导出、指标。
- 游戏模式：移动 / 交谈 / 攻击 / 观察 / 等待 / 使用、护卫拦截、非法传送、存读档、NPC 自主、模式切换、导演改写、分层记忆。
- 不覆盖：图片/音频、TTS、多人、地图 Tier 2/3（M0 明确不做）。

---

## 2. 先建资产（两种模式共用）

### 2.1 角色（按此顺序添加）

| # | name | importance_tier | persona | motivation | secrets |
|---|---|---|---|---|---|
| 1 | 玩家 | primary | 林凡，十九岁，青云宗外门杂役弟子。说话慢，遇事先问代价，习惯把选择权推回给对方；不主动出头，也不轻易认命。 | 先弄清「签到契」每一笔的代价，再把妹妹林小满从外门管事手里赎回来。 | 他的灵根被称作「荒古圣体」，其实是一笔抵押：上一任宿主把未还完的债转到了他身上。每次签到都在第九格记一笔，同时拿走他一段与妹妹有关的记忆。 |
| 2 | 苏清雪 | primary | 内门大师姐，青云宗第一天才。清冷寡言，剑比话快；不替任何人做决定，也不欠任何人解释。 | 查清母亲留下的黑纹与签到契的关系，确认林凡是不是下一个债主。 | 她母亲是上一任宿主，死后债转到她左臂；她接近林凡，一半是调查，一半是想找替她还债的人。 |
| 3 | 秦无咎 | primary | 内门首席，出身长老世家。讲规矩，是因为规矩对他有利；笑的时候比不笑更危险。 | 拿到进入后山禁地的资格，把秦家旧债从族谱上抹掉。 | 噬灵钉是戒律堂的收债法器，他借来对付林凡；一旦当众动用，所有暗账都会被反查。 |
| 4 | 杂役管事 | background | 尖嗓门，手里永远攥着账本，见人先看腰牌；对上面赔笑，对下面刻薄。 | 填上自己欠外门的印子钱，保住管事的位子。 | 他把林凡的妹妹卖给了外门管事抵债，却谎称送去别院养病；账本那一页被他撕了，但丹房还留着一张药单。 |
| 5 | 执法堂守卫 | secondary | 铁面，只认戒律不认人，开口就是「按律」；但他从不站在没有胜算的一边。 | 守住执法堂的差事，别让戒律堂查到自己头上。 | 他曾收过秦无咎一袋灵石，答应在关键时刻「来晚一步」；可一旦噬灵钉被当众取出，他必须选择先查谁。 |

> 「玩家」放在第一位，保证 `WorldState` / 前端默认视角稳定。
> 「执法堂守卫」的名字含「守卫」，用于触发护卫拦截规则。

### 2.2 地点（**按此顺序添加，第一个必须是「演武场」**）

| # | name | description |
|---|---|---|
| 1 | 演武场 | 青云宗外门大比的主场，青石擂台高九丈，四周幡旗猎猎。 |
| 2 | 杂役院 | 低矮石屋，晾着洗不净的灰布衣，墙角堆着劈好的柴。 |
| 3 | 藏经阁 | 七层木塔，每层檐角挂着一枚锈铃，越往上铃声越轻。 |
| 4 | 丹房 | 药气熏人，三尊铜炉昼夜不熄，地上落满黑色药渣。 |
| 5 | 地牢 | 戒律堂地牢，山腹深处的石牢，铁门上刻着「戒律」二字，灯油永远只够烧一夜。 |
| 6 | 后山禁地 | 断崖与古碑，雾气从地缝里往上涌，鸟兽绝迹。 |

> `WorldState.from_project()` 会把所有角色放在**第一个地点**，所以第一地点设为「演武场」：大比当日全宗聚集，天然解释所有角色同场。
> 资产名必须精确叫「地牢」：护卫拦截按 `PRISON_LOCATION="地牢"` 匹配。

### 2.3 伏笔（3 条，建议固定 ID 方便状态流转）

| foreshadow_id | description | planted_in_scene | target_revelation | max_dormant_scenes | linked_characters |
|---|---|---|---|---|---|
| `fs_ninth_slot` | 林凡脑海里的签到面板始终有第九格，灰得像一块死铁；每次签到，第九格都会轻轻震一下，像有人在本子上记了一笔。 | `scene_1` | 第九格不是奖励，是债簿：每次签到都会把一段记忆、寿数或人情记到林凡名下，债主是上一任宿主。债可以拒还，但拒还的人会被全宗追债。 | 5 | 玩家、苏清雪 |
| `fs_black_vein` | 苏清雪每次动用剑意，左袖口都会浮出一道极细的黑纹，像被墨线缝过。 | `scene_2` | 她母亲是上一任宿主，黑纹是债转印记；她不是来救林凡的，而是在评估要不要把这笔债转给他。 | 5 | 苏清雪、玩家 |
| `fs_devouring_nail` | 秦无咎的储物戒内侧有一道新鲜划痕，里面那枚黑色长钉从不示人；每次戒律堂的人靠近，他都会按住戒面。 | `scene_3` | 噬灵钉是戒律堂的收债法器。秦无咎若当众动用它，会把所有人的暗账一起照亮：他自己的、管事的、守卫的，也包括林凡的。 | 5 | 秦无咎、玩家 |

> `scene_N` 以实际生成返回的 `scene_id` 为准；全新项目按顺序生成通常就是 `scene_1` ~ `scene_6`。

### 2.4 章节（先建章节，再生成场景并归属）

| 顺序 | 标题 | outline |
|---|---|---|
| 1 | 杂役院的第一笔 | 林凡在杂役院签到，第一次看见第九格记下一笔；管事克扣灵石，林凡可以选择忍、借势或动用签到奖励，每种选择都会留下痕迹。结尾：远处有人袖口一闪。 |
| 2 | 大比之日，人人有账 | 演武场大比，秦无咎用规则逼林凡上台，苏清雪试探，执法堂守卫冷眼旁观。林凡若动用签到，会被更多债主看见；胜负不自动等于翻身。 |
| 3 | 第九格的债主 | 夜里地牢，债主第一次开口；苏清雪带着自己的账来谈条件，秦无咎的噬灵钉让暗账曝光。结尾不是打脸，而是林凡必须决定：还债、转债，还是让全宗一起查账。 |

### 2.5 扩展包（游戏模式必装，已内嵌在模板里）

地图必须由 `mod` 注入，否则 `WorldState` 没有任何出口，所有移动都会返回 `not_found`。
本 Demo 的地图 `map_xianxia` 与文风 `skill_xianxia` 已作为 Python 字典内嵌在
`src/storyloom/templates/xianxia_system.py` 的 `EXTENSIONS` 中，不再使用独立 YAML，
也没有 `examples/` 扫描目录。`ExtensionRegistry` 在首次解析时会自动把模板内嵌扩展注册进来，
因此无需手动放置文件。另一个内置模板《临江市 · 平行人生》
（`src/storyloom/templates/sandbox_life.py`）同样内嵌 `map_sandbox_life` 与 `skill_sandbox_life`。

- `map_xianxia`（mod）：提供青云宗 6 个地点与 15 条双向路线，地牢只留「→演武场」单向出口。
- `skill_xianxia`（skill）：世界先于主角、NPC 各有各的账、签到必有代价、秘密只作线索。

> **关于同名地点**：本模板内嵌的扩展即时可用，因此「地牢」不会出现歧义。
> 自建项目若也要用「地牢」，只要项目资产里存在精确同名地点，
> `resolve_location` 会优先命中项目自己的地点。
> 如需隔离，可显式传 `enabled_extensions: ["map_xianxia", "skill_xianxia"]`。
> 另外，地图 mod 在**首回合**的 `apply_map` 才注入出口，所以 `GET /state` 的初始出口要在 G1 后再断言。

---

## 3. 作者模式测试剧本

### 3.1 准备

试用项目不再开机自动播种，需在 Web 界面「新建项目」对话框里选择「试用模板 → 青云宗 · 签到有债」，
或调用 `POST /api/templates/xianxia_system/apply`。返回的 `project_id` 形如
`tpl_xianxia_system_<8位hex>`，是普通项目，试用后可直接删除清理。

应用模板后，角色、地点、伏笔、章节均已就绪，打开项目即可从场景 1 开始生成。

如需从零复现，也可以手工执行：

1. `POST /api/projects/` 创建项目（同上）。
2. 按 §2.1、§2.2 顺序调用 `POST /api/projects/<PID>/assets/characters`、`/locations`。
3. 按 §2.3 调用 `POST /api/projects/<PID>/assets/foreshadowings`，带固定 `foreshadow_id`。
4. 按 §2.4 调用 `POST /api/projects/<PID>/chapters`，记录三个 `chapter_id`。

### 3.2 场景生成（LLM）

统一入口：`POST /api/generate/scene`，`present_character_names` 必须使用资产里的名字「玩家」。
生成响应只有 `scene_id`、`final_prose`、`steps`、`foreshadowing_updates`；
章节归属、质量分、在场角色落库要再用 `GET /api/projects/<PID>/scenes/{scene_id}` 核对。

#### 场景 1 · 第一章 · 杂役院的第一笔

- **brief（可直接粘贴）**：
  > 深夜，杂役院柴房。林凡劈完最后一捆柴，脑海里的签到面板弹出今日签到。他先算了算代价，还是点了。签出「淬体·借」——身体轻了，但第九格记下一笔，他忽然想不起妹妹上次笑的样子。管事推门进来，以偷懒为由扣掉三个月灵石，还骂他妹妹是赔钱货。林凡没有当场翻脸，只把账本翻到妹妹那一页。结尾：第九格轻轻震了一下，像有人在本子另一头应了一声。
- **在场角色**：`["玩家", "杂役管事"]`
- **必须出现**：签到、荒古圣体、淬体、账本、第九格
- **禁止**：直接说明第九格是什么；让林凡当场打脸管事；让旁白解释系统
- **伏笔操作**：植入 `fs_ninth_slot`
- **验收**：`final_prose` 不为空；`SceneView.quality_score ≥ 0.7`；`chapter_id` 正确；`present_characters` 落库正确

#### 场景 2 · 第一章 · 各人的账

- **brief**：
  > 清晨，演武场外门集合。秦无咎当众宣布：杂役弟子没有资格参加大比，除非能从藏经阁一层取回一枚锈铃。众人哄笑。林凡去藏经阁，在第七层签到，签出「缩地成寸（一次）」；他没有取铃，而是记下每枚锈铃的位置，回演武场交出一张清单，请执法堂按规矩验铃。秦无咎没料到他用规矩反将一军，只得让他报名。苏清雪第一次正眼看他，左袖口闪过一丝极细的黑纹。结尾：管事在人群后面悄悄合上账本。
- **在场角色**：`["玩家", "秦无咎", "苏清雪"]`
- **必须出现**：藏经阁、锈铃、缩地成寸、清单、黑纹
- **禁止**：让秦无咎当场动手；提前解释黑纹；让苏清雪主动护短
- **伏笔操作**：植入 `fs_black_vein`
- **验收**：场景归属第一章；文风为世界驱动；结尾有可回应的处境

#### 场景 3 · 第二章 · 大比第一剑

- **brief**：
  > 大比当日，演武场。林凡以杂役身份登台，秦无咎在台下笑着说「连剑都拿不稳」。第一场对手是炼气九层的外门师兄。林凡签到「一剑破万法（残）」，一剑劈开擂台；师兄认输，但林凡也因反噬咳血，第九格又多了一笔。秦无咎袖中储物戒一闪，一枚黑色长钉被他按住。苏清雪皱眉，左袖口浮出黑纹。
- **在场角色**：`["玩家", "秦无咎", "苏清雪", "执法堂守卫"]`
- **必须出现**：一剑破万法、擂台、黑色长钉、黑纹、第九格
- **禁止**：让噬灵钉在本场生效；让守卫提前介入；让林凡无代价获胜
- **伏笔操作**：植入 `fs_devouring_nail`；强化 `fs_black_vein`
- **验收**：战斗结果明确；无设定冲突；质量分 ≥ 0.7

#### 场景 4 · 第二章 · 台上台下

- **brief**：
  > 半决赛，林凡对上秦无咎。秦无咎不急着赢，先用规则逼林凡连续应战，消耗他的签到次数。林凡的签到面板第一次主动弹出灰色提示：【第九格可预支一次，是否确认？】他选了「否」，转而用仅剩的「卸力」撑过三招；台下苏清雪没有出手，只在秦无咎催动噬灵钉时，把一枚锈铃弹到执法堂守卫脚边。守卫捡起锈铃，第一次看向秦无咎的储物戒。结尾：林凡输了半招，却让台上的账换了主人。
- **在场角色**：`["玩家", "秦无咎", "苏清雪", "执法堂守卫"]`
- **必须出现**：第九格、卸力、噬灵钉、锈铃、按律
- **禁止**：开启第九格；让苏清雪替林凡赢；直接揭穿秦无咎
- **伏笔操作**：强化 `fs_ninth_slot`；激活 `fs_devouring_nail`
- **验收**：胜负明确但不等于爽点；秦无咎未死亡（保留后续公审）；结尾张力上升

#### 场景 5 · 第三章 · 地牢里的债主

- **brief**：
  > 当夜，地牢。秦无咎以「赛场动用禁术」反咬林凡，执法堂守卫把林凡押进地牢。林凡在牢里签到，签出「听债」——他第一次听见第九格里的声音：那声音不诱惑他，只报了一串名字，最后一个是苏清雪的母亲。苏清雪夜访，隔着铁门问他：「你妹妹在哪？」林凡第一次沉默。结尾：守卫在门外停了很久，才把钥匙收回去。
- **在场角色**：`["玩家", "执法堂守卫", "苏清雪"]`
- **必须出现**：地牢、签到、第九格、债、妹妹、苏清雪
- **禁止**：让林凡当场答应开启第九格；让苏清雪说出全部真相；让债主直接解释规则
- **伏笔操作**：激活 `fs_ninth_slot`、`fs_black_vein`
- **验收**：信息量提升但不泄底；情绪转折成立；一致性通过

#### 场景 6 · 第三章 · 查账

- **brief**：
  > 次日，演武场公审。秦无咎掏出噬灵钉，指认林凡勾结魔修。林凡没有签到，而是请执法堂当众验钉；苏清雪把左袖黑纹亮在光下，守卫第一次说：「按律，先查钉，再查账。」噬灵钉一离手，戒律堂的暗账自己浮了出来：秦无咎的、管事的、守卫的，也包括林凡的。全宗哗然。结尾：林凡看向第九格，灰光里浮出一行小字——「债主不是一个人，是一本账。你准备怎么还？」
- **在场角色**：`["玩家", "秦无咎", "苏清雪", "执法堂守卫"]`
- **必须出现**：噬灵钉、按律、暗账、第九格、怎么还
- **禁止**：让系统解释全部真相；让秦无咎轻易认罪；让林凡靠签到翻盘
- **伏笔操作**：回收 `fs_devouring_nail`；保持 `fs_black_vein` 处于激活态，留到下一章回收
- **验收**：本章冲突收束；留下下一章钩子；质量分 ≥ 0.7

### 3.3 伏笔状态机（确定性）

生成完成后，按下列顺序调用
`POST /api/projects/<PID>/assets/foreshadowings/{foreshadow_id}/transition`：

```json
{"action": "reinforce"}
{"action": "activate"}
{"action": "resolve"}
```

| 伏笔 | 操作序列 | 预期状态 |
|---|---|---|
| `fs_ninth_slot` | `reinforce` → `activate` | `reinforced` → `activated` |
| `fs_black_vein` | `reinforce` → `activate` | `reinforced` → `activated` |
| `fs_devouring_nail` | `activate` → `resolve` | `activated` → `resolved` |

> 场景生成时伏笔 Agent 可能已经自动推进状态；若某一步的前置状态已满足，直接跳过该动作。
> 状态机只接受合法前置状态，返回 409 是保护行为，不是失败。

负向用例：

- 对 `planted` 状态的伏笔直接 `resolve` → **409**，错误信息包含「不允许执行 resolve」。
- 对已 `resolved` 的伏笔再次 `resolve` → **409**。
- `replant` 后 `reinforcement_count` 归零、状态回到 `planted`。

### 3.4 导出与指标（确定性）

1. `GET /api/projects/<PID>/export?format=md`
   - 包含 `# 青云宗 · 签到有债`、`> 文风：仙侠世界 · 现实后果 · 群像`；
   - 包含三个 `## 第N章` 标题，顺序与 `position` 一致；
   - 每个场景有 `### 场景 scene_N` 与正文。
2. `GET /api/projects/<PID>/export?format=txt` → 纯文本，无 Markdown 标记。
3. `GET /api/projects/<PID>/metrics`
   - `scene_count == 6`（若重跑过，按实际场景数）；
   - `avg_quality_score` 有值；
   - `model_calls` / `agent_calls` 非空；
   - `scenes` 中每项有 `scene_id`、`chapter_id`、`quality_score`、`duration_ms`。

### 3.5 作者模式 → 游戏模式的记忆交接（确定性）

先完成 §3.2（至少生成场景 1），再调用：

`GET /api/projects/<PID>/memory`

预期：

- `counts.archive >= 16`（5 个角色 + 5 条秘密 + 6 个地点，已生成场景还会更多）；
- `items` 中存在 `source="backfill"` 的场景索引；
- `prompt_block` 可读，`tiers` 为配置中的有序层；
- `settings` 为项目当前生效的记忆配置（tiers / key_events / demotion / retrieval）。

> 这一步验证「作品数据是事实来源，记忆索引可重建」，对应验收 A13。

---

## 4. 游戏模式测试剧本

### 4.1 准备与初始状态

1. 通过 Web 界面「试用模板」或 `POST /api/templates/xianxia_system/apply` 生成项目，资产与 §2.5 内嵌扩展自动就绪。
2. 实例：`instance_id = "xianxia_demo_001"`；行动者：`actor = "玩家"`。
3. 初始 `GET /runtime/v1/<PID>/state?instance_id=xianxia_demo_001` 断言：

| 项 | 预期 |
|---|---|
| `state.mode` | `game` |
| `state.time_minutes` | `480`（第1日 08:00） |
| `state.turn` | `0` |
| `state.characters` | 5 人，全部在「演武场」 |
| `state.facts` | 5 条「身份」事实 |
| `view.facts` | 只看到「玩家」自己的 1 条（A3） |
| `state.locations` | 本项目 6 个地点；「演武场」出口在 G1 应用地图 mod 后为 杂役院 / 藏经阁 / 后山禁地 |
| 默认选项 | 8 条（`WorldState.allowed_actions` 截断上限），自由输入不受限 |

### 4.2 回合脚本（确定性）

G1~G14 的请求统一为
`POST /runtime/v1/<PID>/turn`，`instance_id = "xianxia_demo_001"`，`mode = "game"`，`actor = "玩家"`，
并且**每一回合**都带 `enabled_extensions: ["map_xianxia", "skill_xianxia"]`（显式锁定期望的扩展组合）。
自由文本直接放在 `text` 字段（如 `{"text": "观察四周"}`）；跳过用 `{"wait": true}`。
G15 起切换为导演模式，按对应行传 `mode` 与 `overrides`。

> 「裁决」列是库层 `AdjudicationResult.outcome`，HTTP 响应不直接暴露 `error_code` / `available`。
> 断言以 `status`、`text`、`state`、`quality`、`choices` 为准。
>
> ⚠️ 裁决已改为导演 Agent 输出统一 JSON（`SceneCrew.adjudicate`），下表的时间增量、
> `moved / intercepted / not_found` 等是**参考结果**而非确定性断言：需要配置模型 Key，
> 并由 `map_xianxia` 提供地点与出口。无 Key 时只走最小兜底叙事（时间 +1、记一条 `freeform` 事件）。

| # | 玩家输入 | 路由 / 裁决 | 预期结果 | 关键断言 |
|---|---|---|---|---|
| G1 | 观察四周 | observe | `observed` | `status=ok`；时间不变；`turn +1`；文本含「苏清雪」「秦无咎」「杂役管事」「执法堂守卫」 |
| G2 | 与苏清雪交谈 | talk | `talked` | 时间 **+3**（08:03）；`relationships["玩家\|苏清雪"] == 1`；玩家情绪「放松」 |
| G3 | 前往藏经阁 | move | `moved` | 时间 **+10**（08:13）；位置「藏经阁」；情绪「警觉」；文本含「路上花了10分钟」 |
| G4 | 观察四周 | observe | `observed` | 文本为「你环顾四周，看见没有别人。」（信息隔离） |
| G5 | 前往杂役院 | move | `moved` | 时间 **+12**（08:25）；位置「杂役院」 |
| G6 | 去演武场 | move | `moved` | 时间 **+8**（08:33）；位置「演武场」 |
| G7 | 攻击秦无咎 | attack | `intercepted` | `status=ok`；文本含「执法堂守卫」「押往地牢」；位置「地牢」；情绪「恐惧」；时间 **+5**（08:38）；`flags.imprisoned_by == "执法堂守卫"`；`quality == 0.85`；`state_delta.events[-1].kind == "attack"` |
| G8 | 观察四周 | observe | `observed` | 文本「没有别人」（地牢与演武场隔离） |
| G9 | 前往演武场 | move | `moved` | 时间 **+6**（08:44）；回到「演武场」 |
| G10 | 瞬移到王宫 | move（`到` 触发） | `not_found` | `status=ok`；文本含「并不在你的世界地图上」；时间不变；`choices` 中的 move 目标为 杂役院 / 藏经阁 / 后山禁地（A2） |
| G11 | 使用系统面板 | use | `used` | `status=ok`；文本为通用兜底「你使用了手边的东西，暂时没有特别的变化。」；时间不变 |
| G12 | 存档 | — | — | `POST /runtime/v1/<PID>/saves`，body `{"instance_id":"xianxia_demo_001","label":"大比前"}`；返回 `save_id`；`GET .../saves` 的 `saves` 长度 1 |
| G13 | 前往藏经阁 → 读档 | move → load | `moved` → 恢复 | 移动后时间 08:54；`POST .../saves/{save_id}/load?instance_id=xianxia_demo_001` 后 `turn/time/location/relationships` 与存档时完全一致（A4） |
| G14 | 跳过 ×3 | skip | 第 3 次触发 NPC 自主 | 请求带 `idle_turns` 1/2/3；前两次 `status=idle`；第 3 次苏清雪与秦无咎各主动交谈一次；时间 **+6**；两条 `talk` 事件；`relationships` 各 +1（A9） |
| G15 | 切换到导演模式 | `POST /runtime/v1/<PID>/mode` | — | body `{"instance_id":"xianxia_demo_001","mode":"director"}`；`checkpoint_id` 非空；`state.mode=director`；`flags.force_director_frame=true`；出现 `mode_switch` 事件（A10） |
| G16 | 「镜头拉远：大比结束，秦无咎被执法堂带走。」 | director_command | `directed` | `status=ok`；`text` 等于导演指令；时间/位置不变（指令只负责叙述） |
| G17 | 「秦无咎当场被执法堂拿下。」+ overrides | director + FactOverride | `directed` | `state.characters["秦无咎"].status == "imprisoned"`；`state.overrides` 长度 1，记录 `before="active"`、`after="imprisoned"`、`base_snapshot_id` 非空；`flags["needs_review:秦无咎"] == true`；`log.overrides` 有 1 条（A8） |
| G18 | 切回游戏模式 | `POST .../mode` | — | 新 `checkpoint_id` 非空；`state.mode=game`；角色与 facts 保留；`flags.last_checkpoint_id` 等于新 checkpoint |

G17 请求体示例：

```json
{
  "instance_id": "xianxia_demo_001",
  "actor": "玩家",
  "mode": "director",
  "text": "秦无咎当场被执法堂拿下。",
  "enabled_extensions": ["map_xianxia", "skill_xianxia"],
  "overrides": [
    {
      "target": "秦无咎",
      "field": "status",
      "after": "imprisoned",
      "reason": "大比作弊，按律收押"
    }
  ]
}
```

### 4.3 负向与边界用例（确定性）

| # | 输入 / 操作 | 预期 |
|---|---|---|
| N1 | 在「藏经阁」输入「与苏清雪交谈」 | 文本为「苏清雪并不在这里。」；时间不变 |
| N2 | 在「藏经阁」输入「攻击」 | 文本为「你想出手，但身边没有可攻击的目标。」；时间不变 |
| N3 | 在「演武场」输入「前往演武场」 | 文本为「你已经在演武场了。」；时间不变 |
| N4 | 读一个不存在的 `save_id` | HTTP 404 |
| N5 | `POST .../mode` 传 `"mode": "author"` | HTTP 422（Literal 只接受 game / director） |
| N6 | 单回合传 `max_turns: 0` | `status=quota_exceeded`；不推进世界 |
| N7 | 单回合传 `max_duration_ms: 1` | `status=timeout`；状态保持原样 |
| N8 | 连续 `wait` | 时间只增不减；`turn` 每回合 +1 |

### 4.4 记忆与后端切换（确定性）

1. 完成 G14 后，`GET /api/projects/<PID>/memory`
   - `counts.archive >= 16`；
   - 游戏回合产生的近期文本进入 `short_term`（`counts.short_term >= 1`）；
   - `prompt_block` 含有最近场景的摘要或正文片段。
2. `PATCH /api/projects/<PID>/memory`，`{"backend": "hybrid"}`
   - 返回 `backend="hybrid"`，`settings.retrieval.backend` 同步为 `hybrid`；
   - 无 embedding 时自动退化为 fts，生成不中断（A14）。
3. `PATCH` 回 `fts`，计数不变。
4. 同一端点还可按字段调整 `tiers` / `key_events` / `demotion` / `retrieval`：
   `key_events` / `demotion` / `retrieval` 递归合并，`tiers` 整体替换；
   例如 `{"tiers": [...], "demotion": {"long_term": {"importance_threshold": 0.3}}}`；
   配置按项目落库；请求体结构错误返回 422，配置校验失败返回 400，且不改动已有配置。

---

## 5. 验收对照

| MVP 验收 | 本 Demo 对应 |
|---|---|
| A1 护卫拦截 | G7 |
| A2 非法传送 | G10 |
| A3 信息隔离 | 4.1 初始 `view.facts`、G4/G8 |
| A4 存档 → 读档 → 回放 | G12 / G13 |
| A5 扩展 skill / map | §2.5 + G3 旅行耗时 |
| A7 前端游戏模式 | G1~G11 可在 GamePanel 复现 |
| A8 导演改写与审计 | G17（回滚由 `tests/test_m0.py` 覆盖） |
| A9 NPC 自主 | G14 |
| A10 模式切换 | G15 / G18 |
| A11 短期压缩 / 重启恢复 | 追加生成第 7 个短场景（超过短期上限 6）后重启，检查 `counts` 中短期已压缩、长期/常驻已恢复 |
| A13 历史场景回填 | §3.5 |
| A14 检索后端切换 | §4.4 |
| A15 角色 secrets | `GET .../memory` 中 secret 条目的 `visibility` 为 `private:<角色>`；默认 `prompt_block` 不含 secret，按角色取 prompt 时只有本人可见 |

---

## 6. 已知边界（写测试时不要误判）

- **系统面板没有独立机制**：游戏模式的「使用」不会真发奖励，系统感来自作者模式正文与 skill 文风。
- **所有角色初始同场**：`WorldState.from_project` 把所有人放在第一地点，NPC 不会跟随玩家；这是 M0 行为，不是 bug。
- **导演指令默认不改状态**：要改状态必须走 `overrides`（FactOverride）；纯文本指令只产出叙述。
- **自由文本不再做动词路由**：「签到」「瞬移到王宫」这类输入整体交给导演 Agent 裁决，
  由 `map_xianxia` 的出口信息判断可达性；不再有 `move` / `not_found` 的硬编码分词分支。
- **默认选项上限 8 条**：由 `allowed_actions(...)[:8]` 截断；自由输入不受限制。
- **回滚没有 HTTP 端点**：`WorldState.rollback_override` 在库层与 `tests/test_m0.py` 中验证。
- **扩展来源**：内置扩展由试用模板内嵌提供（`src/storyloom/templates/`），`ExtensionRegistry` 启动时自动注册；需要隔离时用 `enabled_extensions`。
- **作者模式依赖模型 Key**：无 Key 时场景生成会失败；游戏模式无 Key 时走最小兜底叙事，可跑通但裁决不具语义。

---

## 7. 执行记录表

| 编号 | 用例 | 预期 | 实际 | 结论 |
|---|---|---|---|---|
| A-01 | 创建项目 + 资产 | 5 角色 / 6 地点 / 3 伏笔落库 |  |  |
| A-02 | 6 次场景生成 | 正文非空、质量分 ≥ 0.7、归属正确 |  |  |
| A-03 | 伏笔状态机 | 状态按表流转；非法流转 409 |  |  |
| A-04 | 导出 md / txt | 章节顺序与正文正确 |  |  |
| A-05 | 指标 | 场景数、质量分、模型调用非空 |  |  |
| A-06 | 记忆回填 | `archive` 含场景与资产 |  |  |
| G-01 | 初始状态 | 08:00 / turn 0 / 演武场 / 5 人 |  |  |
| G-02 | G1~G11 | 与 §4.2 一致 |  |  |
| G-03 | G12~G13 | 存读档状态一致 |  |  |
| G-04 | G14 | 第 3 次跳过触发 NPC 交谈 |  |  |
| G-05 | G15~G18 | 切换 / 改写 / 回切一致 |  |  |
| G-06 | N1~N8 | 负向用例全部符合 |  |  |
| G-07 | 记忆后端切换 | fts / hybrid 可切换 |  |  |
