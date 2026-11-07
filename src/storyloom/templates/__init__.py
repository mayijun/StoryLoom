"""
试用模板（Trial Templates）。

模板是一个自包含的小说项目骨架：角色、地点、伏笔、章节大纲，
以及配套的扩展（地图 mod / 文风 skill）。

与 ``db/`` 实现解耦：模板只声明数据，落库与扩展注册由 :func:`apply_template`
统一完成。用户在 Web 界面上选择「试用模板」即可一键生成一个可删除的普通项目，
试用结束后直接删除项目即可清理，不再残留固定文本文件。

扩展（map / skill）以 Python 字典内嵌在模板模块里，不再以独立 YAML 存放在
``examples/`` 下；:class:`storyloom.extensions.host.ExtensionRegistry` 会在
启动时从这里读取并注册。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from storyloom.extensions.manifest import ExtensionManifest, validate_manifest


@dataclass
class Template:
    """一个试用模板的完整声明。"""

    template_id: str
    title: str
    style: str
    description: str = ""
    characters: List[Dict[str, str]] = field(default_factory=list)
    locations: List[Dict[str, str]] = field(default_factory=list)
    foreshadowings: List[Dict[str, Any]] = field(default_factory=list)
    chapters: List[Dict[str, str]] = field(default_factory=list)
    # 扩展 manifest 原始字典（kind / contributes / ...），由 apply 时校验
    extensions: List[Dict[str, Any]] = field(default_factory=list)

    def extension_manifests(self) -> List[ExtensionManifest]:
        """把内嵌的扩展字典校验成 :class:`ExtensionManifest`。"""
        return [validate_manifest(dict(ext)) for ext in self.extensions]


# ---------------- 模板注册表 ----------------

TEMPLATES: Dict[str, Template] = {}


def register(template: Template) -> Template:
    TEMPLATES[template.template_id] = template
    return template


def get_template(template_id: str) -> Optional[Template]:
    return TEMPLATES.get(template_id)


def list_templates() -> List[Dict[str, str]]:
    """返回模板摘要（供 Web 列表展示）。"""
    return [
        {
            "template_id": t.template_id,
            "title": t.title,
            "style": t.style,
            "description": t.description,
        }
        for t in TEMPLATES.values()
    ]


def apply_template(
    template_id: str,
    project_id: str,
    repo: Any,
    *,
    title: Optional[str] = None,
    extension_registry: Any = None,
) -> bool:
    """把模板应用到一个新项目。

    - 创建项目（若不存在）；
    - 写入角色 / 地点 / 伏笔 / 章节；
    - 把模板内嵌的扩展注册到 ``extension_registry``（若提供）。

    返回 ``True`` 表示本次写入了内容；若该项目已有角色则跳过写入，
    返回 ``False``（避免覆盖用户在试用中的修改）。
    """
    template = get_template(template_id)
    if template is None:
        raise ValueError(f"模板不存在: {template_id}")

    repo.create_all()

    if repo.get_project(project_id) is None:
        repo.create_project(
            project_id,
            title or template.title,
            template.style,
            template.description,
        )
    else:
        repo.ensure_seeded(project_id)

    def _sync_stats() -> None:
        repo.update_project_stats(
            project_id,
            character_count=len(repo.list_characters(project_id)),
            foreshadowing_count=len(repo.list_foreshadowings(project_id)),
        )

    if repo.list_characters(project_id):
        _sync_stats()
        return False

    for character in template.characters:
        repo.upsert_character(project_id, **character)

    for location in template.locations:
        repo.upsert_location(project_id, **location)

    for foreshadowing in template.foreshadowings:
        repo.upsert_foreshadowing(project_id, **foreshadowing)

    if not repo.list_chapters(project_id):
        for position, chapter in enumerate(template.chapters):
            repo.create_chapter(
                project_id=project_id,
                position=position,
                status="draft",
                **chapter,
            )

    _sync_stats()

    # 模板内嵌扩展已由 ExtensionRegistry 在首次 manifests() 时全局注册，
    # 此处无需重复 add（避免重复 manifest）。保留参数供未来按需注册使用。
    return True


# 注册内置模板（导入即注册，便于扩展注册表与 API 直接取用）
from storyloom.templates import xianxia_system  # noqa: E402,F401

__all__ = [
    "Template",
    "TEMPLATES",
    "apply_template",
    "get_template",
    "list_templates",
    "register",
]
