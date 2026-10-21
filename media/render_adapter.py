"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

多模态渲染适配器（预留接口层）

设计要点：ProseAgent 产出的正文先转成结构化中间表示
（speaker / dialogue / narration / emotion_tag / camera_hint），
未来接入 TTS、Seedance、图片生成时只需新增一个 Adapter 实现类，
不用改动前面任何 Agent 逻辑。

这是现在就必须做对的设计决策，因为补救成本最高。
"""

from abc import ABC, abstractmethod
from typing import List

from pydantic import BaseModel, Field


class SceneSegment(BaseModel):
    """单个叙事片段：一句台词或一段旁白"""

    speaker: str = ""
    dialogue: str = ""
    narration: str = ""
    emotion_tag: str = ""
    camera_hint: str = ""


class SceneRenderData(BaseModel):
    """结构化中间表示：所有渲染器的输入统一格式"""

    scene_id: str
    prose_text: str
    segments: List[SceneSegment] = Field(default_factory=list)


class RenderAdapter(ABC):
    """渲染适配器抽象基类"""

    @abstractmethod
    def render(self, data: SceneRenderData) -> str:
        """返回渲染结果的路径或 URL"""
        ...


class TextOnlyAdapter(RenderAdapter):
    """纯文本渲染（当前默认实现）"""

    def render(self, data: SceneRenderData) -> str:
        return data.prose_text


class TTSAdapter(RenderAdapter):
    """语音小说渲染（预留）"""

    def render(self, data: SceneRenderData) -> str:
        # TODO: 接入 Fish-TTS / CosyVoice 等
        raise NotImplementedError("TTS 渲染待实现")


class ImageAdapter(RenderAdapter):
    """插图渲染（预留）"""

    def render(self, data: SceneRenderData) -> str:
        # TODO: 接入 DALL-E / Midjourney API / Seedance
        raise NotImplementedError("图片渲染待实现")


class VideoAdapter(RenderAdapter):
    """短剧视频渲染（预留）"""

    def render(self, data: SceneRenderData) -> str:
        # TODO: 接入 Seedance / Kling 等视频生成模型
        raise NotImplementedError("视频渲染待实现")
