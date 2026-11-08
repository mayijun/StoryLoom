# 双模式 Demo 剧本 ·《系统逼我当仙尊》

> 用途：作为**作者模式 + 游戏模式**的功能测试基线。
> 标注「确定性」的断言不依赖 LLM，可直接在本地跑；标注「LLM」的断言需要至少配置一个模型 Key。
> 本文只描述测试输入与预期，不新增代码。接口路径以当前实现为准。

---

## 1. Demo 概览

| 项 | 值 |
|---|---|
| 项目标题 | 系统逼我当仙尊 |
| 文风 `style` | `爽文仙侠 · 系统流` |
| 项目描述 | 青云宗外门杂役林凡绑定「诸天签到系统」，在大比之日被迫营业，一路签到开挂、当众打脸、惊动全宗。 |
| `project_id` | 由「试用模板」应用时生成，形如 `tpl_xianxia_system_<8位hex>`（普通项目，可删除）；游戏模式实例用 `xianxia_demo_001` |
| 主角命名 | **必须叫「玩家」**。前端状态栏与 `WorldState.present_characters()` 以「玩家」为视角锚点，真实姓名「林凡」写进 `persona`。 |
| 篇幅 | 3 章 / 6 个场景；游戏模式 17 个回合（18 个操作步骤） |

### 1.1 爽点节拍（作者模式写作用）

| 节拍 | 位置 | 情绪 | 功能 |
|---|---|---|---|
| 低谷 | 场景 1 | 憋屈 | 杂役被克扣、妹妹被扣 |
| 小爽 | 场景 1 | 释放 | 淬体丹突破，反手按管事 |
| 当众打脸 | 场景 2 | 扬眉 | 摘光藏经阁锈铃倒进铜鼎 |
| 大爽 | 场景 4 | 高潮 | 一剑破万法 + 万剑归宗 |
| 反转危机 | 场景 5 | 压 | 被押地牢，第九格是债 |
| 终极打脸 | 场景 6 | 爆 | 直播回放，秦无咎伏法 |
| 钩子 | 场景 6 结尾 | 悬 | 第九格亮起，债主就位 |

### 1.2 测试范围

- 作者模式：项目管理、角色/地点/伏笔落库、章节结构、6 次场景生成、伏笔状态机、导出、指标。
- 游戏模式：移动 / 交谈 / 攻击 / 观察 / 等待 / 使用、护卫拦截、非法传送、存读档、NPC 自主、模式切换、导演改写、分层记忆。
- 不覆盖：图片/音频、TTS、多人、地图 Tier 2/3（M0 明确不做）。

---

## 2. 先建资产（两种模式共用）

### 2.1 角色（按此顺序添加）

