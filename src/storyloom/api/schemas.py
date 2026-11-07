"""
API数据模型：前后端通信的数据契约
所有模型都设计为与 Vue Flow 的节点/边格式兼容，
方便未来直接接入拖曳式编辑器
"""

from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
import uuid


# ================================================================
# Agent 相关（字段对齐数据库 agent_configs 表 / CrewAI agent 配置）
# ================================================================

_KEY_PATTERN = r"^[a-z][a-z0-9_]*$"


class AgentConfigInput(BaseModel):
    """创建 Agent"""
    model_config = ConfigDict(extra="forbid")

    key: str = Field(
        ..., min_length=1, max_length=64, pattern=_KEY_PATTERN
    )
    role: str = Field(..., min_length=1)
    goal: str = Field(..., min_length=1)
    backstory: str = Field(..., min_length=1)

    allow_delegation: Optional[bool] = None
    verbose: Optional[bool] = None
    max_iter: Optional[int] = None
    settings: Dict[str, Any] = Field(default_factory=dict)

    enabled: bool = True
    position: Optional[int] = None


class AgentConfigUpdate(BaseModel):
    """部分更新 Agent（key 不可修改，请用删除+新建重命名）"""
    model_config = ConfigDict(extra="forbid")

    role: Optional[str] = Field(None, min_length=1)
    goal: Optional[str] = Field(None, min_length=1)
    backstory: Optional[str] = Field(None, min_length=1)

    allow_delegation: Optional[bool] = None
    verbose: Optional[bool] = None
    max_iter: Optional[int] = None
    settings: Optional[Dict[str, Any]] = None

    enabled: Optional[bool] = None
    position: Optional[int] = None


class AgentConfigView(BaseModel):
    """Agent 配置（直接对应数据库记录）"""
    key: str
    project_id: str
    crew: str
    role: str
    goal: str
    backstory: str
    allow_delegation: Optional[bool] = None
    verbose: Optional[bool] = None
    max_iter: Optional[int] = None
    settings: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool
    position: int


class AgentListResponse(BaseModel):
    agents: List[AgentConfigView]
    available_models: List[str]


# ================================================================
# Task 相关（字段对齐数据库 task_configs 表 / CrewAI task 配置）
# ================================================================

class TaskConfigInput(BaseModel):
    """创建 Task"""
    model_config = ConfigDict(extra="forbid")

    key: str = Field(
        ..., min_length=1, max_length=64, pattern=_KEY_PATTERN
    )
    description: str = Field(..., min_length=1)
    expected_output: str = Field(..., min_length=1)

    agent_key: Optional[str] = None
    context_keys: List[str] = Field(default_factory=list)

    enabled: bool = True
    position: Optional[int] = None


class TaskConfigUpdate(BaseModel):
    """部分更新 Task（key 不可修改）"""
    model_config = ConfigDict(extra="forbid")

    description: Optional[str] = Field(None, min_length=1)
    expected_output: Optional[str] = Field(None, min_length=1)

    agent_key: Optional[str] = None
    context_keys: Optional[List[str]] = None

    enabled: Optional[bool] = None
    position: Optional[int] = None


class TaskConfigView(BaseModel):
    """Task 配置（直接对应数据库记录）"""
    key: str
    project_id: str
    crew: str
    description: str
    expected_output: str
    agent_key: Optional[str] = None
    context_keys: List[str] = Field(default_factory=list)
    enabled: bool
    position: int


class TaskListResponse(BaseModel):
    tasks: List[TaskConfigView]


# ================================================================
# Asset 相关
# ================================================================

class CharacterCreate(BaseModel):
    name: str
    importance_tier: Literal["primary", "secondary", "background"]
    persona: str
    motivation: str
    secrets: str = ""
    # 预留：视觉资产
    portrait_url: Optional[str] = None
    voice_id: Optional[str] = None


class LocationCreate(BaseModel):
    name: str
    description: str
    # 预留：视觉资产
    background_url: Optional[str] = None


class ForeshadowingView(BaseModel):
    foreshadow_id: str
    description: str
    status: str
    planted_in_scene: str
    target_revelation: str
    reinforcement_count: int
    scenes_since_last_mention: int
    max_dormant_scenes: int
    linked_characters: List[str]


