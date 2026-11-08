import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import type { AgentConfig, AgentConfigInput, AgentMessage } from '@/types/agent'

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listAgents: vi.fn(),
    createAgent: vi.fn(),
    updateAgent: vi.fn(),
    deleteAgent: vi.fn(),
  },
}))

vi.mock('@/composables/useApi', () => ({ useApi: () => apiMock }))

import { useAgentStore } from '@/stores/agentStore'

function agent(key: string, position = 0, enabled = true): AgentConfig {
  return {
    key, crew: 'default', role: key, goal: '', backstory: '',
    settings: {}, enabled, position,
  }
}

function message(id: string, agentId: string): AgentMessage {
  return {
    message_id: id, agent_id: agentId, agent_type: 'writer', agent_name: agentId,
    content: '内容', timestamp: 1, message_type: 'system',
  }
}

describe('agentStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    Object.values(apiMock).forEach(fn => fn.mockReset())
  })

  it('fetchAgents 拉取 agents 与可用模型', async () => {
    apiMock.listAgents.mockResolvedValue({
      data: { agents: [agent('a1')], available_models: ['gpt-4o'] },
    })
    const store = useAgentStore()

    await store.fetchAgents('p1')

    expect(apiMock.listAgents).toHaveBeenCalledWith('p1')
    expect(store.agents.map(a => a.key)).toEqual(['a1'])
    expect(store.availableModels).toEqual(['gpt-4o'])
  })

  it('enabledAgents 仅返回启用的 Agent', () => {
    const store = useAgentStore()
    store.agents = [agent('a1', 0, true), agent('a2', 1, false)]

    expect(store.enabledAgents.map(a => a.key)).toEqual(['a1'])
  })

  it('addAgent 调用接口并追加到列表', async () => {
    const input: AgentConfigInput = { key: 'a2', role: 'r', goal: 'g', backstory: 'b' }
    apiMock.createAgent.mockResolvedValue({ data: agent('a2') })
    const store = useAgentStore()

    await store.addAgent(input, 'p1')

    expect(apiMock.createAgent).toHaveBeenCalledWith(input, 'p1')
    expect(store.agents.map(a => a.key)).toEqual(['a2'])
  })

  it('removeAgent 调用接口并从列表移除', async () => {
    apiMock.deleteAgent.mockResolvedValue({})
    const store = useAgentStore()
    store.agents = [agent('a1'), agent('a2')]

    await store.removeAgent('a1', 'p1')

    expect(apiMock.deleteAgent).toHaveBeenCalledWith('a1', 'p1')
    expect(store.agents.map(a => a.key)).toEqual(['a2'])
  })

  it('updateAgent 更新本地对应项', async () => {
    apiMock.updateAgent.mockResolvedValue({ data: agent('a1', 0, false) })
    const store = useAgentStore()
    store.agents = [agent('a1', 0, true)]

    await store.updateAgent('a1', { enabled: false }, 'p1')

    expect(apiMock.updateAgent).toHaveBeenCalledWith('a1', { enabled: false }, 'p1')
    expect(store.agents[0].enabled).toBe(false)
  })

  describe('reorderAgents', () => {
    it('按新顺序重排并持久化变化项 position', async () => {
      apiMock.updateAgent.mockResolvedValue({ data: {} })
      const store = useAgentStore()
      const a1 = agent('a1', 0)
      const a2 = agent('a2', 1)
      store.agents = [a1, a2]

      await store.reorderAgents([a2, a1], 'p1')

      expect(store.agents.map(a => a.key)).toEqual(['a2', 'a1'])
      expect(store.agents.map(a => a.position)).toEqual([0, 1])
      expect(apiMock.updateAgent).toHaveBeenCalledTimes(2)
    })

    it('顺序不变时不提交更新', async () => {
      const store = useAgentStore()
      store.agents = [agent('a1', 0), agent('a2', 1)]

      await store.reorderAgents([agent('a1', 0), agent('a2', 1)], 'p1')

      expect(apiMock.updateAgent).not.toHaveBeenCalled()
    })

    it('持久化失败时回滚本地顺序并抛出错误', async () => {
      apiMock.updateAgent.mockRejectedValue(new Error('network'))
      const store = useAgentStore()
      store.agents = [agent('a1', 0), agent('a2', 1)]

      await expect(
        store.reorderAgents([agent('a2', 1), agent('a1', 0)], 'p1')
      ).rejects.toThrow('排序保存失败')

      expect(store.agents.map(a => a.key)).toEqual(['a1', 'a2'])
    })
  })

  it('addMessage / clearMessages 维护消息列表', () => {
    const store = useAgentStore()

    store.addMessage(message('m1', 'a1'))
    store.addMessage(message('m2', 'a2'))

    expect(store.messages).toHaveLength(2)

    store.clearMessages()

    expect(store.messages).toHaveLength(0)
  })
})
