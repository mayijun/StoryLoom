import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import type { ChapterView } from '@/types/chapter'

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listChapters: vi.fn(),
    createChapter: vi.fn(),
    updateChapter: vi.fn(),
    deleteChapter: vi.fn(),
  },
}))

vi.mock('@/composables/useApi', () => ({ useApi: () => apiMock }))

import { useChapterStore } from '@/stores/chapterStore'

function chapter(id: string, position: number, title = id): ChapterView {
  return { chapter_id: id, project_id: 'p1', title, outline: '', position, status: 'draft' }
}

describe('chapterStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    Object.values(apiMock).forEach(fn => fn.mockReset())
  })

  it('fetchChapters 拉取并写入列表，结束后重置 loading', async () => {
    apiMock.listChapters.mockResolvedValue({ data: [chapter('c1', 0), chapter('c2', 1)] })
    const store = useChapterStore()

    await store.fetchChapters('p1')

    expect(apiMock.listChapters).toHaveBeenCalledWith('p1')
    expect(store.chapters).toHaveLength(2)
    expect(store.chapters.map(c => c.chapter_id)).toEqual(['c1', 'c2'])
    expect(store.loading).toBe(false)
  })

  it('fetchChapters 失败时抛出错误但仍重置 loading', async () => {
    apiMock.listChapters.mockRejectedValue(new Error('boom'))
    const store = useChapterStore()

    await expect(store.fetchChapters('p1')).rejects.toThrow('boom')
    expect(store.loading).toBe(false)
  })

  it('addChapter 创建后重新拉取列表', async () => {
    apiMock.createChapter.mockResolvedValue({ data: chapter('c2', 1) })
    apiMock.listChapters.mockResolvedValue({ data: [chapter('c1', 0), chapter('c2', 1)] })
    const store = useChapterStore()

    const created = await store.addChapter('p1', { title: '第二章' })

    expect(apiMock.createChapter).toHaveBeenCalledWith('p1', { title: '第二章' })
    expect(apiMock.listChapters).toHaveBeenCalledWith('p1')
    expect(created.chapter_id).toBe('c2')
    expect(store.chapters).toHaveLength(2)
  })

  it('updateChapter 更新本地对应项且不影响其他章节', async () => {
    const updated = { ...chapter('c1', 0, '新标题') }
    apiMock.updateChapter.mockResolvedValue({ data: updated })
    const store = useChapterStore()
    store.chapters = [chapter('c1', 0), chapter('c2', 1)]

    await store.updateChapter('p1', 'c1', { title: '新标题' })

    expect(apiMock.updateChapter).toHaveBeenCalledWith('p1', 'c1', { title: '新标题' })
    expect(store.chapters[0].title).toBe('新标题')
    expect(store.chapters[1].title).toBe('c2')
  })

  it('removeChapter 调用接口并从本地列表移除', async () => {
    apiMock.deleteChapter.mockResolvedValue({})
    const store = useChapterStore()
    store.chapters = [chapter('c1', 0), chapter('c2', 1)]

    await store.removeChapter('p1', 'c1')

    expect(apiMock.deleteChapter).toHaveBeenCalledWith('p1', 'c1')
    expect(store.chapters.map(c => c.chapter_id)).toEqual(['c2'])
  })

  describe('reorderChapters', () => {
    it('本地重排并按新顺序持久化 position', async () => {
      apiMock.updateChapter.mockResolvedValue({ data: {} })
      const store = useChapterStore()
      const c1 = chapter('c1', 0)
      const c2 = chapter('c2', 1)
      const c3 = chapter('c3', 2)
      store.chapters = [c1, c2, c3]

      await store.reorderChapters('p1', [c3, c1, c2])

      expect(store.chapters.map(c => c.chapter_id)).toEqual(['c3', 'c1', 'c2'])
      expect(store.chapters.map(c => c.position)).toEqual([0, 1, 2])
      expect(apiMock.updateChapter).toHaveBeenCalledTimes(3)
      expect(apiMock.updateChapter).toHaveBeenCalledWith('p1', 'c3', { position: 0 })
    })

    it('顺序未变化时不提交任何更新', async () => {
      const store = useChapterStore()
      store.chapters = [chapter('c1', 0), chapter('c2', 1)]

      await store.reorderChapters('p1', [chapter('c1', 0), chapter('c2', 1)])

      expect(apiMock.updateChapter).not.toHaveBeenCalled()
    })

    it('持久化失败时回滚本地顺序并抛出错误', async () => {
      apiMock.updateChapter.mockRejectedValue(new Error('network'))
      const store = useChapterStore()
      store.chapters = [chapter('c1', 0), chapter('c2', 1)]

      await expect(
        store.reorderChapters('p1', [chapter('c2', 1), chapter('c1', 0)])
      ).rejects.toThrow('章节排序保存失败')

      expect(store.chapters.map(c => c.chapter_id)).toEqual(['c1', 'c2'])
    })
  })
})
