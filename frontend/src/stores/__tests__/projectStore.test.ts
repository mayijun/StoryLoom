import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import type { ProjectView, TemplateView } from '@/types/project'

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listProjects: vi.fn(),
    listTemplates: vi.fn(),
    createProject: vi.fn(),
    applyTemplate: vi.fn(),
    getProject: vi.fn(),
  },
}))

vi.mock('@/composables/useApi', () => ({ useApi: () => apiMock }))

import { useProjectStore } from '@/stores/projectStore'

function project(id: string, title = id): ProjectView {
  return { project_id: id, title, style: '悬疑', description: '', scene_count: 0, character_count: 0, foreshadowing_count: 0 }
}

describe('projectStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    Object.values(apiMock).forEach(fn => fn.mockReset())
  })

  it('fetchProjects 拉取列表并在结束后重置 loading', async () => {
    apiMock.listProjects.mockResolvedValue({ data: { projects: [project('p1'), project('p2')] } })
    const store = useProjectStore()

    await store.fetchProjects()

    expect(apiMock.listProjects).toHaveBeenCalled()
    expect(store.projects.map(p => p.project_id)).toEqual(['p1', 'p2'])
    expect(store.loading).toBe(false)
  })

  it('fetchProjects 失败时抛出错误但仍重置 loading', async () => {
    apiMock.listProjects.mockRejectedValue(new Error('boom'))
    const store = useProjectStore()

    await expect(store.fetchProjects()).rejects.toThrow('boom')
    expect(store.loading).toBe(false)
  })

  it('fetchTemplates 拉取模板列表', async () => {
    const templates: TemplateView[] = [{ template_id: 't1', title: '模板', style: '', description: '' }]
    apiMock.listTemplates.mockResolvedValue({ data: { templates } })
    const store = useProjectStore()

    await store.fetchTemplates()

    expect(store.templates).toHaveLength(1)
  })

  it('createProject 写入列表并设为当前项目，随后拉取当前项目详情', async () => {
    apiMock.createProject.mockResolvedValue({ data: project('p2', '新项目') })
    apiMock.getProject.mockResolvedValue({ data: project('p2', '新项目') })
    const store = useProjectStore()

    await store.createProject('新项目', '悬疑')

    expect(apiMock.createProject).toHaveBeenCalledWith({ title: '新项目', style: '悬疑', description: '' })
    expect(store.projects).toHaveLength(1)
    expect(store.currentProjectId).toBe('p2')
    expect(apiMock.getProject).toHaveBeenCalledWith('p2')
    expect(store.currentProject?.project_id).toBe('p2')
  })

  it('applyTemplate 写入列表并设为当前项目', async () => {
    apiMock.applyTemplate.mockResolvedValue({ data: project('p3', '模板项目') })
    apiMock.getProject.mockResolvedValue({ data: project('p3', '模板项目') })
    const store = useProjectStore()

    await store.applyTemplate('t1', '模板项目')

    expect(apiMock.applyTemplate).toHaveBeenCalledWith('t1', '模板项目')
    expect(store.currentProjectId).toBe('p3')
  })

  it('selectProject 设置当前并拉取详情', async () => {
    apiMock.getProject.mockResolvedValue({ data: project('p1') })
    const store = useProjectStore()

    await store.selectProject('p1')

    expect(store.currentProjectId).toBe('p1')
    expect(apiMock.getProject).toHaveBeenCalledWith('p1')
  })

  it('fetchCurrentProject 在无当前项目时不发起请求', async () => {
    const store = useProjectStore()
    store.currentProjectId = null

    await store.fetchCurrentProject()

    expect(apiMock.getProject).not.toHaveBeenCalled()
  })
})
