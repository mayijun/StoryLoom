/**
 * Project 类型定义
 */

export interface ProjectView {
  project_id: string
  title: string
  style: string
  description: string
  scene_count: number
  character_count: number
  foreshadowing_count: number
}

export interface ProjectCreate {
  title: string
  style: string
  description: string
}
