"""
试用模板：现代都市开放沙盒人生 ·《临江市 · 平行人生》。

与线性叙事模板不同，这一版把重点放在"无剧本的世界"上：

- 世界先于主角：室友、组长、老板娘、发小各有动机与日程，不围着玩家转；
- 后果真实：时间、金钱、人情，每个选择都有代价，代价全部兑现；
- 信息迷雾：玩家不知道的就是不知道，NPC 只能说他有途径知道的事；
- 开放沙盒：只有开场态势，没有剧本；玩家可以上进、躺平、冒险或违法，
  世界给出真实的社会、法律与经济后果。

角色、地点、伏笔、章节大纲与扩展 manifest 的结构与既有模板保持一致，
以兼容既有测试与前端资产页。
"""

from typing import Any, Dict, List

from storyloom.templates import Template, register

TEMPLATE_ID = "sandbox_life"
TITLE = "临江市 · 平行人生"
STYLE = "现代都市 · 开放沙盒 · 现实后果"
DESCRIPTION = (
    "临江市入秋，月初交租日。没有剧本，也没有主角光环：室友说去加班，"
    "组长贴出「优化排班」，发小发来一句「在吗」。世界不为谁停转，"
    "你伤害过的人会记仇，帮过的人未必报恩，每个选择都有代价。"
)

CHARACTERS: List[Dict[str, str]] = [
    {
        "name": "玩家",
        "importance_tier": "primary",
        "persona": (
            "默认人设：25 岁，临江市老城区合租房住户，城郊物流仓库理货员，"
            "存款两万三，没房没车。话不多，习惯先看人再说话。"
            "（这是默认人设：玩家首轮可自定义姓名/性别/年龄/职业/出身/目标，"
            "以玩家输入为准。）"
        ),
        "motivation": (
            "先交上下个月房租（800 元），再想想是熬转正，还是找个别的不那么累的活。"
        ),
        "secrets": (
            "上个月替室友高远垫过一次水电费，没跟任何人说；"
            "他最怕母亲打电话问「钱还够不够」。"
        ),
    },
    {
        "name": "高远",
        "importance_tier": "primary",
        "persona": (
            "玩家的合租室友，二十六岁，前教培行业课程顾问。被裁三个月，"
            "白天照样拎包出门装上班，实际在网吧投简历。嘴上爱说「没事」，"
            "烟越抽越凶。"
        ),
        "motivation": (
            "在下个月房租到期前找到工作，同时瞒住所有人——包括玩家——他借了网贷。"
        ),
        "secrets": (
            "他欠了两家网贷平台共一万八，催收电话已经打到了他母亲那里，"
            "下一步就会打到合租房。"
        ),
    },
    {
        "name": "马国梁",
        "importance_tier": "secondary",
        "persona": (
            "物流仓库夜班组长，四十多岁，说话带厂区口音，手里永远攥着排班表。"
            "对上面点头哈腰，对下面一碗水端得很平——平到冷酷。"
        ),
        "motivation": (
            "仓库要砍编制，他必须在本月交出一份「表现排名」；"
            "他不想得罪人，但更不想丢自己的位置。"
        ),
        "secrets": (
            "裁员名单初稿他见过，高远的名字在上面；"
            "他还没决定要不要提前透口风。"
        ),
    },
    {
        "name": "陈姨",
        "importance_tier": "background",
        "persona": (
            "合租房楼下小饭馆老板娘，五十岁，消息比谁都灵通，赊账看人。"
            "谁加班、谁吵架、谁搬家，她都知道。"
        ),
        "motivation": (
            "守住小店供儿子读大学；她想多一个常客，也想少一个惹事的。"
        ),
        "secrets": (
            "她记得每个赊账的人，账本就压在收银台玻璃板底下；"
            "前租客欠了三个月饭钱跑了，从此她不再轻易赊账。"
        ),
    },
    {
        "name": "罗倩",
        "importance_tier": "secondary",
        "persona": (
            "玩家发小，二十四岁，化妆品多级分销的「小代理」，朋友圈永远光鲜。"
            "她找玩家不是叙旧，是找下家。"
        ),
        "motivation": (
            "上线在催她本月业绩，她需要拉一个人头或出一笔货；"
            "玩家是她通讯录里「最好说话」的那个。"
        ),
        "secrets": (
            "她自己囤了两万块的货砸在手里，上线答应的「月入过万」从没兑现；"
            "她不敢退出，退出就血本无归。"
        ),
    },
]