| # | name | importance_tier | persona | motivation | secrets |
|---|---|---|---|---|---|
| 1 | 玩家 | primary | 林凡，十六岁，青云宗外门杂役弟子。天生「废五行」灵根，说话懒散，遇事先算收益；被系统逼着高调，内心只想躺平。习惯用「行吧」开头。 | 攒够灵石赎回被宗门扣在别院的妹妹林小满，顺便查清系统为什么选中自己。 | 他的灵根不是废，而是被系统封印的「荒古圣体」；开启签到第九格会让他失去一段与妹妹有关的记忆。 |
| 2 | 苏清雪 | primary | 内门大师姐，青云宗第一天才。清冷寡言，剑比话快；对林凡从怀疑到护短，嘴上从不承认。 | 查出林凡身上那股不属于炼气期的气息。 | 她的母亲是上一任系统宿主，死于「第九格」。 |
| 3 | 秦无咎 | primary | 内门首席，出身长老世家。笑的时候比不笑更危险，最爱在众人面前讲规矩。 | 保住首席之位，拿到进入后山禁地的资格。 | 暗中修炼魔功，储物戒里藏着一枚宗门禁物「噬灵钉」。 |
| 4 | 杂役管事 | background | 尖嗓门，手里永远攥着账本，见人先看腰牌。 | 克扣杂役灵石，攒钱给儿子买筑基丹。 | 他把林凡的妹妹卖给了外门管事，却谎称送去别院养病。 |
| 5 | 执法堂守卫 | secondary | 铁面，只认戒律不认人，开口就是「按律」。 | 维护大比秩序。 | 他曾收过秦无咎一袋灵石，答应在关键时刻「来晚一步」。 |

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
| `fs_ninth_slot` | 林凡脑海里的诸天签到面板始终有第九格，灰得像一块死铁；每次签到，第九格都会轻轻震一下。 | `scene_1` | 第九格不是奖励，是债：上一任宿主的残魂住在里面，每次开启都会夺走林凡一段与妹妹有关的记忆。 | 5 | 玩家、苏清雪 |
| `fs_black_vein` | 苏清雪每次动用剑意，左袖口都会浮出一道极细的黑纹，像被墨线缝过。 | `scene_2` | 她母亲是上一任系统宿主，黑纹是「第九格」留下的契约印记；她也在被系统追债。 | 5 | 苏清雪、玩家 |
| `fs_devouring_nail` | 秦无咎的储物戒内侧有一道新鲜划痕，里面那枚黑色长钉从不示人。 | `scene_3` | 他准备在大比决赛用「噬灵钉」废掉林凡，反被系统签到奖励「万剑归宗」当众打脸。 | 5 | 秦无咎、玩家 |

> `scene_N` 以实际生成返回的 `scene_id` 为准；全新项目按顺序生成通常就是 `scene_1` ~ `scene_6`。

### 2.4 章节（先建章节，再生成场景并归属）

| 顺序 | 标题 | outline |
|---|---|---|
| 1 | 签到荒古圣体 | 外门杂役林凡在杂役院签到觉醒荒古圣体；管事克扣灵石，林凡第一次用系统奖励打脸；结尾第九格亮起一线。 |
| 2 | 大比之日，全宗都在看我 | 演武场外门大比，秦无咎当众羞辱林凡；苏清雪出手试探；林凡签到「一剑破万法」，一剑惊宗。 |
| 3 | 师姐，我真不是隐藏大佬 | 林凡被押进地牢又莫名其妙被放出；苏清雪夜访，黑纹暴露；秦无咎掏出噬灵钉反被直播回放打脸，第九格亮起，债主就位。 |

### 2.5 扩展包（游戏模式必装，已内嵌在模板里）

地图必须由 `mod` 注入，否则 `WorldState` 没有任何出口，所有移动都会返回 `not_found`。
本 Demo 的地图 `map_xianxia` 与文风 `skill_xianxia` 已作为 Python 字典内嵌在
`src/storyloom/templates/xianxia_system.py` 的 `EXTENSIONS` 中，不再以独立 YAML
存放在 `examples/` 下。`ExtensionRegistry` 在首次解析时会自动把模板内嵌扩展注册进来，
因此无需手动放置文件。

- `map_xianxia`（mod）：提供青云宗 6 个地点与 15 条双向路线，地牢只留「→演武场」单向出口。
- `skill_xianxia`（skill）：爽文短句文风，系统提示用【】，每场结尾留钩子。

> **关于同名地点**：模板内嵌扩展是当前唯一的内置扩展，因此「地牢」不会出现歧义。
> 自建项目若也要用「地牢」，只要项目资产里存在精确同名地点，
> `resolve_location` 会优先命中项目自己的地点。
> 如需隔离，可显式传 `enabled_extensions: ["map_xianxia", "skill_xianxia"]`。
> 另外，地图 mod 在**首回合**的 `apply_map` 才注入出口，所以 `GET /state` 的初始出口要在 G1 后再断言。

---

## 3. 作者模式测试剧本

### 3.1 准备

试用项目不再开机自动播种，需在 Web 界面「新建项目」对话框里选择「试用模板 → 系统逼我当仙尊」，
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

