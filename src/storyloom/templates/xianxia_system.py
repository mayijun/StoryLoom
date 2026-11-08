"""
试用模板：世界驱动仙侠 ·《青云宗 · 签到有债》。

与旧版「爽文系统流」不同，这一版把重点放在世界本身：

- 世界先于主角：NPC 有各自的目标、债务和行动逻辑，不围着玩家转；
- 后果驱动：每次「签到」都记一笔债，收益与代价同时发生；
- 群像：管事、师姐、首席、守卫都有自己的账，没人无条件帮玩家；
- 秘密只作线索：伏笔描述可以被看见，真相不会被旁白直接说出。

角色、地点、伏笔、章节大纲与扩展 manifest 的结构保持稳定，
以兼容既有测试与前端资产页；只重写叙事内容与文风约束。
"""

from typing import Any, Dict, List

from storyloom.templates import Template, register

TEMPLATE_ID = "xianxia_system"
TITLE = "青云宗 · 签到有债"
STYLE = "仙侠世界 · 现实后果 · 群像"
DESCRIPTION = (
    "青云宗外门杂役林凡被一纸「签到契」绑住：每一次看似白得的机缘，"
    "都会在第九格记下一笔债。大比在即，管事、师姐、首席各有各的账，"
    "没人有义务救他，也没人会等他长大。"
)

CHARACTERS: List[Dict[str, str]] = [
    {
        "name": "玩家",
        "importance_tier": "primary",
        "persona": (
            "林凡，十九岁，青云宗外门杂役弟子。说话慢，遇事先问代价，"
            "习惯把选择权推回给对方；不主动出头，也不轻易认命。"
            "被称作「废五行」，却总能看见别人看不见的那一格灰光。"
        ),
        "motivation": (
            "先弄清「签到契」每一笔的代价，再把妹妹林小满从外门管事手里赎回来。"
            "他并不想当什么仙尊，只想把账算清。"
        ),
        "secrets": (
            "他的灵根被称作「荒古圣体」，其实是一笔抵押：上一任宿主把未还完的债"
            "转到了他身上。每次签到都在第九格记一笔，同时拿走他一段与妹妹有关的记忆。"
        ),
    },
    {
        "name": "苏清雪",
        "importance_tier": "primary",
        "persona": (
            "内门大师姐，青云宗第一天才。清冷寡言，剑比话快；"
            "不替任何人做决定，也不欠任何人解释。对林凡的兴趣，"
            "更像是在核对一笔旧账。"
        ),
        "motivation": (
            "查清母亲留下的黑纹与签到契的关系，确认林凡是不是下一个债主，"
            "以及自己能不能把债转出去。"
        ),
        "secrets": (
            "她母亲是上一任宿主，死后债转到她左臂。她接近林凡，"
            "一半是调查，一半是想找一个替她还债的人。"
        ),
    },
    {
        "name": "秦无咎",
        "importance_tier": "primary",
        "persona": (
            "内门首席，出身长老世家。讲规矩，是因为规矩对他有利；"
            "笑的时候比不笑更危险，从不亲自动手。"
        ),
        "motivation": (
            "拿到进入后山禁地的资格，把秦家旧债从族谱上抹掉；"
            "林凡只是他用来向长老证明「杂役也能被规矩收拾」的一枚棋子。"
        ),
        "secrets": (
            "噬灵钉是戒律堂的收债法器，他借来对付林凡；"
            "一旦当众动用，所有暗账都会被反查，包括他自己的。"
        ),
    },
    {
        "name": "杂役管事",
        "importance_tier": "background",
        "persona": "尖嗓门，手里永远攥着账本，见人先看腰牌；对上面赔笑，对下面刻薄。",
        "motivation": "填上自己欠外门的印子钱，保住管事的位子。",
        "secrets": (
            "他把林凡的妹妹卖给了外门管事抵债，却谎称送去别院养病；"
            "账本上那一页被他撕了，但丹房还留着一张药单。"
        ),
    },
    {
        "name": "执法堂守卫",
        "importance_tier": "secondary",
        "persona": "铁面，只认戒律不认人，开口就是「按律」；但他从不站在没有胜算的一边。",
        "motivation": "守住执法堂的差事，别让戒律堂查到自己头上。",
        "secrets": (
            "他曾收过秦无咎一袋灵石，答应在关键时刻「来晚一步」；"
            "可一旦噬灵钉被当众取出，他必须选择先查谁。"
        ),
    },
]

