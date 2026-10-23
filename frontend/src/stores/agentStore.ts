import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { AgentDefinition, AgentMessage, AgentRuntimeState } from '@/types/agent'
import { useApi } from '@/composables/useApi'

export const useAgentStore = defineStore('agent', () => {
  const api = useApi()
  const agents = ref<AgentDefinition[]>([])
  const availableModels = ref<string[]>([])
  const runtimeStates = ref<Map<string, AgentRuntimeState>>(new Map())
  const messages = ref<AgentMessage[]>([])

  const enabledAgents = computed(() => agents.value.filter(a => a.enabled))

  async function fetchAgents() {
    const res = await api.listAgents()
    agents.value = res.data.agents
    availableModels.value = res.data.available_models
  }

  async function addAgent(agent: AgentDefinition) {
    const res = await api.createAgent(agent)
    agents.value.push(res.data)
  }

  async function removeAgent(id: string) {
    await api.deleteAgent(id)
    agents.value = agents.value.filter(a => a.agent_id !== id)
  }

  async function updateAgent(agent: AgentDefinition) {
    await api.updateAgent(agent.agent_id, agent)
    const idx = agents.value.findIndex(a => a.agent_id === agent.agent_id)
    if (idx >= 0) agents.value[idx] = agent
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
