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

  return { tasks, enabledTasks, fetchTasks, addTask, removeTask, updateTask }
})