LOCATIONS: List[Dict[str, str]] = [
    {
        "name": "演武场",
        "description": "青云宗外门大比的主场，青石擂台高九丈，四周幡旗猎猎；台下站着的每个人都在算自己的账。",
    },
    {
        "name": "杂役院",
        "description": "低矮石屋，晾着洗不净的灰布衣，墙角堆着劈好的柴；管事的小窗正对着每个人的进出。",
    },
    {
        "name": "藏经阁",
        "description": "七层木塔，每层檐角挂着一枚锈铃，越往上铃声越轻；有些书页被人提前撕走了。",
    },
    {
        "name": "丹房",
        "description": "药气熏人，三尊铜炉昼夜不熄，地上落满黑色药渣；药单和账本常常对不上。",
    },
    {
        "name": "地牢",
        "description": "戒律堂地牢，山腹深处的石牢，铁门上刻着「戒律」二字，灯油永远只够烧一夜。",
    },
    {
        "name": "后山禁地",
        "description": "断崖与古碑，雾气从地缝里往上涌，鸟兽绝迹；碑上的名字比宗门名册还旧。",
    },
]

FORESHADOWINGS: List[Dict[str, Any]] = [
    {
        "foreshadow_id": "fs_ninth_slot",
        "description": (
            "林凡脑海里的签到面板始终有第九格，灰得像一块死铁；"
            "每次签到，第九格都会轻轻震一下，像有人在本子上记了一笔。"
        ),
        "planted_in_scene": "scene_1",
        "target_revelation": (
            "第九格不是奖励，是债簿：每次签到都会把一段记忆、寿数或人情记到林凡名下，"
            "债主是上一任宿主。债可以拒还，但拒还的人会被全宗追债。"
        ),
        "max_dormant_scenes": 5,
        "linked_characters": ["玩家", "苏清雪"],
    },
    {
        "foreshadow_id": "fs_black_vein",
        "description": "苏清雪每次动用剑意，左袖口都会浮出一道极细的黑纹，像被墨线缝过。",
        "planted_in_scene": "scene_2",
        "target_revelation": (
            "她母亲是上一任宿主，黑纹是债转印记；她不是来救林凡的，"
            "而是在评估要不要把这笔债转给他。"
        ),
        "max_dormant_scenes": 5,
        "linked_characters": ["苏清雪", "玩家"],
    },
    {
        "foreshadow_id": "fs_devouring_nail",
        "description": (
            "秦无咎的储物戒内侧有一道新鲜划痕，里面那枚黑色长钉从不示人；"
            "每次戒律堂的人靠近，他都会下意识按住戒面。"
        ),
        "planted_in_scene": "scene_3",
        "target_revelation": (
            "噬灵钉是戒律堂的收债法器。秦无咎若当众动用它，"
            "会把所有人的暗账一起照亮：他自己的、管事的、守卫的，也包括林凡的。"
        ),
        "max_dormant_scenes": 5,
        "linked_characters": ["秦无咎", "玩家"],
    },
]

CHAPTERS: List[Dict[str, str]] = [
    {
        "chapter_id": "xianxia_ch_01",
        "title": "杂役院的第一笔",
        "outline": (
            "林凡在杂役院签到，第一次看见第九格记下一笔；管事克扣灵石，"
            "林凡可以选择忍、借势或动用签到奖励，每种选择都会留下痕迹。"
            "结尾：远处有人袖口一闪，像在确认他有没有签。"
        ),
    },
    {
        "chapter_id": "xianxia_ch_02",
        "title": "大比之日，人人有账",
        "outline": (
            "演武场大比，秦无咎用规则逼林凡上台，苏清雪试探，执法堂守卫冷眼旁观。"
            "林凡若动用签到，会被更多债主看见；胜负不自动等于翻身，"
            "因为台下的账比台上的剑更麻烦。"
        ),
    },
    {
        "chapter_id": "xianxia_ch_03",
        "title": "第九格的债主",
        "outline": (
            "夜里地牢，债主第一次开口；苏清雪带着自己的账来谈条件，"
            "秦无咎的噬灵钉让暗账曝光。结尾不是打脸，而是林凡必须决定："
            "还债、转债，还是让全宗一起查账。"
        ),
    },
]

