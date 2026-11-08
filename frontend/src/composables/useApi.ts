/**
 * API调用封装
 */

import axios from 'axios'
import type { ProjectView, ProjectCreate, TemplateView } from '@/types/project'
import type { CharacterAsset, LocationAsset, Foreshadowing } from '@/types/asset'
import type { AgentConfig, AgentConfigInput } from '@/types/agent'
import type { TaskConfig, TaskConfigInput } from '@/types/task'

const api = axios.create({
  baseURL: '/api',
  timeout: 300000, // 生成场景可能需要较长时间
})

// 双模式运行时的稳定入口，后端前缀为 /runtime/v1（见 routers/runtime_v1.py）
const runtime = axios.create({
  baseURL: '/runtime/v1',
  timeout: 300000,
})

export function useApi() {

  // ---- Projects ----
  const listProjects = () => api.get<{ projects: ProjectView[] }>('/projects/')
  const createProject = (data: ProjectCreate) => api.post<ProjectView>('/projects/', data)
  const getProject = (id: string) => api.get(`/projects/${id}`)

  // ---- Templates (试用模板) ----
  const listTemplates = () => api.get<{ templates: TemplateView[] }>('/templates/')
  const applyTemplate = (templateId: string, title?: string) =>
    api.post<ProjectView>(`/templates/${templateId}/apply`, { title })

  // ---- Assets ----
  const listCharacters = (pid: string) => api.get<CharacterAsset[]>(`/projects/${pid}/assets/characters`)
  const addCharacter = (pid: string, data: any) => api.post(`/projects/${pid}/assets/characters`, data)
  const deleteCharacter = (pid: string, name: string) => api.delete(`/projects/${pid}/assets/characters/${name}`)
  const listLocations = (pid: string) => api.get<LocationAsset[]>(`/projects/${pid}/assets/locations`)
  const addLocation = (pid: string, data: any) => api.post(`/projects/${pid}/assets/locations`, data)
  const listForeshadowings = (pid: string) => api.get<Foreshadowing[]>(`/projects/${pid}/assets/foreshadowings`)
  const addForeshadowing = (pid: string, data: any) => api.post(`/projects/${pid}/assets/foreshadowings`, data)
  const transitionForeshadowing = (pid: string, fid: string, action: string) =>
    api.post<Foreshadowing>(`/projects/${pid}/assets/foreshadowings/${fid}/transition`, { action })

  // ---- 导出 / 指标 ----
  const exportNovelUrl = (pid: string, format: 'md' | 'txt') =>
    `/api/projects/${pid}/export?format=${format}`
  const getMetrics = (pid: string) => api.get(`/projects/${pid}/metrics`)

  // ---- 配置导入导出 / 跨项目复制 ----
  const exportConfig = (pid: string) => api.get(`/projects/${pid}/config/export`)
  const importConfig = (pid: string, data: any) => api.post(`/projects/${pid}/config/import`, data)
  const copyConfigFrom = (pid: string, sourcePid: string, mode: 'merge' | 'overwrite' = 'overwrite') =>
    api.post(`/projects/${pid}/config/copy_from`, { source_project_id: sourcePid, mode })

  // ---- Agents ----
  // Agent / Task 从属于小说项目，通过 project_id 查询参数隔离
  const listAgents = (projectId?: string) =>
    api.get<{ agents: AgentConfig[]; available_models: string[] }>('/agents/', {
      params: projectId ? { project_id: projectId } : undefined,
    })
  const createAgent = (data: AgentConfigInput, projectId?: string) =>
    api.post<AgentConfig>('/agents/', data, {
      params: projectId ? { project_id: projectId } : undefined,
    })
  const updateAgent = (key: string, data: Partial<AgentConfigInput>, projectId?: string) =>
    api.put<AgentConfig>(`/agents/${key}`, data, {
      params: projectId ? { project_id: projectId } : undefined,
    })
  const deleteAgent = (key: string, projectId?: string) =>
    api.delete(`/agents/${key}`, {
      params: projectId ? { project_id: projectId } : undefined,
    })
  const getAgentTypes = () => api.get('/agents/types')

  // ---- Tasks ----
  const listTasks = (projectId?: string) =>
    api.get<{ tasks: TaskConfig[] }>('/tasks/', {
      params: projectId ? { project_id: projectId } : undefined,
    })
  const createTask = (data: TaskConfigInput, projectId?: string) =>
    api.post<TaskConfig>('/tasks/', data, {
      params: projectId ? { project_id: projectId } : undefined,
    })
  const updateTask = (key: string, data: Partial<TaskConfigInput>, projectId?: string) =>
    api.put<TaskConfig>(`/tasks/${key}`, data, {
      params: projectId ? { project_id: projectId } : undefined,
    })
  const deleteTask = (key: string, projectId?: string) =>
    api.delete(`/tasks/${key}`, {
      params: projectId ? { project_id: projectId } : undefined,
    })

  // ---- Generation ----
  const generateScene = (data: any) => api.post('/generate/scene', data)

  // ---- 双模式运行时（M0） ----
  const playTurn = (pid: string, data: any) => runtime.post(`/${pid}/turn`, data)
  const getGameState = (pid: string, instanceId = 'ui') =>
    runtime.get(`/${pid}/state`, { params: { instance_id: instanceId } })
  const createGameSave = (pid: string, data: any) => runtime.post(`/${pid}/saves`, data)
  const listGameSaves = (pid: string) => runtime.get(`/${pid}/saves`)
  const loadGameSave = (pid: string, saveId: string, instanceId = 'ui') =>
    runtime.post(`/${pid}/saves/${saveId}/load`, null, {
      params: { instance_id: instanceId },
    })
  const switchGameMode = (pid: string, mode: 'game' | 'director', instanceId = 'ui') =>
    runtime.post(`/${pid}/mode`, { mode, instance_id: instanceId })
  const getMemory = (pid: string) => api.get(`/projects/${pid}/memory`)
  const patchMemory = (pid: string, backend: string) =>
    api.patch(`/projects/${pid}/memory`, { backend })
  const resolveExtensions = (instanceId = 'ui') =>
    runtime.post('/extensions/resolve', { instance_id: instanceId })

  // ---- SSE流式生成 ----
  const generateSceneStream = (data: any, onMessage: (event: any) => void) => {
    const eventSource = new EventSource('/api/generate/scene/stream?' + new URLSearchParams({
      // SSE不支持POST body，这里用简化方案
      // 生产环境建议用WebSocket
    }))
    // 实际实现中用fetch + ReadableStream
    return fetch('/api/generate/scene/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(response => {
      const reader = response.body?.getReader()
      const decoder = new TextDecoder()

      function read() {
        reader?.read().then(({ done, value }) => {
          if (done) return
          const text = decoder.decode(value)
          const lines = text.split('\n')
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6))
                onMessage(data)
              } catch {}
            }
          }
          read()
        })
      }
      read()
    })
  }

  // ---- Health ----
  const checkHealth = () => api.get('/health')

  return {
    listProjects, createProject, getProject,
    listTemplates, applyTemplate,
    listCharacters, addCharacter, deleteCharacter,
    listLocations, addLocation,
    listForeshadowings, addForeshadowing, transitionForeshadowing,
    exportNovelUrl, getMetrics,
    exportConfig, importConfig, copyConfigFrom,
    listAgents, createAgent, updateAgent, deleteAgent, getAgentTypes,
    listTasks, createTask, updateTask, deleteTask,
    generateScene, generateSceneStream,
    playTurn, getGameState, createGameSave, listGameSaves, loadGameSave,
    switchGameMode, getMemory, patchMemory, resolveExtensions,
    checkHealth,
  }
}
