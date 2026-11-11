import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    submitSceneGenerate: vi.fn(),
    getGenerateTask: vi.fn(),
    deleteGenerateTask: vi.fn(),
  },
}))

vi.mock('@/composables/useApi', () => ({ useApi: () => apiMock }))

import { useGenerationStore } from '@/stores/generationStore'

const sceneResult = {
  scene_id: 's1',
  final_prose: '生成后的正文',
  steps: [
    { agent_name: '作家', agent_type: 'writer', content: '完成初稿' },
  ],
}

const doneTask = {
  data: {
    task_id: 't1',
    status: 'done',
    progress: 100,
    step: '润色叙事',
    result: sceneResult,
  },
}

/** 让 store 的轮询走完：推进一次 1.5s 定时器，再等待任务完成后的第二次取结果。 */
async function runToDone(store: ReturnType<typeof useGenerationStore>) {
  const promise = store.generateScene('p1', '场景 brief', ['林夏'])
  await vi.advanceTimersByTimeAsync(1500)
  await promise
}

describe('generationStore', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    Object.values(apiMock).forEach(fn => fn.mockReset())
    apiMock.deleteGenerateTask.mockResolvedValue({ data: {} })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('生成成功：提交任务、轮询结果并写入正文/当前场景/历史', async () => {
    apiMock.submitSceneGenerate.mockResolvedValue({ data: { task_id: 't1' } })
    apiMock.getGenerateTask.mockResolvedValue(doneTask)
    const store = useGenerationStore()

    await runToDone(store)

    expect(apiMock.submitSceneGenerate).toHaveBeenCalledWith({
      project_id: 'p1',
      scene_brief: '场景 brief',
      present_character_names: ['林夏'],
      render_mode: 'text_only',
      chapter_id: null,
    })
    expect(apiMock.getGenerateTask).toHaveBeenCalledWith('t1')
    expect(apiMock.deleteGenerateTask).toHaveBeenCalledWith('t1')
    expect(store.currentSceneId).toBe('s1')
    expect(store.finalProse).toBe('生成后的正文')
    expect(store.generationHistory).toHaveLength(1)
    expect(store.isGenerating).toBe(false)
    expect(store.taskId).toBeNull()
  })

  it('提交失败：复位生成状态且不保留当前场景', async () => {
    apiMock.submitSceneGenerate.mockRejectedValue(new Error('生成失败'))
    const store = useGenerationStore()

    await expect(store.generateScene('p1', 'brief', ['林夏'])).rejects.toThrow('生成失败')

    expect(store.isGenerating).toBe(false)
    expect(store.currentStep).toBe('')
    expect(store.currentSceneId).toBeNull()
    expect(store.generationHistory).toHaveLength(0)
  })

  it('后端任务失败：抛出错误并复位状态', async () => {
    apiMock.submitSceneGenerate.mockResolvedValue({ data: { task_id: 't1' } })
    apiMock.getGenerateTask.mockResolvedValue({
      data: { task_id: 't1', status: 'failed', progress: 0, error: '模型不可用' },
    })
    const store = useGenerationStore()

    const promise = store.generateScene('p1', 'brief', ['林夏'])
    const assertion = expect(promise).rejects.toThrow('模型不可用')
    await vi.advanceTimersByTimeAsync(1500)
    await assertion

    expect(store.isGenerating).toBe(false)
    expect(store.currentSceneId).toBeNull()
  })

  it('reset 清空写作态', async () => {
    apiMock.submitSceneGenerate.mockResolvedValue({ data: { task_id: 't1' } })
    apiMock.getGenerateTask.mockResolvedValue(doneTask)
    const store = useGenerationStore()
    await runToDone(store)

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