# 扩展：原 examples/xianxia_demo/map_xianxia.yaml + skill_xianxia.yaml 合并内嵌
EXTENSIONS: List[Dict[str, Any]] = [
    {
        "id": "map_xianxia",
        "kind": "mod",
        "api_version": 1,
        "name": "青云宗地图",
        "description": "试用项目《青云宗 · 签到有债》的地点与路线；旅行时间统一按分钟。",
        "requires": {"time_resolution": "minute"},
        "contributes": {
            "state": {"namespace": "map", "fields": ["locations", "routes"]},
            "map": {
                "locations": [
                    {"name": "演武场", "description": "青云宗外门大比的主场。"},
                    {"name": "杂役院", "description": "低矮石屋，墙角堆着劈好的柴。"},
                    {"name": "藏经阁", "description": "七层木塔，檐角挂着锈铃。"},
                    {"name": "丹房", "description": "药气熏人，三尊铜炉昼夜不熄。"},
                    {"name": "地牢", "description": "戒律堂地牢，山腹深处的石牢。"},
                    {"name": "后山禁地", "description": "断崖与古碑，雾气从地缝里往上涌。"},
                ],
                "routes": [
                    {"from": "演武场", "to": "杂役院", "minutes": 8},
                    {"from": "杂役院", "to": "演武场", "minutes": 8},
                    {"from": "演武场", "to": "藏经阁", "minutes": 10},
                    {"from": "藏经阁", "to": "演武场", "minutes": 10},
                    {"from": "演武场", "to": "后山禁地", "minutes": 30},
                    {"from": "后山禁地", "to": "演武场", "minutes": 30},
                    {"from": "藏经阁", "to": "杂役院", "minutes": 12},
                    {"from": "杂役院", "to": "藏经阁", "minutes": 12},
                    {"from": "杂役院", "to": "丹房", "minutes": 12},
                    {"from": "丹房", "to": "杂役院", "minutes": 12},
                    {"from": "藏经阁", "to": "丹房", "minutes": 15},
                    {"from": "丹房", "to": "藏经阁", "minutes": 15},
                    {"from": "丹房", "to": "后山禁地", "minutes": 20},
                    {"from": "后山禁地", "to": "丹房", "minutes": 20},
                    # 地牢只留出口：被押进去后可以走回演武场
                    {"from": "地牢", "to": "演武场", "minutes": 6},
                ],
            },
            "rules": [
                {"id": "map.move", "access": "gm_only", "handler": "builtin.map.move"}
            ],
            "tools": [
                {
                    "id": "map.route",
                    "access": "llm_tool",
                    "read_only": True,
                    "handler": "builtin.map.route",
                }
            ],
        },
    },
    {
        "id": "skill_xianxia",
        "kind": "skill",
        "api_version": 1,
        "name": "仙侠世界 · 后果驱动",
        "description": (
            "世界先于主角；NPC 有各自的账；每次签到都要付出可见代价；"
            "秘密只作线索，结尾留可被行动回应的处境。"
        ),
        "contributes": {
            "prompt": (
                "用中文第三人称限制视角叙事，主角是林凡（资产名为「玩家」）。"
                "这是一个世界先于主角的仙侠故事：NPC 有各自的目标和账，世界不会围着玩家转；"
                "不要替玩家做决定，不要自动让玩家赢，不要让 NPC 无条件帮助或臣服。"
                "每次「签到」都必须付出可见代价（记忆、时间、寿数、人情或债），"
                "并在文本中留下具体痕迹。秘密只能作为线索出现，不得直接解释。"
                "每场结尾留一个具体、可被行动回应的处境，而不是总结。"
            )
        },
    },
]


register(
    Template(
        template_id=TEMPLATE_ID,
        title=TITLE,
        style=STYLE,
        description=DESCRIPTION,
        characters=CHARACTERS,
        locations=LOCATIONS,
        foreshadowings=FORESHADOWINGS,
        chapters=CHAPTERS,
        extensions=EXTENSIONS,
    )
)


__all__ = [
    "CHARACTERS",
    "CHAPTERS",
    "DESCRIPTION",
    "EXTENSIONS",
    "FORESHADOWINGS",
    "LOCATIONS",
    "STYLE",
    "TEMPLATE_ID",
    "TITLE",
]