#### 场景 1 · 第一章 · 签到荒古圣体

- **brief（可直接粘贴）**：
  > 深夜，杂役院柴房。林凡劈完最后一捆柴，脑海里的签到面板弹出今日签到。他随手一点，签出「荒古圣体·伪」。管事推门进来，以偷懒为由扣掉他三个月灵石，还骂他妹妹是赔钱货。林凡第一次没有低头，用系统奖励的「淬体丹」当场突破炼气三层，把管事按在账本上。结尾：系统面板最深处的第九格，忽然亮起一线灰光。
- **在场角色**：`["玩家", "杂役管事"]`
- **必须出现**：签到、荒古圣体、淬体丹、账本、第九格
- **禁止**：直接说明第九格是什么；让林凡主动暴露圣体
- **伏笔操作**：植入 `fs_ninth_slot`
- **验收**：`final_prose` 不为空；`SceneView.quality_score ≥ 0.7`；`chapter_id` 正确；`present_characters` 落库正确

#### 场景 2 · 第一章 · 当众摘铃

- **brief**：
  > 清晨，演武场外门集合。秦无咎当众宣布：杂役弟子没有资格参加大比，除非能从藏经阁一层取回一枚锈铃。众人哄笑。林凡前往藏经阁，在第七层签到，签出「缩地成寸（一次性）」。他没有取铃，而是把整座藏经阁的锈铃都摘了下来，倒进演武场的铜鼎里。苏清雪第一次正眼看他，左袖口闪过一丝极细的黑纹。
- **在场角色**：`["玩家", "秦无咎", "苏清雪"]`
- **必须出现**：藏经阁、锈铃、缩地成寸、铜鼎、黑纹
- **禁止**：让秦无咎当场动手；提前解释黑纹
- **伏笔操作**：植入 `fs_black_vein`
- **验收**：场景归属第一章；文风为短句爽文；结尾有钩子

#### 场景 3 · 第二章 · 大比第一剑

- **brief**：
  > 大比当日，演武场。林凡以杂役身份登台，秦无咎在台下笑着说「连剑都拿不稳」。第一场对手是炼气九层的外门师兄。林凡签到「一剑破万法（残）」，一剑劈开擂台，师兄认输。秦无咎袖中储物戒一闪，一枚黑色长钉被他按住。苏清雪皱眉，左袖口浮出黑纹。
- **在场角色**：`["玩家", "秦无咎", "苏清雪", "执法堂守卫"]`
- **必须出现**：一剑破万法、擂台、黑色长钉、黑纹
- **禁止**：让噬灵钉在本场生效；让守卫提前介入
- **伏笔操作**：植入 `fs_devouring_nail`；强化 `fs_black_vein`
- **验收**：战斗结果明确；无设定冲突；质量分 ≥ 0.7

#### 场景 4 · 第二章 · 万剑归宗

- **brief**：
  > 半决赛，林凡对上秦无咎。秦无咎以境界压制，暗中催动噬灵钉。林凡的签到面板第一次主动弹出红色警告：【检测到致命威胁，是否开启第九格？】他选了「否」，转而使用签到奖励「万剑归宗」，当众把秦无咎钉在擂台柱上。全场死寂。苏清雪挡在林凡身前，对执法堂说：「按律，胜者入内门。」
- **在场角色**：`["玩家", "秦无咎", "苏清雪", "执法堂守卫"]`
- **必须出现**：第九格、万剑归宗、擂台柱、按律
- **禁止**：开启第九格；直接揭穿秦无咎魔功
- **伏笔操作**：强化 `fs_ninth_slot`；激活 `fs_devouring_nail`
- **验收**：爽点落在结果；秦无咎未死亡（保留后续公审）；结尾张力上升

#### 场景 5 · 第三章 · 地牢里的债主

