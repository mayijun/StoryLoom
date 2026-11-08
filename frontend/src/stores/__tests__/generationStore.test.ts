import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    generateScene: vi.fn(),
  },
}))

vi.mock('@/composables/useApi', () => ({ useApi: () => apiMock }))

import { useGenerationStore } from '@/stores/generationStore'

const successResponse = {
  data: {
    scene_id: 's1',
    final_prose: '生成后的正文',
    steps: [
      { agent_name: '作家', agent_type: 'writer', content: '完成初稿' },
    ],
  },
}

describe('generationStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    Object.values(apiMock).forEach(fn => fn.mockReset())
  })

  it('生成成功：写入正文、当前场景与历史', async () => {
    apiMock.generateScene.mockResolvedValue(successResponse)
    const store = useGenerationStore()

    await store.generateScene('p1', '场景 brief', ['林夏'])

    expect(apiMock.generateScene).toHaveBeenCalledWith({
      project_id: 'p1',
      scene_brief: '场景 brief',
      present_character_names: ['林夏'],
      render_mode: 'text_only',
    })
    expect(store.currentSceneId).toBe('s1')
    expect(store.finalProse).toBe('生成后的正文')
    expect(store.generationHistory).toHaveLength(1)
    expect(store.isGenerating).toBe(false)
  })

  it('生成失败：复位生成状态且不保留当前场景', async () => {
    apiMock.generateScene.mockRejectedValue(new Error('生成失败'))
    const store = useGenerationStore()

    await expect(store.generateScene('p1', 'brief', ['林夏'])).rejects.toThrow('生成失败')

    expect(store.isGenerating).toBe(false)
    expect(store.currentStep).toBe('')
    expect(store.currentSceneId).toBeNull()
    expect(store.generationHistory).toHaveLength(0)
  })

  it('reset 清空写作态', async () => {
    apiMock.generateScene.mockResolvedValue(successResponse)
    const store = useGenerationStore()
    await store.generateScene('p1', 'brief', ['林夏'])

    store.reset()

    expect(store.finalProse).toBe('')
    expect(store.currentSceneId).toBeNull()
    expect(store.generationHistory).toHaveLength(0)
  })

  it('setCurrentScene 可切换当前场景', () => {
    const store = useGenerationStore()

    store.setCurrentScene('s9')

    expect(store.currentSceneId).toBe('s9')
  })
})