LOCATIONS: List[Dict[str, str]] = [
    {
        "name": "合租房",
        "description": (
            "临江市老城区六层步梯楼的三楼，两室一厅隔成三间，"
            "厨房台面永远有一层油；楼下是陈姨的小饭馆。"
        ),
    },
    {
        "name": "物流仓库",
        "description": (
            "城郊物流园三号仓，货架高九米，夜班的灯永远比人先到；"
            "组长办公室的小窗正对着分拣线。"
        ),
    },
    {
        "name": "夜市大排档",
        "description": (
            "仓库后街的夜市，塑料桌椅摆到马路牙子上，炒粉的锅气混着啤酒味；"
            "凌晨两点才散场。"
        ),
    },
    {
        "name": "网吧",
        "description": (
            "居民楼地下室的网吧，烟味和泡面味不散；包夜十五块，"
            "角落的机器键盘缺了两个键帽。"
        ),
    },
    {
        "name": "滨江步道",
        "description": (
            "滨江绿道，晚上有人跑步、钓鱼、摆摊；长椅朝向江面，"
            "是这座城市唯一不催人赶路的地方。"
        ),
    },
    {
        "name": "银行网点",
        "description": (
            "街角的银行网点，取号机吐出的纸条印着前面还有十七个人；"
            "ATM 区 24 小时亮着灯。"
        ),
    },
]

FORESHADOWINGS: List[Dict[str, Any]] = [
    {
        "foreshadow_id": "fs_layoff_list",
        "description": (
            "仓库公告栏贴出「优化排班」通知，用词含糊；"
            "马国梁最近总把排班表反扣在桌上。"
        ),
        "planted_in_scene": "scene_1",
        "target_revelation": (
            "裁员名单上有高远的名字——他已经三个月没班可上却一直瞒着；"
            "名单公布那天，合租房的房租会少一个人分担。"
        ),
        "max_dormant_scenes": 5,
        "linked_characters": ["玩家", "高远", "马国梁"],
    },
    {
        "foreshadow_id": "fs_gaoyuan_debt",
        "description": (
            "高远的手机总在深夜震动，他看一眼就按掉；"
            "有一次玩家瞥见来电显示是一串外地号码。"
        ),
        "planted_in_scene": "scene_1",
        "target_revelation": (
            "催收电话打到合租房，高远的网贷败露；"
            "他要么向玩家摊牌借钱，要么连夜搬走。"
        ),
        "max_dormant_scenes": 5,
        "linked_characters": ["玩家", "高远"],
    },
    {
        "foreshadow_id": "fs_luoqian_scheme",
        "description": (
            "罗倩的朋友圈一天比一天光鲜，私聊却越来越频繁，"
            "话题总往「副业」「机会」上引。"
        ),
        "planted_in_scene": "scene_1",
        "target_revelation": (
            "罗倩摊牌要玩家「入伙」或借钱囤货；她上线已失联过一次，"
            "她比谁都清楚这是击鼓传花。"
        ),
        "max_dormant_scenes": 5,
        "linked_characters": ["玩家", "罗倩"],
    },
]

CHAPTERS: List[Dict[str, str]] = [
    {
        "chapter_id": "sandbox_ch_01",
        "title": "入秋 · 交租日",
        "outline": (
            "月初，房东的催租消息躺在手机里；玩家上夜班前在楼下陈姨的饭馆吃饭，"
            "高远说「公司加班」出了门，仓库贴出「优化排班」的通知，"
            "罗倩发来一条「在吗」。四条线同时动，玩家先回应哪一条、怎么回应，"
            "都会留下痕迹。本章只设开场态势，之后没有剧本。"
        ),
    },
]

