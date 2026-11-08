import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import type { CharacterAsset, LocationAsset, Foreshadowing } from '@/types/asset'

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listCharacters: vi.fn(),
    addCharacter: vi.fn(),
    deleteCharacter: vi.fn(),
    listLocations: vi.fn(),
    addLocation: vi.fn(),
    listForeshadowings: vi.fn(),
    addForeshadowing: vi.fn(),
    transitionForeshadowing: vi.fn(),
  },
}))

vi.mock('@/composables/useApi', () => ({ useApi: () => apiMock }))

import { useAssetStore } from '@/stores/assetStore'

function char(name: string): CharacterAsset {
  return { name, importance_tier: 'primary', persona: '', motivation: '', secrets: '' }
}

function loc(name: string): LocationAsset {
  return { name, description: '' }
}

function foreshadowing(id: string, status: Foreshadowing['status'] = 'planted'): Foreshadowing {
  return {
    foreshadow_id: id, description: id, status,
    planted_in_scene: 's1', target_revelation: '',
    reinforcement_count: 0, scenes_since_last_mention: 0,
    max_dormant_scenes: 5, linked_characters: [],
  }
}

describe('assetStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    Object.values(apiMock).forEach(fn => fn.mockReset())
  })

  it('fetchAll 并行拉取角色 / 地点 / 伏笔', async () => {
    apiMock.listCharacters.mockResolvedValue({ data: [char('林夏')] })
    apiMock.listLocations.mockResolvedValue({ data: [loc('旅店')] })
    apiMock.listForeshadowings.mockResolvedValue({ data: [foreshadowing('f1')] })
    const store = useAssetStore()

    await store.fetchAll('p1')

    expect(apiMock.listCharacters).toHaveBeenCalledWith('p1')
    expect(apiMock.listLocations).toHaveBeenCalledWith('p1')
    expect(apiMock.listForeshadowings).toHaveBeenCalledWith('p1')
    expect(store.characters).toHaveLength(1)
    expect(store.locations).toHaveLength(1)
    expect(store.foreshadowings).toHaveLength(1)
  })

  it('addCharacter 调用接口后追加到本地列表', async () => {
    apiMock.addCharacter.mockResolvedValue({ data: {} })
    const store = useAssetStore()

    await store.addCharacter('p1', char('林夏'))

    expect(apiMock.addCharacter).toHaveBeenCalledWith('p1', expect.objectContaining({ name: '林夏' }))
    expect(store.characters.map(c => c.name)).toEqual(['林夏'])
  })

  it('removeCharacter 调用接口后从本地移除', async () => {
    apiMock.deleteCharacter.mockResolvedValue({})
    const store = useAssetStore()
    store.characters = [char('林夏'), char('李雷')]

    await store.removeCharacter('p1', '林夏')

    expect(apiMock.deleteCharacter).toHaveBeenCalledWith('p1', '林夏')
    expect(store.characters.map(c => c.name)).toEqual(['李雷'])
  })

  it('addLocation 调用接口后追加到本地列表', async () => {
    apiMock.addLocation.mockResolvedValue({ data: {} })
    const store = useAssetStore()

    await store.addLocation('p1', loc('旅店'))

    expect(store.locations.map(l => l.name)).toEqual(['旅店'])
  })

  it('addForeshadowing 调用接口后追加到本地列表', async () => {
    apiMock.addForeshadowing.mockResolvedValue({ data: {} })
    const store = useAssetStore()

    await store.addForeshadowing('p1', { description: '神秘信件' })

    expect(store.foreshadowings).toHaveLength(1)
  })

  it('transitionForeshadowing 成功后更新本地对应项', async () => {
    const updated = foreshadowing('f1', 'activated')
    apiMock.transitionForeshadowing.mockResolvedValue({ data: updated })
    const store = useAssetStore()
    store.foreshadowings = [foreshadowing('f1', 'planted')]

    await store.transitionForeshadowing('p1', 'f1', 'activate')

    expect(apiMock.transitionForeshadowing).toHaveBeenCalledWith('p1', 'f1', 'activate')
    expect(store.foreshadowings[0].status).toBe('activated')
  })

  it('transitionForeshadowing 抛出后端错误', async () => {
    apiMock.transitionForeshadowing.mockRejectedValue(new Error('非法动作'))
    const store = useAssetStore()
    store.foreshadowings = [foreshadowing('f1')]

    await expect(store.transitionForeshadowing('p1', 'f1', 'illegal')).rejects.toThrow('非法动作')
  })
})
