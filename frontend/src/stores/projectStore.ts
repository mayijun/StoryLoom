import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ProjectView } from '@/types/project'
import { useApi } from '@/composables/useApi'

export const useProjectStore = defineStore('project', () => {
  const api = useApi()
  const projects = ref<ProjectView[]>([])
  const currentProjectId = ref<string | null>(null)
  const currentProject = ref<any>(null)
  const loading = ref(false)

  async function fetchProjects() {
    loading.value = true
    try {
      const res = await api.listProjects()
      projects.value = res.data.projects
    } finally {
      loading.value = false
    }
  }

  async function createProject(title: string, style: string) {
    const res = await api.createProject({ title, style, description: '' })
    projects.value.push(res.data)
    currentProjectId.value = res.data.project_id
    await fetchCurrentProject()
  }

  async function selectProject(id: string) {
    currentProjectId.value = id
    await fetchCurrentProject()
  }

  async function fetchCurrentProject() {
    if (!currentProjectId.value) return
    const res = await api.getProject(currentProjectId.value)
    currentProject.value = res.data
  }

  return {
    projects, currentProjectId, currentProject, loading,
    fetchProjects, createProject, selectProject, fetchCurrentProject,
  }
})