# 扩展：地图 mod + 沙盒规则 skill 内嵌
EXTENSIONS: List[Dict[str, Any]] = [
    {
        "id": "map_sandbox_life",
        "kind": "mod",
        "api_version": 1,
        "name": "临江市地图",
        "description": "试用项目《临江市 · 平行人生》的地点与路线；旅行时间统一按分钟。",
        "requires": {"time_resolution": "minute"},
        "contributes": {
            "state": {"namespace": "map", "fields": ["locations", "routes"]},
            "map": {
                "locations": [
                    {"name": "合租房", "description": "老城区步梯楼三楼，楼下是陈姨的小饭馆。"},
                    {"name": "物流仓库", "description": "城郊物流园三号仓，夜班灯比人先到。"},
                    {"name": "夜市大排档", "description": "仓库后街的夜市，凌晨两点才散场。"},
                    {"name": "网吧", "description": "居民楼地下室，包夜十五块。"},
                    {"name": "滨江步道", "description": "滨江绿道，全城唯一不催人赶路的地方。"},
                    {"name": "银行网点", "description": "街角网点，ATM 区 24 小时亮灯。"},
                ],
                "routes": [
                    {"from": "合租房", "to": "物流仓库", "minutes": 25},
                    {"from": "物流仓库", "to": "合租房", "minutes": 25},
                    {"from": "合租房", "to": "夜市大排档", "minutes": 8},
                    {"from": "夜市大排档", "to": "合租房", "minutes": 8},
                    {"from": "合租房", "to": "网吧", "minutes": 10},
                    {"from": "网吧", "to": "合租房", "minutes": 10},
                    {"from": "合租房", "to": "滨江步道", "minutes": 12},
                    {"from": "滨江步道", "to": "合租房", "minutes": 12},
                    {"from": "合租房", "to": "银行网点", "minutes": 6},
                    {"from": "银行网点", "to": "合租房", "minutes": 6},
                    {"from": "夜市大排档", "to": "网吧", "minutes": 5},
                    {"from": "网吧", "to": "夜市大排档", "minutes": 5},
                    {"from": "物流仓库", "to": "银行网点", "minutes": 15},
                    {"from": "银行网点", "to": "物流仓库", "minutes": 15},
                    {"from": "滨江步道", "to": "夜市大排档", "minutes": 10},
                    {"from": "夜市大排档", "to": "滨江步道", "minutes": 10},
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
        "id": "skill_sandbox_life",
        "kind": "skill",
        "api_version": 1,
        "name": "开放沙盒 · 现实后果",
        "description": (
            "无剧本、无主角光环；时间与金钱精确；信息迷雾；关系渐进且不对称；"
            "意图不审查但后果真实；NPC 各自生活并兑现承诺；结尾留可被行动回应的处境。"
        ),
        "contributes": {
            "prompt": (
                "用中文第二人称「你」叙事，主角是玩家（资产名为「玩家」）。"
                "【建卡】首轮若玩家给出自定义人设（姓名/性别/年龄/职业/出身/目标）"
                "或叙事人称要求，以玩家输入为准覆盖默认人设；否则使用默认人设。"
                "【无剧本】世界不围着玩家转：NPC 各有动机与日程；不替玩家做决定，"
                "不预判意图，不让玩家自动成功。"
                "【时间与金钱】叙述中的时刻、耗时、金额必须具体且前后一致；"
                "支出要有来源、收入要有去处；任何行动（含躺平、睡觉）都消耗时间并产生后果。"
                "【信息迷雾】只写玩家在场可感知的内容；未见过面的联系人不写外貌；"
                "NPC 只能说他有途径知道的事。"
                "【关系渐进且不对称】好感与信任一次只小幅变化，且必须挂具体事件；"
                "被伤害会记仇，帮过的人未必报恩。"
                "【意图不审查、后果真实】不拦截灰色或高风险意图，"
                "但给出真实的社会、法律与经济后果。"
                "【NPC 一致性】NPC 记住自己说过的话并兑现；不在场时也在过自己的生活，"
                "再见面时世界已变化。"
                "【结尾】每场结尾留一个具体、可被行动回应的处境；"
                "不总结、不灌鸡汤、不替玩家感慨。"
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
