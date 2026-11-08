import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const { mockApi, mockRuntime } = vi.hoisted(() => ({
  mockApi: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    patch: vi.fn(),
  },
  mockRuntime: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

vi.mock('axios', () => ({
  default: {
    create: vi.fn((cfg: { baseURL: string }) =>
      cfg.baseURL === '/api' ? mockApi : mockRuntime,
    ),
  },
}))

import { useApi } from '@/composables/useApi'

const { get, post, put, patch, del } = {
  get: mockApi.get,
  post: mockApi.post,
  put: mockApi.put,
  patch: mockApi.patch,
  del: mockApi.delete,
}

describe('useApi', () => {
  const api = useApi()

  beforeEach(() => {
    Object.values(mockApi).forEach(fn => fn.mockReset())
    Object.values(mockRuntime).forEach(fn => fn.mockReset())
  })

  it('listProjects / createProject / getProject 路径正确', async () => {
    await api.listProjects()
    expect(get).toHaveBeenCalledWith('/projects/')

    await api.createProject({ title: 'x', style: 'y' })
    expect(post).toHaveBeenCalledWith('/projects/', { title: 'x', style: 'y' })

    await api.getProject('p1')
    expect(get).toHaveBeenCalledWith('/projects/p1')
  })

  describe('listScenes — chapter_id 参数处理', () => {
    it('未传 chapterId 时不带 params', async () => {
      await api.listScenes('p1')
      expect(get).toHaveBeenCalledWith('/projects/p1/scenes', { params: {} })
    })

    it('chapterId 为 null 时传字符串 "null"（后端约定）', async () => {
      await api.listScenes('p1', null)
      expect(get).toHaveBeenCalledWith('/projects/p1/scenes', {
        params: { chapter_id: 'null' },
      })
    })

    it('chapterId 为具体 id 时传该值', async () => {
      await api.listScenes('p1', 'c1')
      expect(get).toHaveBeenCalledWith('/projects/p1/scenes', {
        params: { chapter_id: 'c1' },
      })
    })
  })

  it('assignSceneToChapter 用 PATCH 并携带 chapter_id', async () => {
    await api.assignSceneToChapter('p1', 's1', 'c1')
    expect(patch).toHaveBeenCalledWith('/projects/p1/scenes/s1/chapter', {
      chapter_id: 'c1',
    })

    await api.assignSceneToChapter('p1', 's1', null)
    expect(patch).toHaveBeenCalledWith('/projects/p1/scenes/s1/chapter', {
      chapter_id: null,
    })
  })

  describe('Agents — project_id 通过 params 透传', () => {
    it('listAgents 有 projectId 时带 params', async () => {
      await api.listAgents('p1')
      expect(get).toHaveBeenCalledWith('/agents/', { params: { project_id: 'p1' } })
    })

    it('listAgents 无 projectId 时 params 为 undefined', async () => {
      await api.listAgents()
      expect(get).toHaveBeenCalledWith('/agents/', { params: undefined })
    })

    it('createAgent POST 带 data 与 params', async () => {
      const data = { key: 'a1', role: 'r', goal: 'g', backstory: 'b' }
      await api.createAgent(data, 'p1')
      expect(post).toHaveBeenCalledWith('/agents/', data, {
        params: { project_id: 'p1' },
      })
    })

    it('deleteAgent DELETE 带 params', async () => {
      await api.deleteAgent('a1', 'p1')
      expect(del).toHaveBeenCalledWith('/agents/a1', {
        params: { project_id: 'p1' },
      })
    })
  })

  it('copyConfigFrom 默认 mode 为 overwrite', async () => {
    await api.copyConfigFrom('p1', 'p2')
    expect(post).toHaveBeenCalledWith('/projects/p1/config/copy_from', {
      source_project_id: 'p2',
      mode: 'overwrite',
    })
  })

  it('copyConfigFrom 支持显式 merge', async () => {
    await api.copyConfigFrom('p1', 'p2', 'merge')
    expect(post).toHaveBeenCalledWith('/projects/p1/config/copy_from', {
      source_project_id: 'p2',
      mode: 'merge',
    })
  })

  it('exportNovelUrl 返回拼接好的下载地址', () => {
    expect(api.exportNovelUrl('p1', 'md')).toBe('/api/projects/p1/export?format=md')
    expect(api.exportNovelUrl('p1', 'txt')).toBe('/api/projects/p1/export?format=txt')
  })

  it('getMemory / patchMemory 路径与方法正确', async () => {
    await api.getMemory('p1')
    expect(get).toHaveBeenCalledWith('/projects/p1/memory')

    await api.patchMemory('p1', 'chroma')
    expect(patch).toHaveBeenCalledWith('/projects/p1/memory', { backend: 'chroma' })
  })

  it('regenerateScene 为 POST', async () => {
    await api.regenerateScene('p1', 's1')
    expect(post).toHaveBeenCalledWith('/projects/p1/scenes/s1/regenerate')
  })

  describe('generateSceneStream', () => {
    const originalFetch = global.fetch
    const originalEventSource = global.EventSource

    afterEach(() => {
      global.fetch = originalFetch
      global.EventSource = originalEventSource
    })

    it('逐行解析 data: 事件并回调 onMessage', async () => {
      global.EventSource = vi.fn() as any
      const lines = 'data: {"step":"1"}\n\ndata: {"step":"2"}\n\n'
      let done = false
      const fakeBody = {
        getReader: () => ({
          read: () => {
            if (done) return Promise.resolve({ done: true })
            done = true
            return Promise.resolve({ done: false, value: new TextEncoder().encode(lines) })
          },
        }),
      }
      global.fetch = vi.fn().mockResolvedValue({ body: fakeBody } as any)

      const messages: any[] = []
      await api.generateSceneStream({ brief: 'x' }, msg => messages.push(msg))

      expect(global.fetch).toHaveBeenCalledWith(
        '/api/generate/scene/stream',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ brief: 'x' }),
        }),
      )
      expect(messages).toEqual([{ step: '1' }, { step: '2' }])
    })

    it('忽略非 data: 前缀与非法 JSON', async () => {
      global.EventSource = vi.fn() as any
      const lines = 'event: foo\ninvalid json\ndata: {"ok":true}\n'
      let done = false
      const fakeBody = {
        getReader: () => ({
          read: () => {
            if (done) return Promise.resolve({ done: true })
            done = true
            return Promise.resolve({ done: false, value: new TextEncoder().encode(lines) })
          },
        }),
      }
      global.fetch = vi.fn().mockResolvedValue({ body: fakeBody } as any)

      const messages: any[] = []
      await api.generateSceneStream({}, msg => messages.push(msg))

      expect(messages).toEqual([{ ok: true }])
    })
  })

  describe('Runtime（游戏模式）', () => {
    it('playTurn / getGameState 走 runtime 实例', async () => {
      await api.playTurn('p1', { action: 'go' })
      expect(mockRuntime.post).toHaveBeenCalledWith('/p1/turn', { action: 'go' })

      await api.getGameState('p1')
      expect(mockRuntime.get).toHaveBeenCalledWith('/p1/state', {
        params: { instance_id: 'ui' },
      })
    })

    it('switchGameMode 默认 instance_id 为 ui', async () => {
      await api.switchGameMode('p1', 'game')
      expect(mockRuntime.post).toHaveBeenCalledWith('/p1/mode', {
        mode: 'game',
        instance_id: 'ui',
      })
    })

    it('loadGameSave 带 instance_id params', async () => {
      await api.loadGameSave('p1', 'save1', 'ui')
      expect(mockRuntime.post).toHaveBeenCalledWith(
        '/p1/saves/save1/load',
        null,
        { params: { instance_id: 'ui' } },
      )
    })
  })
})
