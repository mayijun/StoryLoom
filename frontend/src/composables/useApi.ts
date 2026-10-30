/**
 * API调用封装
 */

import axios from 'axios'
import type { ProjectView, ProjectCreate } from '@/types/project'
import type { CharacterAsset, LocationAsset, Foreshadowing } from '@/types/asset'
import type { AgentConfig, AgentConfigInput } from '@/types/agent'

const api = axios.create({
  baseURL: '/api',
  timeout: 300000, // 生成场景可能需要较长时间
})

export function useApi() {

  // ---- Projects ----
  const listProjects = () => api.get<{ projects: ProjectView[] }>('/projects/')
  const createProject = (data: ProjectCreate) => api.post<ProjectView>('/projects/', data)
  const getProject = (id: string) => api.get(`/projects/${id}`)

  // ---- Assets ----
  const listCharacters = (pid: string) => api.get<CharacterAsset[]>(`/projects/${pid}/assets/characters`)
  const addCharacter = (pid: string, data: any) => api.post(`/projects/${pid}/assets/characters`, data)
  const deleteCharacter = (pid: string, name: string) => api.delete(`/projects/${pid}/assets/characters/${name}`)
  const listLocations = (pid: string) => api.get<LocationAsset[]>(`/projects/${pid}/assets/locations`)
  const addLocation = (pid: string, data: any) => api.post(`/projects/${pid}/assets/locations`, data)
  const listForeshadowings = (pid: string) => api.get<Foreshadowing[]>(`/projects/${pid}/assets/foreshadowings`)
  const addForeshadowing = (pid: string, data: any) => api.post(`/projects/${pid}/assets/foreshadowings`, data)

  // ---- Agents ----
  const listAgents = () => api.get<{ agents: AgentConfig[]; available_models: string[] }>('/agents/')
  const createAgent = (data: AgentConfigInput) => api.post<AgentConfig>('/agents/', data)
  const updateAgent = (key: string, data: Partial<AgentConfigInput>) => api.put<AgentConfig>(`/agents/${key}`, data)
  const deleteAgent = (key: string) => api.delete(`/agents/${key}`)
  const getAgentTypes = () => api.get('/agents/types')

  // ---- Generation ----
  const generateScene = (data: any) => api.post('/generate/scene', data)

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
    listCharacters, addCharacter, deleteCharacter,
    listLocations, addLocation,
    listForeshadowings, addForeshadowing,
    listAgents, createAgent, updateAgent, deleteAgent, getAgentTypes,
    generateScene, generateSceneStream,
    checkHealth,
  }
}
