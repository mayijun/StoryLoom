import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import type { TaskConfig, TaskConfigInput } from '@/types/task'

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listTasks: vi.fn(),
    createTask: vi.fn(),
    updateTask: vi.fn(),
    deleteTask: vi.fn(),
  },
}))

vi.mock('@/composables/useApi', () => ({ useApi: () => apiMock }))

import { useTaskStore } from '@/stores/taskStore'

function task(key: string, position = 0, enabled = true): TaskConfig {
  return {
    key, crew: 'default', description: '', expected_output: '',
    context_keys: [], enabled, position,
  }
}

describe('taskStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    Object.values(apiMock).forEach(fn => fn.mockReset())
  })

  it('fetchTasks 拉取任务列表', async () => {
    apiMock.listTasks.mockResolvedValue({ data: { tasks: [task('t1')] } })
    const store = useTaskStore()

    await store.fetchTasks('p1')

    expect(apiMock.listTasks).toHaveBeenCalledWith('p1')
    expect(store.tasks.map(t => t.key)).toEqual(['t1'])
  })

  it('enabledTasks 仅返回启用任务', () => {
    const store = useTaskStore()
    store.tasks = [task('t1', 0, true), task('t2', 1, false)]

    expect(store.enabledTasks.map(t => t.key)).toEqual(['t1'])
  })

  it('addTask 调用接口并追加', async () => {
    const input: TaskConfigInput = { key: 't1', description: 'd', expected_output: 'o' }
    apiMock.createTask.mockResolvedValue({ data: task('t1') })
    const store = useTaskStore()

    await store.addTask(input, 'p1')

    expect(apiMock.createTask).toHaveBeenCalledWith(input, 'p1')
    expect(store.tasks).toHaveLength(1)
  })

  it('removeTask 调用接口并移除', async () => {
    apiMock.deleteTask.mockResolvedValue({})
    const store = useTaskStore()
    store.tasks = [task('t1'), task('t2')]

    await store.removeTask('t1', 'p1')

    expect(apiMock.deleteTask).toHaveBeenCalledWith('t1', 'p1')
    expect(store.tasks.map(t => t.key)).toEqual(['t2'])
  })

  it('updateTask 更新本地对应项', async () => {
    apiMock.updateTask.mockResolvedValue({ data: task('t1', 0, false) })
    const store = useTaskStore()
    store.tasks = [task('t1', 0, true)]

    await store.updateTask('t1', { enabled: false }, 'p1')

    expect(apiMock.updateTask).toHaveBeenCalledWith('t1', { enabled: false }, 'p1')
    expect(store.tasks[0].enabled).toBe(false)
  })

  describe('reorderTasks', () => {
    it('按新顺序重排并持久化变化项', async () => {
      apiMock.updateTask.mockResolvedValue({ data: {} })
      const store = useTaskStore()
      const t1 = task('t1', 0)
      const t2 = task('t2', 1)
      store.tasks = [t1, t2]

      await store.reorderTasks([t2, t1], 'p1')

      expect(store.tasks.map(t => t.key)).toEqual(['t2', 't1'])
      expect(store.tasks.map(t => t.position)).toEqual([0, 1])
      expect(apiMock.updateTask).toHaveBeenCalledTimes(2)
    })

    it('顺序不变时不提交', async () => {
      const store = useTaskStore()
      store.tasks = [task('t1', 0), task('t2', 1)]

      await store.reorderTasks([task('t1', 0), task('t2', 1)], 'p1')

      expect(apiMock.updateTask).not.toHaveBeenCalled()
    })

    it('持久化失败回滚并抛出错误', async () => {
      apiMock.updateTask.mockRejectedValue(new Error('network'))
      const store = useTaskStore()
      store.tasks = [task('t1', 0), task('t2', 1)]

      await expect(
        store.reorderTasks([task('t2', 1), task('t1', 0)], 'p1')
      ).rejects.toThrow('排序保存失败')

      expect(store.tasks.map(t => t.key)).toEqual(['t1', 't2'])
    })
  })
})
