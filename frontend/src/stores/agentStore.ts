import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { AgentConfig, AgentConfigInput, AgentMessage, AgentRuntimeState } from '@/types/agent'
import { useApi } from '@/composables/useApi'

export const useAgentStore = defineStore('agent', () => {
  const api = useApi()
  const agents = ref<AgentConfig[]>([])
  const availableModels = ref<string[]>([])
  const runtimeStates = ref<Map<string, AgentRuntimeState>>(new Map())
  const messages = ref<AgentMessage[]>([])

  const enabledAgents = computed(() => agents.value.filter(a => a.enabled))

  async function fetchAgents() {
    const res = await api.listAgents()
    agents.value = res.data.agents
    availableModels.value = res.data.available_models
  }

  async function addAgent(agent: AgentConfigInput) {
    const res = await api.createAgent(agent)
    agents.value.push(res.data)
  }

  async function removeAgent(key: string) {
    await api.deleteAgent(key)
    agents.value = agents.value.filter(a => a.key !== key)
  }

  async function updateAgent(key: string, patch: Partial<AgentConfigInput>) {
    const res = await api.updateAgent(key, patch)
    const idx = agents.value.findIndex(a => a.key === key)
    if (idx >= 0) agents.value[idx] = res.data
  }

  function addMessage(msg: AgentMessage) {
    messages.value.push(msg)
  }

  function clearMessages() {
    messages.value = []
  }

  return {
    agents, availableModels, runtimeStates, messages, enabledAgents,
    fetchAgents, addAgent, removeAgent, updateAgent,
    addMessage, clearMessages,
  }
})
