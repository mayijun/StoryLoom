/**
 * 多模态类型定义（预留）
 */

export interface RenderOutput {
  modality: 'text' | 'image' | 'audio' | 'video' | 'composite'
  success: boolean
  output_paths: string[]
  error_message?: string
  metadata: Record<string, any>
}

// 预留接口：未来可扩展
export interface ImageRenderConfig {
  workflow: string
  width: number
  height: number
  steps: number
}

export interface AudioRenderConfig {
  provider: string
  voice_mapping: Record<string, string>
}

export interface VideoRenderConfig {
  provider: string
  duration: number
  resolution: string
}