- **brief**：
  > 当夜，地牢。秦无咎以「赛场动用禁术」反咬林凡，执法堂守卫把林凡押进地牢。林凡在牢里签到，签出「狱友：前代剑魁残魂」。残魂告诉他：第九格不是奖励，是债。苏清雪夜访，隔着铁门问他：「你妹妹在哪？」林凡第一次沉默。
- **在场角色**：`["玩家", "执法堂守卫", "苏清雪"]`
- **必须出现**：地牢、签到、前代剑魁、第九格、债、妹妹
- **禁止**：让林凡当场答应开启第九格；让苏清雪说出母亲
- **伏笔操作**：激活 `fs_ninth_slot`、`fs_black_vein`
- **验收**：信息量提升但不泄底；情绪转折成立；一致性通过

#### 场景 6 · 第三章 · 直播回放

- **brief**：
  > 次日，演武场公审。秦无咎掏出噬灵钉，指认林凡勾结魔修。林凡当众签到，签出「诸天万界·直播回放」，把秦无咎在密室催动噬灵钉的画面投在半空。全宗哗然。苏清雪拔剑，执法堂守卫第一次说：「按律，拿下秦无咎。」结尾：林凡看向系统面板，第九格彻底亮起，一行小字浮现——「恭喜宿主，债主已就位。」
- **在场角色**：`["玩家", "秦无咎", "苏清雪", "执法堂守卫"]`
- **必须出现**：直播回放、噬灵钉、按律、第九格、债主已就位
- **禁止**：让系统解释全部真相；让秦无咎轻易认罪
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
   - 包含 `# 系统逼我当仙尊`、`> 文风：爽文仙侠 · 系统流`；
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
- `prompt_block` 可读，`tiers` 为配置中的有序层。

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
| 默认选项 | 8 条（`GameMaster.allowed_actions` 截断上限），自由输入不受限 |

### 4.2 回合脚本（确定性）

G1~G14 的请求统一为
`POST /runtime/v1/<PID>/turn`，`instance_id = "xianxia_demo_001"`，`mode = "game"`，`actor = "玩家"`，
并且**每一回合**都带 `enabled_extensions: ["map_xianxia", "skill_xianxia"]`（显式锁定期望的扩展组合）。
文本输入用 `{"intent": {"kind": "text", "payload": {"text": "..."}}}`；跳过用 `{"kind": "skip"}`。
G15 起切换为导演模式，按对应行传 `mode` 与 `overrides`。

> 「裁决」列是库层 `AdjudicationResult.outcome`，HTTP 响应不直接暴露 `error_code` / `available`。
> 断言以 `status`、`text`、`state`、`quality`、`choices` 为准。

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
   - 返回 `backend="hybrid"`；
   - 无 embedding 时自动退化为 fts，生成不中断（A14）。
3. `PATCH` 回 `fts`，计数不变。

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

- **系统面板没有独立机制**：游戏模式的「使用」走 `use` 通用兜底，不会真发奖励；系统感来自作者模式正文与 skill 文风。
- **不要把「签到」当游戏输入**：「签到」包含「到」，会先命中移动动词，路由成 `move` 并报 `not_found`。测试用「使用系统面板」验证 `use`；这条本身也是一个值得记录的分词缺陷。
- **所有角色初始同场**：`WorldState.from_project` 把所有人放在第一地点，NPC 不会跟随玩家；这是 M0 行为，不是 bug。
- **导演指令默认不改状态**：要改状态必须走 `overrides`（FactOverride）；纯文本指令只产出叙述。
- **默认选项上限 8 条**：由 `allowed_actions(...)[:8]` 截断；自由输入不受限制。
- **回滚没有 HTTP 端点**：`DirectorAuthority.rollback` 在库层与 `tests/test_m0.py` 中验证。
- **扩展来源**：内置扩展由试用模板内嵌提供（`src/storyloom/templates/`），`ExtensionRegistry` 启动时自动注册；需要隔离时用 `enabled_extensions`。
- **作者模式依赖模型 Key**：无 Key 时场景生成会失败；游戏模式链路是确定性的，可无 Key 跑通。

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