class ForeshadowTransition(BaseModel):
    """伏笔状态显式流转请求

    action 与状态机对应：
    - reinforce: planted/reinforced → reinforced（强化计数 +1，沉睡清零）
    - activate:  planted/reinforced → activated
    - resolve:   activated → resolved
    - subvert:   planted/reinforced/activated → subverted
    - abandon:   planted/reinforced/activated → abandoned
    - replant:   resolved/subverted/abandoned → planted（计数重置）
    """
    model_config = ConfigDict(extra="forbid")

    action: Literal[
        "reinforce", "activate", "resolve", "subvert", "abandon", "replant"
    ]


# ================================================================
# Project 相关
# ================================================================

class ProjectCreate(BaseModel):
    title: str
    style: str
    description: str = ""


class ProjectView(BaseModel):
    project_id: str
    title: str
    style: str
    description: str
    scene_count: int
    character_count: int
    foreshadowing_count: int


class ProjectListResponse(BaseModel):
    projects: List[ProjectView]
    current_project_id: Optional[str]


# ================================================================
# 项目指标（成本与质量）
# ================================================================

class SceneMetric(BaseModel):
    scene_id: str
    chapter_id: Optional[str] = None
    quality_score: Optional[float] = None
    duration_ms: Optional[int] = None
    created_at: Optional[str] = None


class ProjectMetrics(BaseModel):
    project_id: str
    scene_count: int
    avg_quality_score: Optional[float] = None
    total_duration_ms: int = 0
    avg_duration_ms: Optional[float] = None
    model_calls: Dict[str, int] = Field(default_factory=dict)
    agent_calls: Dict[str, int] = Field(default_factory=dict)
    scenes: List[SceneMetric] = Field(default_factory=list)


# ================================================================
# Agent / Task 配置导入导出
# ================================================================

class ConfigExport(BaseModel):
    """项目 Agent / Task 配置的可移植快照"""
    version: int = 1
    project_id: str
    agents: List[Dict[str, Any]] = Field(default_factory=list)
    tasks: List[Dict[str, Any]] = Field(default_factory=list)


class ConfigImport(BaseModel):
    """导入配置；mode=merge 逐条 upsert，overwrite 先清空再写入"""
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    agents: List[Dict[str, Any]] = Field(default_factory=list)
    tasks: List[Dict[str, Any]] = Field(default_factory=list)
    mode: Literal["merge", "overwrite"] = "merge"


class ConfigCopyRequest(BaseModel):
    """从同库另一个项目复制配置"""
    model_config = ConfigDict(extra="forbid")

    source_project_id: str
    mode: Literal["merge", "overwrite"] = "overwrite"


# ================================================================
# 生成相关
# ================================================================

class GenerateSceneRequest(BaseModel):
    project_id: str
    scene_brief: str
    present_character_names: List[str]
    render_mode: str = "text_only"
    # 可选：生成后归属到指定章节（需先创建章节）
    chapter_id: Optional[str] = None
    # 预留：自定义Agent编排（未来Flow编辑器输出）
    custom_flow: Optional[Dict[str, Any]] = None


class GenerationStepUpdate(BaseModel):
    """生成过程中的实时步骤更新（通过SSE/WebSocket推送）"""
    step: str
    status: Literal["running", "completed", "failed", "skipped"]
    agent_name: str
    agent_type: str
    model_used: str
    content: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class GenerateSceneResponse(BaseModel):
    scene_id: str
    final_prose: str
    steps: List[GenerationStepUpdate]
    foreshadowing_updates: List[ForeshadowingView]
    # 预留：多模态输出
    render_outputs: Dict[str, Any] = Field(default_factory=dict)


# ================================================================
# 场景持久化
# ================================================================

class SceneView(BaseModel):
    scene_id: str
    project_id: str
    chapter_id: Optional[str] = None
    brief: str
    present_characters: List[str] = Field(default_factory=list)
    prose: str
    quality_score: Optional[float] = None
    duration_ms: Optional[int] = None
    model_usage: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None


class SceneUpdate(BaseModel):
    """编辑已落库场景（仅 prose / brief 等可变字段）"""
    model_config = ConfigDict(extra="forbid")

    brief: Optional[str] = None
    present_characters: Optional[List[str]] = None
    prose: Optional[str] = None
    quality_score: Optional[float] = None
    duration_ms: Optional[int] = None
    model_usage: Optional[Dict[str, Any]] = None


