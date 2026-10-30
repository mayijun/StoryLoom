// ============================================================
// Task 配置（与后端数据库 task_configs 表一致）
// ============================================================

export interface TaskConfig {
  key: string
  crew: string
  description: string
  expected_output: string
  agent_key?: string | null
  context_keys: string[]
  enabled: boolean
  position: number
}

export interface TaskConfigInput {
  key: string
  description: string
  expected_output: string
  agent_key?: string | null
  context_keys?: string[]
  enabled?: boolean
  position?: number
}
