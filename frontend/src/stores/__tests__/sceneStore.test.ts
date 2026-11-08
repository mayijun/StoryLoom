import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import type { SceneView } from '@/types/scene'

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listScenes: vi.fn(),
    assignSceneToChapter: vi.fn(),
    updateScene: vi.fn(),
    regenerateScene: vi.fn(),
    getScene: vi.fn(),
    deleteScene: vi.fn(),
  },
}))

vi.mock('@/composables/useApi', () => ({ useApi: () => apiMock }))

import { useSceneStore } from '@/stores/sceneStore'

function scene(id: string, chapterId: string | null, overrides: Partial<SceneView> = {}): SceneView {
  return {
    scene_id: id,
    project_id: 'p1',
    chapter_id: chapterId,
    brief: `brief-${id}`,
    present_characters: [],
    prose: `prose-${id}`,
    quality_score: 0.8,
    duration_ms: 1200,
    model_usage: {},
    created_at: null,
    ...overrides,
  }
}

describe('sceneStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    Object.values(apiMock).forEach(fn => fn.mockReset())
  })

  it('fetchScenes 拉取全部场景并重置 loading', async () => {
    apiMock.listScenes.mockResolvedValue({ data: [scene('s1', 'c1'), scene('s2', null)] })
    const store = useSceneStore()

    await store.fetchScenes('p1')

    expect(apiMock.listScenes).toHaveBeenCalledWith('p1')
    expect(store.scenes).toHaveLength(2)
    expect(store.loading).toBe(false)
  })

  it('unassignedScenes 仅返回未归属场景', () => {
    const store = useSceneStore()
    store.scenes = [scene('s1', 'c1'), scene('s2', null), scene('s3', null)]

    expect(store.unassignedScenes.map(s => s.scene_id)).toEqual(['s2', 's3'])
  })

  it('sceneCountByChapter 统计各章节场景数', () => {
    const store = useSceneStore()
    store.scenes = [scene('s1', 'c1'), scene('s2', 'c1'), scene('s3', 'c2'), scene('s4', null)]

    expect(store.sceneCountByChapter).toEqual({ c1: 2, c2: 1 })
  })

  it('scenesByChapter 返回指定章节的场景 computed', () => {
    const store = useSceneStore()
    store.scenes = [scene('s1', 'c1'), scene('s2', 'c1'), scene('s3', 'c2')]

    expect(store.scenesByChapter('c1').value.map(s => s.scene_id)).toEqual(['s1', 's2'])
    expect(store.scenesByChapter('c9').value).toEqual([])
  })

  it('assignScene 调用归属接口并更新本地场景', async () => {
    const store = useSceneStore()
    store.scenes = [scene('s1', null)]
    apiMock.assignSceneToChapter.mockResolvedValue({ data: scene('s1', 'c1') })

    await store.assignScene('p1', 's1', 'c1')

    expect(apiMock.assignSceneToChapter).toHaveBeenCalledWith('p1', 's1', 'c1')
    expect(store.scenes[0].chapter_id).toBe('c1')
  })

  it('unassignScene 以 null 调用归属接口', async () => {
    const store = useSceneStore()
    store.scenes = [scene('s1', 'c1')]
    apiMock.assignSceneToChapter.mockResolvedValue({ data: scene('s1', null) })

    await store.unassignScene('p1', 's1')

    expect(apiMock.assignSceneToChapter).toHaveBeenCalledWith('p1', 's1', null)
    expect(store.scenes[0].chapter_id).toBeNull()
  })

  it('updateSceneProse 保存正文并更新本地缓存', async () => {
    const store = useSceneStore()
    store.scenes = [scene('s1', 'c1')]
    apiMock.updateScene.mockResolvedValue({ data: scene('s1', 'c1', { prose: '新正文' }) })

    await store.updateSceneProse('p1', 's1', '新正文')

    expect(apiMock.updateScene).toHaveBeenCalledWith('p1', 's1', { prose: '新正文' })
    expect(store.scenes[0].prose).toBe('新正文')
  })

  describe('regenerateScene', () => {
    it('重跑后重新拉取并替换已有场景', async () => {
      const store = useSceneStore()
      store.scenes = [scene('s1', 'c1')]
      apiMock.regenerateScene.mockResolvedValue({ data: { scene_id: 's1' } })
      apiMock.getScene.mockResolvedValue({ data: scene('s1', 'c1', { prose: '重跑正文' }) })

      await store.regenerateScene('p1', 's1')

      expect(apiMock.regenerateScene).toHaveBeenCalledWith('p1', 's1')
      expect(apiMock.getScene).toHaveBeenCalledWith('p1', 's1')
      expect(store.scenes).toHaveLength(1)
      expect(store.scenes[0].prose).toBe('重跑正文')
    })

    it('重跑返回新场景 id 时追加到列表', async () => {
      const store = useSceneStore()
      store.scenes = []
      apiMock.regenerateScene.mockResolvedValue({ data: { scene_id: 's9' } })
      apiMock.getScene.mockResolvedValue({ data: scene('s9', 'c1') })

      await store.regenerateScene('p1', 's1')

      expect(apiMock.getScene).toHaveBeenCalledWith('p1', 's9')
      expect(store.scenes.map(s => s.scene_id)).toEqual(['s9'])
    })
  })

  it('removeScene 调用接口并从本地列表移除', async () => {
    apiMock.deleteScene.mockResolvedValue({})
    const store = useSceneStore()
    store.scenes = [scene('s1', 'c1'), scene('s2', null)]

    await store.removeScene('p1', 's2')

    expect(apiMock.deleteScene).toHaveBeenCalledWith('p1', 's2')
    expect(store.scenes.map(s => s.scene_id)).toEqual(['s1'])
  })
})
