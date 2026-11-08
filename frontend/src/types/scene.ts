/**
 * 场景类型定义（对齐后端 SceneView / SceneUpdate）
 */

export interface SceneView {
  scene_id: string
  project_id: string
  chapter_id: string | null
  brief: string
  present_characters: string[]
  prose: string
  quality_score: number | null
  duration_ms: number | null
  model_usage: Record<string, any>
  created_at: string | null
}

export interface SceneUpdate {
  brief?: string
  present_characters?: string[]
  prose?: string
  quality_score?: number | null
}
