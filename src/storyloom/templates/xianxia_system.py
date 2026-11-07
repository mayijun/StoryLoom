"""
试用模板：爽文仙侠系统流 ·《系统逼我当仙尊》。

角色、地点、伏笔、章节大纲来自原 ``db/demo_seed.py``；
地图 mod 与文风 skill 由原 ``examples/xianxia_demo/*.yaml`` 合并内嵌，
不再以独立文本文件存在。试用结束后用户可直接删除项目清理。
"""

from typing import Any, Dict, List

from storyloom.templates import Template, register

TEMPLATE_ID = "xianxia_system"
TITLE = "系统逼我当仙尊"
STYLE = "爽文仙侠 · 系统流"
DESCRIPTION = (
    "外门杂役林凡绑定「诸天签到系统」，在大比之日被迫营业，"
    "一路签到开挂、当众打脸、惊动全宗。"
)

CHARACTERS: List[Dict[str, str]] = [
    {
        "name": "玩家",
        "importance_tier": "primary",
        "persona": (
            "林凡，十六岁，青云宗外门杂役弟子。天生「废五行」灵根，说话懒散，"
            "遇事先算收益；被系统逼着高调，内心只想躺平。习惯用「行吧」开头。"
        ),
        "motivation": "攒够灵石赎回被宗门扣在别院的妹妹林小满，顺便查清系统为什么选中自己。",
        "secrets": (
            "他的灵根不是废，而是被系统封印的「荒古圣体」；"
            "开启签到第九格会让他失去一段与妹妹有关的记忆。"
        ),
    },
    {
        "name": "苏清雪",
        "importance_tier": "primary",
        "persona": (
            "内门大师姐，青云宗第一天才。清冷寡言，剑比话快；"
            "对林凡从怀疑到护短，嘴上从不承认。"
        ),
        "motivation": "查出林凡身上那股不属于炼气期的气息。",
        "secrets": "她的母亲是上一任系统宿主，死于「第九格」。",
    },
    {
        "name": "秦无咎",
        "importance_tier": "primary",
        "persona": (
            "内门首席，出身长老世家。笑的时候比不笑更危险，"
            "最爱在众人面前讲规矩。"
        ),
        "motivation": "保住首席之位，拿到进入后山禁地的资格。",
        "secrets": "暗中修炼魔功，储物戒里藏着一枚宗门禁物「噬灵钉」。",
    },
    {
        "name": "杂役管事",
        "importance_tier": "background",
        "persona": "尖嗓门，手里永远攥着账本，见人先看腰牌。",
        "motivation": "克扣杂役灵石，攒钱给儿子买筑基丹。",
        "secrets": "他把林凡的妹妹卖给了外门管事，却谎称送去别院养病。",
    },
    {
        "name": "执法堂守卫",
        "importance_tier": "secondary",
        "persona": "铁面，只认戒律不认人，开口就是「按律」。",
        "motivation": "维护大比秩序。",
        "secrets": "他曾收过秦无咎一袋灵石，答应在关键时刻「来晚一步」。",
    },
]

LOCATIONS: List[Dict[str, str]] = [
    {"name": "演武场", "description": "青云宗外门大比的主场，青石擂台高九丈，四周幡旗猎猎。"},
    {"name": "杂役院", "description": "低矮石屋，晾着洗不净的灰布衣，墙角堆着劈好的柴。"},
    {"name": "藏经阁", "description": "七层木塔，每层檐角挂着一枚锈铃，越往上铃声越轻。"},
    {"name": "丹房", "description": "药气熏人，三尊铜炉昼夜不熄，地上落满黑色药渣。"},
    # 资产名用精确的「地牢」：护卫拦截按 PRISON_LOCATION 精确命中。
    {"name": "地牢", "description": "戒律堂地牢，山腹深处的石牢，铁门上刻着「戒律」二字。"},
    {"name": "后山禁地", "description": "断崖与古碑，雾气从地缝里往上涌，鸟兽绝迹。"},
]

FORESHADOWINGS: List[Dict[str, Any]] = [
    {
        "foreshadow_id": "fs_ninth_slot",
        "description": (
            "林凡脑海里的诸天签到面板始终有第九格，灰得像一块死铁；"
            "每次签到，第九格都会轻轻震一下。"
        ),
        "planted_in_scene": "scene_1",
        "target_revelation": (
            "第九格不是奖励，是债：上一任宿主的残魂住在里面，"
            "每次开启都会夺走林凡一段与妹妹有关的记忆。"
        ),
        "max_dormant_scenes": 5,
        "linked_characters": ["玩家", "苏清雪"],
    },
    {
        "foreshadow_id": "fs_black_vein",
        "description": "苏清雪每次动用剑意，左袖口都会浮出一道极细的黑纹，像被墨线缝过。",
        "planted_in_scene": "scene_2",
        "target_revelation": (
            "她母亲是上一任系统宿主，黑纹是「第九格」留下的契约印记；"
            "她也在被系统追债。"
        ),
        "max_dormant_scenes": 5,
        "linked_characters": ["苏清雪", "玩家"],
    },
    {
        "foreshadow_id": "fs_devouring_nail",
        "description": (
            "秦无咎的储物戒内侧有一道新鲜划痕，里面那枚黑色长钉从不示人。"
        ),
        "planted_in_scene": "scene_3",
        "target_revelation": (
            "他准备在大比决赛用「噬灵钉」废掉林凡，"
            "反被系统签到奖励「万剑归宗」当众打脸。"
        ),
        "max_dormant_scenes": 5,
        "linked_characters": ["秦无咎", "玩家"],
    },
]

CHAPTERS: List[Dict[str, str]] = [
    {
        "chapter_id": "xianxia_ch_01",
        "title": "签到荒古圣体",
        "outline": (
            "外门杂役林凡在杂役院签到觉醒荒古圣体；管事克扣灵石，"
            "林凡第一次用系统奖励打脸；结尾第九格亮起一线。"
        ),
    },
    {
        "chapter_id": "xianxia_ch_02",
        "title": "大比之日，全宗都在看我",
        "outline": (
            "演武场外门大比，秦无咎当众羞辱林凡；苏清雪出手试探；"
            "林凡签到「一剑破万法」，一剑惊宗。"
        ),
    },
    {
        "chapter_id": "xianxia_ch_03",
        "title": "师姐，我真不是隐藏大佬",
        "outline": (
            "林凡被押进地牢又莫名其妙被放出；苏清雪夜访，黑纹暴露；"
            "秦无咎掏出噬灵钉反被直播回放打脸，第九格亮起，债主就位。"
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
        "description": "试用项目《系统逼我当仙尊》的地点与路线；旅行时间统一按分钟。",
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
        "name": "爽文仙侠系统流",
        "description": "短句、强节奏、打脸及时；系统提示用【】标出，每场结尾留钩子。",
        "contributes": {
            "prompt": (
                "用中文第三人称叙事，主角是林凡（资产名为「玩家」）。短句为主，段落不超过四句；"
                "爽点要落在动作和结果上，不解释系统原理；系统提示统一用【】包裹；"
                "不替玩家做决定，不新增未经裁决的事实；每场结尾留一个具体钩子。"
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