# ================================================================
# 章节结构
# ================================================================

class ChapterCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    outline: str = ""
    position: Optional[int] = None
    status: str = "draft"


class ChapterUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = None
    outline: Optional[str] = None
    position: Optional[int] = None
    status: Optional[str] = None


class ChapterView(BaseModel):
    chapter_id: str
    project_id: str
    title: str
    outline: str
    position: int
    status: str


class SceneAssignChapter(BaseModel):
    """把场景归属到章节；chapter_id 为 null 时解除归属"""
    model_config = ConfigDict(extra="forbid")

    chapter_id: Optional[str] = None


# ================================================================
# ★ Flow 编辑器预留：节点/边数据结构
# 设计为与 Vue Flow 的数据格式完全兼容
# 参考：https://vueflow.dev/
# ================================================================

class FlowNode(BaseModel):
    """
    Vue Flow 兼容的节点定义
    
    搜索结果确认 Vue Flow 支持：
    - 自定义节点（AgentNode、AssetNode、ProcessNode）
    - 拖拽、缩放、多选
    - 嵌套节点
    
    参考 LuckyFlow 项目和 vue3-workFlow 项目的节点模型
    """
    id: str
    type: str                                    # "agent" / "asset" / "process"
    position: Dict[str, float]                   # {"x": 100, "y": 200}
    data: Dict[str, Any]                         # 节点内部数据
    # 以下字段与 Vue Flow 格式对齐
    label: Optional[str] = None
    source_position: str = "right"               # "top" / "right" / "bottom" / "left"
    target_position: str = "left"


class FlowEdge(BaseModel):
    """Vue Flow 兼容的边（连线）定义"""
    id: str
    source: str                                  # 源节点ID
    target: str                                  # 目标节点ID
    source_handle: Optional[str] = None
    target_handle: Optional[str] = None
    type: str = "default"                        # "default" / "data_flow" / "control_flow"
    label: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)


class FlowDefinition(BaseModel):
    """
    完整的工作流定义
    前端 Flow 编辑器保存/加载的数据格式
    后端根据此定义动态编排 Agent
    """
    flow_id: str = Field(default_factory=lambda: f"flow_{uuid.uuid4().hex[:8]}")
    name: str = "Default Scene Flow"
    nodes: List[FlowNode] = Field(default_factory=list)
    edges: List[FlowEdge] = Field(default_factory=list)
    # 元信息
    viewport: Dict[str, float] = Field(
        default_factory=lambda: {"x": 0, "y": 0, "zoom": 1}
    )


# ================================================================
# 双模式运行时（M0）
# ================================================================

class TurnRequest(BaseModel):
    """游戏 / 导演模式的一次回合请求"""

    instance_id: str = "default"
    actor: str = "玩家"
    mode: Literal["game", "director"] = "game"
    text: str = ""
    intent: Optional[Dict[str, Any]] = None
    world_state: Optional[Dict[str, Any]] = None

    max_turns: int = 1
    max_retries: int = 1
    max_cost: float = 1.0
    max_duration_ms: int = 30000

    enabled_extensions: Optional[List[str]] = None
    memory_backend: Optional[Literal["fts", "vector", "hybrid"]] = None
    idle_turns: int = 0
    switch_mode_to: Optional[Literal["game", "director"]] = None
    overrides: List[Dict[str, Any]] = Field(default_factory=list)
    goal: str = ""
    # 仅在本次运行时内存中生效，不回显、不落盘
    provider_api_keys: Dict[str, str] = Field(default_factory=dict, exclude=True)


class SaveCreateRequest(BaseModel):
    instance_id: str = "default"
    label: str = ""


class ModeSwitchRequest(BaseModel):
    instance_id: str = "default"
    mode: Literal["game", "director"]


class MemoryPatchRequest(BaseModel):
    backend: Literal["fts", "vector", "hybrid"]


class ExtensionResolveRequest(BaseModel):
    instance_id: str = "default"
    enabled: Optional[List[str]] = None


# ---------------- 试用模板 ----------------

class TemplateView(BaseModel):
    template_id: str
    title: str
    style: str
    description: str = ""


class TemplateListResponse(BaseModel):
    templates: List[TemplateView]


class TemplateApplyRequest(BaseModel):
    title: Optional[str] = None  # 不传则使用模板默认标题
