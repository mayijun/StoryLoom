import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import type { ChapterView } from '@/types/chapter'
import type { SceneView } from '@/types/scene'

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listChapters: vi.fn(),
    createChapter: vi.fn(),
    updateChapter: vi.fn(),
    deleteChapter: vi.fn(),
    listScenes: vi.fn(),
    getScene: vi.fn(),
    updateScene: vi.fn(),
    assignSceneToChapter: vi.fn(),
    deleteScene: vi.fn(),
    regenerateScene: vi.fn(),
  },
}))

vi.mock('@/composables/useApi', () => ({ useApi: () => apiMock }))

import ChapterPanel from '@/components/ChapterPanel.vue'

const chapters: ChapterView[] = [
  { chapter_id: 'c1', project_id: 'p1', title: '初入江湖', outline: '主角离开村庄', position: 0, status: 'draft' },
  { chapter_id: 'c2', project_id: 'p1', title: '风云再起', outline: '', position: 1, status: 'writing' },
]

function scene(id: string, chapterId: string | null): SceneView {
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
  }
}

const scenes: SceneView[] = [scene('s1', 'c1'), scene('s2', 'c1'), scene('s3', null)]

async function mountPanel() {
  const wrapper = mount(ChapterPanel, {
    props: { projectId: 'p1' },
    global: { plugins: [createPinia()] },
  })
  await flushPromises()
  return wrapper
}

function buttonByText(wrapper: ReturnType<typeof mount>, text: string) {
  return wrapper.findAll('button').find(b => b.text().includes(text))!
}

describe('ChapterPanel', () => {
  beforeEach(() => {
    Object.values(apiMock).forEach(fn => fn.mockReset())
    // 每次返回深拷贝，避免用例间因 store 就地更新而互相污染
    apiMock.listChapters.mockImplementation(() =>
      Promise.resolve({ data: chapters.map(c => ({ ...c })) })
    )
    apiMock.listScenes.mockImplementation(() =>
      Promise.resolve({ data: scenes.map(s => ({ ...s })) })
    )
    apiMock.createChapter.mockResolvedValue({ data: { ...chapters[0] } })
    apiMock.deleteChapter.mockResolvedValue({})
    apiMock.assignSceneToChapter.mockResolvedValue({ data: scene('s3', 'c1') })
  })

  it('渲染章节标题与统计信息', async () => {
    const wrapper = await mountPanel()

    const text = wrapper.text()
    expect(text).toContain('第1章 初入江湖')
    expect(text).toContain('第2章 风云再起')
    expect(text).toContain('共 2 章 · 1 未归属')
    expect(wrapper.text()).toContain('主角离开村庄')
  })

  it('初始只显示未归属场景，展开章节后显示其下场景', async () => {
    const wrapper = await mountPanel()

    expect(wrapper.findAll('.scene-row')).toHaveLength(1)
    expect(wrapper.find('.unassigned-block').text()).toContain('未归属场景（1）')

    await wrapper.find('.expand-btn').trigger('click')

    expect(wrapper.findAll('.scene-row')).toHaveLength(3)
    expect(wrapper.text()).toContain('brief-s1')
  })

  it('新建章节：填标题后调用创建接口', async () => {
    const wrapper = await mountPanel()

    await buttonByText(wrapper, '新建').trigger('click')
    const dialog = wrapper.find('.dialog')
    expect(dialog.exists()).toBe(true)

    await dialog.find('input').setValue('新章节')
    const createBtn = dialog.findAll('button').find(b => b.text().includes('创建'))!
    await createBtn.trigger('click')
    await flushPromises()

    expect(apiMock.createChapter).toHaveBeenCalledWith('p1', {
      title: '新章节',
      outline: '',
      status: 'draft',
    })
  })

  it('标题为空时创建按钮禁用', async () => {
    const wrapper = await mountPanel()

    await buttonByText(wrapper, '新建').trigger('click')
    const dialog = wrapper.find('.dialog')
    const createBtn = dialog.findAll('button').find(b => b.text().includes('创建'))!

    expect(createBtn.attributes('disabled')).toBeDefined()
  })

  it('未归属场景选择章节后调用归属接口', async () => {
    const wrapper = await mountPanel()

    await wrapper.find('.assign-select').setValue('c1')
    await flushPromises()

    expect(apiMock.assignSceneToChapter).toHaveBeenCalledWith('p1', 's3', 'c1')
  })

  it('删除章节需确认，确认后调用删除接口', async () => {
    const wrapper = await mountPanel()

    await wrapper.find('.chapter-actions .btn-icon.danger').trigger('click')
    await flushPromises()

    const dialog = wrapper.find('.dialog')
    expect(dialog.text()).toContain('未归属')

    const delBtn = dialog.findAll('button').find(b => b.text().includes('删除'))!
    await delBtn.trigger('click')
    await flushPromises()

    expect(apiMock.deleteChapter).toHaveBeenCalledWith('p1', 'c1')
  })

  it('查看正文：只读展示，点击编辑后可保存', async () => {
    apiMock.updateScene.mockResolvedValue({ data: scene('s3', null) })
    const wrapper = await mountPanel()

    // 未归属场景第一个操作按钮为「正文」
    await buttonByText(wrapper, '正文').trigger('click')
    await flushPromises()

    const dialog = wrapper.find('.prose-dialog')
    const textarea = dialog.find('textarea')
    expect((textarea.element as HTMLTextAreaElement).value).toBe('prose-s3')
    expect(textarea.attributes('readonly')).toBeDefined()

    const editBtn = dialog.findAll('button').find(b => b.text() === '编辑')!
    await editBtn.trigger('click')
    await textarea.setValue('修改后的正文')

    const saveBtn = dialog.findAll('button').find(b => b.text() === '保存')!
    await saveBtn.trigger('click')
    await flushPromises()

    expect(apiMock.updateScene).toHaveBeenCalledWith('p1', 's3', { prose: '修改后的正文' })
  })

  it('删除场景需确认，确认后调用删除接口', async () => {
    const wrapper = await mountPanel()

    // 未归属场景的「删除」按钮
    const sceneDeleteBtn = wrapper
      .find('.unassigned-block')
      .findAll('button')
      .find(b => b.text().includes('删除'))!
    await sceneDeleteBtn.trigger('click')
    await flushPromises()

    const dialog = wrapper.find('.dialog')
    expect(dialog.text()).toContain('永久删除')

    const confirmBtn = dialog.findAll('button').find(b => b.text() === '删除')!
    await confirmBtn.trigger('click')
    await flushPromises()

    expect(apiMock.deleteScene).toHaveBeenCalledWith('p1', 's3')
  })
})
