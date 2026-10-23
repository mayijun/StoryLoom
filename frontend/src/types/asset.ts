/**
 * Asset 类型定义
 */

export type ImportanceTier = 'primary' | 'secondary' | 'background'

export interface CharacterAsset {
  name: string
  importance_tier: ImportanceTier
  persona: string
  motivation: string
  secrets: string
  // 预留
  portrait_url?: string
  voice_id?: string
}

export interface LocationAsset {
  name: string
  description: string
  background_url?: string
}

export type ForeshadowStatus =
  | 'planted' | 'reinforced' | 'activated'
  | 'resolved' | 'subverted' | 'abandoned'

export interface Foreshadowing {
  foreshadow_id: string
  description: string
  status: ForeshadowStatus
  planted_in_scene: string
  target_revelation: string
  reinforcement_count: number
  scenes_since_last_mention: number
  max_dormant_scenes: number
  linked_characters: string[]
}

export const FORESHADOW_STATUS_META: Record<ForeshadowStatus, {
  label: string; emoji: string; color: string
}> = {
  planted:    { label: '已种下', emoji: '🌱', color: '#27ae60' },
  reinforced: { label: '已强化', emoji: '💪', color: '#2980b9' },
  activated:  { label: '已触发', emoji: '🎯', color: '#e67e22' },
  resolved:   { label: '已回收', emoji: '✅', color: '#95a5a6' },
  subverted:  { label: '已颠覆', emoji: '🔄', color: '#8e44ad' },
  abandoned:  { label: '已废弃', emoji: '⚠️', color: '#e74c3c' },
}
