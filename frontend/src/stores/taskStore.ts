import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { TaskConfig, TaskConfigInput } from '@/types/task'
import { useApi } from '@/composables/useApi'

export const useTaskStore = defineStore('task', () => {
  const api = useApi()
  const tasks = ref<TaskConfig[]>([])

  const enabledTasks = computed(() => tasks.value.filter(t => t.enabled))

  async function fetchTasks() {
    const res = await api.listTasks()
    tasks.value = res.data.tasks
  }

  async function addTask(task: TaskConfigInput) {
    const res = await api.createTask(task)
    tasks.value.push(res.data)
  }

  async function removeTask(key: string) {
    await api.deleteTask(key)
    tasks.value = tasks.value.filter(t => t.key !== key)
  }

  async function updateTask(key: string, patch: Partial<TaskConfigInput>) {
    const res = await api.updateTask(key, patch)
    const idx = tasks.value.findIndex(t => t.key === key)
    if (idx >= 0) tasks.value[idx] = res.data
  }

  /** 拖拽排序：先本地更新，再按新顺序持久化 position */
  async function reorderTasks(list: TaskConfig[]) {
    const previous = tasks.value
    tasks.value = list.map((task, index) => ({ ...task, position: index }))
    try {
      const changes = list
        .map((task, index) => ({ key: task.key, index, old: task.position }))
        .filter(item => item.old !== item.index)
      await Promise.all(
        changes.map(item => api.updateTask(item.key, { position: item.index }))
      )
    } catch {
      tasks.value = previous
      throw new Error('排序保存失败')
    }
  }

  return { tasks, enabledTasks, fetchTasks, addTask, removeTask, updateTask, reorderTasks }
})
