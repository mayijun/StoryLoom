import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    getGameState: vi.fn(),
    getMemory: vi.fn(),
    listGameSaves: vi.fn(),
    resolveExtensions: vi.fn(),
    playTurn: vi.fn(),
    switchGameMode: vi.fn(),
    patchMemory: vi.fn(),
    createGameSave: vi.fn(),
    loadGameSave: vi.fn(),
  },
}))

vi.mock('@/composables/useApi', () => ({ useApi: () => apiMock }))

import GamePanel from '@/components/GamePanel.vue'

const gameState = (overrides: any = {}) => ({
  data: {
    state: { mode: 'game', turn: 1, time_minutes: 600, characters: {} },
    memory: { backend: 'fts', counts: {} },
    ...overrides,
  },
})

const playResponse = (overrides: any = {}) => ({
  data: {
    state: { mode: 'game', turn: 2, characters: {} },
    text: '世界回应了你。',
    choices: [{ index: 0, label: '继续' }],
    quality: 0.8,
    quality_flags: [],
    scene: { directives: [] },
    ...overrides,
  },
})

function mountPanel(props: any = {}) {
  return mount(GamePanel, {
    props: { projectId: 'p1', projectTitle: 'Demo', active: true, ...props },
  })
}

describe('GamePanel', () => {
  beforeEach(() => {
    Object.values(apiMock).forEach(fn => fn.mockReset())
    apiMock.getGameState.mockResolvedValue(gameState())
    apiMock.getMemory.mockResolvedValue({ data: { items: [], backend: 'fts', counts: {} } })
    apiMock.listGameSaves.mockResolvedValue({ data: { saves: [] } })
    apiMock.resolveExtensions.mockResolvedValue({ data: { skills: [] } })
  })

  it('mount 后载入游戏状态，状态栏显示回合与地点', async () => {
    apiMock.getGameState.mockResolvedValue(
      gameState({
        state: {
          mode: 'game', turn: 3, time_minutes: 600,
          characters: { 玩家: { name: '玩家', location: '码头', status: 'active' } },
        },
      }),
    )
    const wrapper = mountPanel()
    await flushPromises()

    expect(apiMock.getGameState).toHaveBeenCalledWith('p1', 'ui')
    expect(wrapper.find('.game-status').text()).toContain('游戏')
    expect(wrapper.find('.game-status').text()).toContain('第3回合')
    expect(wrapper.find('.game-status').text()).toContain('码头')
  })

  it('state 为 null 时状态栏显示「载入中…」', () => {
    // 不 await flushPromises，state 还未回填
    const wrapper = mountPanel()
    expect(wrapper.find('.game-status').text()).toBe('载入中…')
  })

  it('发送文本：调用 playTurn 并追加玩家/旁白消息', async () => {
    apiMock.playTurn.mockResolvedValue(playResponse())
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.find('textarea').setValue('我拔剑')
    await wrapper.find('.input-actions button').trigger('click')
    await flushPromises()

    expect(apiMock.playTurn).toHaveBeenCalledWith('p1', expect.objectContaining({
      instance_id: 'ui',
      mode: 'game',
      intent: { kind: 'text', payload: { text: '我拔剑' } },
    }))
    const entries = wrapper.findAll('.entry')
    expect(entries[entries.length - 2].text()).toContain('我拔剑')
    expect(entries[entries.length - 1].text()).toContain('世界回应了你。')
    // 行动选项渲染
    expect(wrapper.find('.choices').text()).toContain('继续')
  })

  it('点击 Agent 推荐行动时保留自然语言 text', async () => {
    apiMock.playTurn.mockResolvedValue(playResponse({
      choices: [{ index: 0, label: '问老板账单是谁留下的', text: '问老板账单是谁留下的', source: 'agent' }],
    }))
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.find('textarea').setValue('观察四周')
    await wrapper.find('.input-actions button').trigger('click')
    await flushPromises()
    await wrapper.find('.choice').trigger('click')
    await flushPromises()

    expect(apiMock.playTurn).toHaveBeenLastCalledWith('p1', expect.objectContaining({
      intent: {
        kind: 'choice',
        payload: expect.objectContaining({
          label: '问老板账单是谁留下的',
          text: '问老板账单是谁留下的',
        }),
      },
    }))
  })

  it('等待回合：intent.kind 为 skip 且 idleTurns 自增', async () => {
    apiMock.playTurn.mockResolvedValue(playResponse({ text: '你原地等待。' }))
    const wrapper = mountPanel()
    await flushPromises()

    const waitBtn = wrapper.findAll('.input-actions button')[1]
    await waitBtn.trigger('click')
    await flushPromises()

    expect(apiMock.playTurn).toHaveBeenCalledWith('p1', expect.objectContaining({
      intent: { kind: 'skip' },
      idle_turns: 0,
    }))
    const kvs = wrapper.findAll('.kv')
    expect(kvs[kvs.length - 1].text()).toContain('1')
  })

  it('playTurn 失败时显示错误状态', async () => {
    apiMock.playTurn.mockRejectedValue({ response: { data: { detail: '后端崩了' } } })
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.find('textarea').setValue('测试')
    await wrapper.find('.input-actions button').trigger('click')
    await flushPromises()

    expect(wrapper.find('.status-note').text()).toBe('后端崩了')
  })

  it('存档弹窗：填写名称后调用 createGameSave 并刷新存档列表', async () => {
    apiMock.getGameState.mockResolvedValue(
      gameState({ state: { mode: 'game', turn: 5, characters: { 玩家: { location: '旅店' } } } }),
    )
    apiMock.createGameSave.mockResolvedValue({ data: {} })
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.findAll('.game-actions button')[1].trigger('click')
    expect(wrapper.find('.modal').exists()).toBe(true)
    expect((wrapper.find('.modal-input').element as HTMLInputElement).value).toContain('旅店')
    expect((wrapper.find('.modal-input').element as HTMLInputElement).value).toContain('第5回合')

    await wrapper.find('.modal-input').setValue('我的存档')
    await wrapper.findAll('.modal-actions button')[1].trigger('click')
    await flushPromises()

    expect(apiMock.createGameSave).toHaveBeenCalledWith('p1', expect.objectContaining({
      instance_id: 'ui',
      label: '我的存档',
    }))
    expect(wrapper.find('.modal').exists()).toBe(false)
  })

  it('空存档名时保存按钮被禁用，不调用接口', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.findAll('.game-actions button')[1].trigger('click')
    await wrapper.find('.modal-input').setValue('   ')

    const saveBtn = wrapper.findAll('.modal-actions button')[1]
    expect((saveBtn.element as HTMLButtonElement).disabled).toBe(true)

    await saveBtn.trigger('click')
    expect(apiMock.createGameSave).not.toHaveBeenCalled()
  })

  it('读取存档：调用 loadGameSave 并恢复 backlog', async () => {
    apiMock.listGameSaves.mockResolvedValue({
      data: { saves: [{ save_id: 'sv1', label: '存档1', kind: 'story', mode: 'game', created_at: '2026-01-01T00:00:00' }] },
    })
    apiMock.loadGameSave.mockResolvedValue({
      data: { label: '存档1', mode: 'game', text: '旧的一幕', directives: [], choices: [] },
    })
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.find('.save-item').trigger('click')
    await flushPromises()

    expect(apiMock.loadGameSave).toHaveBeenCalledWith('p1', 'sv1', 'ui')
    expect(wrapper.find('.backlog').text()).toContain('已读档')
    expect(wrapper.find('.backlog').text()).toContain('旧的一幕')
  })

  it('切换记忆后端：调用 patchMemory 并追加系统消息', async () => {
    apiMock.patchMemory.mockResolvedValue({ data: { items: [], backend: 'vector', counts: {} } })
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.find('select').setValue('vector')
    await flushPromises()

    expect(apiMock.patchMemory).toHaveBeenCalledWith('p1', 'vector')
    expect(wrapper.find('.backlog').text()).toContain('记忆检索后端已切换为 vector')
  })

  it('toggleMode 从游戏切到导演：成功后 emit close', async () => {
    apiMock.switchGameMode.mockResolvedValue({ data: { state: { mode: 'director' }, mode: 'director' } })
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.findAll('.game-actions button')[0].trigger('click')
    await flushPromises()

    expect(apiMock.switchGameMode).toHaveBeenCalledWith('p1', 'director', 'ui')
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('退出按钮 emit close 事件', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.findAll('.game-actions button')[2].trigger('click')

    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('checkpointLabel 对系统日志做友好展示', async () => {
    apiMock.listGameSaves.mockResolvedValue({
      data: {
        saves: [
          { save_id: 'cp1', label: 'switch_to_director', kind: 'checkpoint', turn: 2 },
          { save_id: 'cp2', label: 'before_override_x', kind: 'checkpoint', turn: 3 },
        ],
      },
    })
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.find('.checkpoint-toggle').trigger('click')

    const labels = wrapper.findAll('.save-item').map(s => s.text())
    expect(labels.some(t => t.includes('切到导演模式'))).toBe(true)
    expect(labels.some(t => t.includes('导演改写前'))).toBe(true)
  })
})
