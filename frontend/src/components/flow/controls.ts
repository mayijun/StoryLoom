/**
 * Flow 控制配置
 *
 * 控制不是独立的后端模块，而是 Flow 图上的节点 / 连线参数：
 * 调整灵敏度、采样次数、质量闸门，本质上就是在修改 Flow。
 * 本文件承接原 src/storyloom/control/ 的灵敏度画像与闸门策略。
 */

export type SensitivityTier = 'critical' | 'high' | 'medium' | 'low'

export type ControlDecision =
  | 'pass'
  | 'feedback_loop'
  | 'multi_sample'
  | 'human_review'
  | 'reject_retry'

export interface AgentControlProfile {
  agentRole: string
  sensitivity: SensitivityTier
  errorPropagationTo: string[]
  recommendedControls: string[]
  nSamples: number
  needsFeedbackLoop: boolean
  needsHumanReview: boolean
}

export const AGENT_CONTROL_PROFILES: Record<string, AgentControlProfile> = {
  director: {
    agentRole: 'director',
    sensitivity: 'critical',
    errorPropagationTo: ['所有角色Agent', '伏笔状态', '意外事件', '最终正文'],
    recommendedControls: ['反馈闭环(3轮)', '多次采样取最佳', '一致性Agent后置校验'],
    nSamples: 2,
    needsFeedbackLoop: true,
    needsHumanReview: false,
  },
  protagonist: {
    agentRole: 'protagonist',
    sensitivity: 'high',
    errorPropagationTo: ['情节走向', '其他角色反应', '正文'],
    recommendedControls: ['反馈闭环(2轮)', '人设一致性校验'],
    nSamples: 1,
    needsFeedbackLoop: true,
    needsHumanReview: false,
  },
  surprise: {
    agentRole: 'surprise',
    sensitivity: 'high',
    errorPropagationTo: ['情节走向', '伏笔状态', '读者体验'],
    recommendedControls: ['导演审批', '一致性Agent校验', '多次采样供导演选择'],
    nSamples: 3,
    needsFeedbackLoop: false,
    needsHumanReview: false,
  },
  foreshadowing: {
    agentRole: 'foreshadowing',
    sensitivity: 'high',
    errorPropagationTo: ['长期情节一致性', '回收质量'],
    recommendedControls: ['显式状态机约束', '一致性Agent校验'],
    nSamples: 1,
    needsFeedbackLoop: true,
    needsHumanReview: false,
  },
  ensemble: {
    agentRole: 'ensemble',
    sensitivity: 'low',
    errorPropagationTo: ['当前场景氛围'],
    recommendedControls: ['基本格式校验即可'],
    nSamples: 1,
    needsFeedbackLoop: false,
    needsHumanReview: false,
  },
  consistency: {
    agentRole: 'consistency',
    sensitivity: 'critical',
    errorPropagationTo: ['漏报冲突→永久性设定矛盾', '误报冲突→浪费重试资源'],
    recommendedControls: ['使用结构化输出最稳定的模型', '多次采样投票决定是否真有冲突'],
    nSamples: 2,
    needsFeedbackLoop: false,
    needsHumanReview: false,
  },
  prose: {
    agentRole: 'prose',
    sensitivity: 'medium',
    errorPropagationTo: ['读者体验', '文风一致性'],
    recommendedControls: ['反馈闭环(2轮)'],
    nSamples: 1,
    needsFeedbackLoop: true,
    needsHumanReview: false,
  },
}

export function getControlProfile(agentRole: string): AgentControlProfile {
  return (
    AGENT_CONTROL_PROFILES[agentRole] ?? {
      agentRole,
      sensitivity: 'medium',
      errorPropagationTo: ['未知'],
      recommendedControls: ['默认单次生成'],
      nSamples: 1,
      needsFeedbackLoop: false,
      needsHumanReview: false,
    }
  )
}

export function decideControlStrategy(
  agentRole: string,
  autoMode = true,
): ControlDecision {
  const profile = getControlProfile(agentRole)

  if (profile.sensitivity === 'critical') {
    return profile.nSamples > 1 ? 'multi_sample' : 'feedback_loop'
  }
  if (profile.sensitivity === 'high') {
    return profile.needsFeedbackLoop ? 'feedback_loop' : 'multi_sample'
  }
  if (profile.needsHumanReview && !autoMode) {
    return 'human_review'
  }
  return 'pass'
}

export function passQualityGate(confidence: number, threshold = 0.5): boolean {
  return confidence >= threshold
}

export interface ControlNodeData {
  kind: 'control'
  role: string
  sensitivity: SensitivityTier
  decision: ControlDecision
  nSamples: number
  threshold: number
  autoMode: boolean
}

export function buildControlNodeData(
  agentRole: string,
  autoMode = true,
  threshold = 0.5,
): ControlNodeData {
  const profile = getControlProfile(agentRole)
  return {
    kind: 'control',
    role: agentRole,
    sensitivity: profile.sensitivity,
    decision: decideControlStrategy(agentRole, autoMode),
    nSamples: profile.nSamples,
    threshold,
    autoMode,
  }
}
