/**
 * Agent 类型定义
 * 
 * 设计原则：
 * 1. 所有Agent共享同一个基础接口（BaseAgent）
 * 2. 文本类Agent已完整实现
 * 3. 视觉/音频/游戏类Agent只定义interface，不实现逻辑
 * 4. 位置信息兼容Vue Flow节点格式，预留拖曳编辑
 * 
 * 参考搜索结果：
 * - Vue Flow 节点数据格式：{ id, type, position: {x, y}, data }
 * - LuckyFlow 项目：Agent节点可拖拽编排
 */

// ============================================================
// Agent 类型枚举
// ============================================================

export type TextAgentType =
  | 'protagonist'
  | 'ensemble'
  | 'director'
  | 'surprise'
  | 'foreshadowing'
  | 'consistency'
  | 'prose'
  | 'structuring'
  | 'outline'

export type ReservedAgentType =
  | 'visual'
  | 'audio'
  | 'game_logic'
  | 'custom'

export type AgentType = TextAgentType | ReservedAgentType

export type AgentStatus = 'idle' | 'thinking' | 'completed' | 'error'

// ============================================================
// Agent 配置（与后端数据库 agent_configs 表一致）
// ============================================================

export interface AgentConfig {
  key: string
  crew: string
  role: string
  goal: string
  backstory: string
  allow_delegation?: boolean | null
  verbose?: boolean | null
  max_iter?: number | null
  settings: Record<string, any>
  enabled: boolean
  position: number
}

export interface AgentConfigInput {
  key: string
  role: string
  goal: string
  backstory: string
  allow_delegation?: boolean | null
  verbose?: boolean | null
  max_iter?: number | null
  settings?: Record<string, any>
  enabled?: boolean
  position?: number
}

// ============================================================
// Agent 运行时状态
// ============================================================

export interface AgentRuntimeState {
  agent_id: string
  status: AgentStatus
  current_output: string
  model_used: string
  tokens_used: number
  cost_usd: number
}

// ============================================================
// Agent 消息（场景生成过程中的输出）
// ============================================================

export interface AgentMessage {
  message_id: string
  agent_id: string
  agent_type: AgentType
  agent_name: string
  content: string
  timestamp: number
  // 消息类型
  message_type: 'thought' | 'dialogue' | 'action' | 'system' | 'error'
  // 预留：多模态附件
  attachments?: MessageAttachment[]
}

export interface MessageAttachment {
  type: 'image' | 'audio' | 'video' | 'file'
  url: string
  metadata?: Record<string, any>
}

// ============================================================
// Agent 类型元信息（用于UI展示）
// ============================================================

export const AGENT_TYPE_META: Record<AgentType, {
  label: string
  icon: string
  color: string
  description: string
  implemented: boolean
}> = {
  protagonist:    { label: '主角Agent',      icon: '🎭', color: '#e74c3c', description: '1角色=1实例，独立人格', implemented: true },
  ensemble:       { label: '群演Agent',      icon: '👥', color: '#e67e22', description: '1实例承载多个次要角色', implemented: true },
  director:       { label: '导演Agent',      icon: '🎬', color: '#3498db', description: '场景意图包，间接引导', implemented: true },
  surprise:       { label: '意外Agent',      icon: '🎲', color: '#9b59b6', description: '合理的意外事件提案', implemented: true },
  foreshadowing:  { label: '伏笔Agent',      icon: '📌', color: '#1abc9c', description: '伏笔生命周期管理', implemented: true },
  consistency:    { label: '一致性检测Agent', icon: '✅', color: '#2ecc71', description: '校验人设/时间线冲突', implemented: true },
  prose:          { label: '润色Agent',      icon: '✍️', color: '#f39c12', description: '文学化叙事正文', implemented: true },
  structuring:    { label: '结构化Agent',    icon: '🔧', color: '#95a5a6', description: '正文→SceneIR', implemented: true },
  outline:        { label: '大纲Agent',      icon: '📋', color: '#34495e', description: '章节级结构规划', implemented: true },
  // 预留类型
  visual:         { label: '视觉Agent',      icon: '🖼️', color: '#bdc3c7', description: '图片/漫画生成（预留）', implemented: false },
  audio:          { label: '音频Agent',      icon: '🔊', color: '#bdc3c7', description: '语音/音效生成（预留）', implemented: false },
  game_logic:     { label: '游戏逻辑Agent',  icon: '🎮', color: '#bdc3c7', description: '交互游戏逻辑（预留）', implemented: false },
  custom:         { label: '自定义Agent',    icon: '⚙️', color: '#bdc3c7', description: '用户自定义（预留）', implemented: false },
}
