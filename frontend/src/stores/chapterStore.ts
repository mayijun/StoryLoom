import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ChapterView, ChapterCreate, ChapterUpdate } from '@/types/chapter'
import { useApi } from '@/composables/useApi'

export const useChapterStore = defineStore('chapter', () => {
  const api = useApi()
  const chapters = ref<ChapterView[]>([])
  const loading = ref(false)

  async function fetchChapters(projectId: string) {
    loading.value = true
    try {
      const res = await api.listChapters(projectId)
      chapters.value = res.data
    } finally {
      loading.value = false
    }
  }

  async function addChapter(projectId: string, data: ChapterCreate) {
    const res = await api.createChapter(projectId, data)
    // 重新拉取以保证 position 正确排序
    await fetchChapters(projectId)
    return res.data
  }

  async function updateChapter(projectId: string, chapterId: string, patch: ChapterUpdate) {
    const res = await api.updateChapter(projectId, chapterId, patch)
    const idx = chapters.value.findIndex(c => c.chapter_id === chapterId)
    if (idx >= 0) chapters.value[idx] = res.data
    return res.data
  }

  async function removeChapter(projectId: string, chapterId: string) {
    await api.deleteChapter(projectId, chapterId)
    chapters.value = chapters.value.filter(c => c.chapter_id !== chapterId)
  }

  /** 拖拽排序：先本地更新，再按新顺序持久化 position */
  async function reorderChapters(projectId: string, list: ChapterView[]) {
    const previous = chapters.value
    chapters.value = list.map((ch, index) => ({ ...ch, position: index }))
    try {
      const changes = list
        .map((ch, index) => ({ key: ch.chapter_id, index, old: ch.position }))
        .filter(item => item.old !== item.index)
      await Promise.all(
        changes.map(item =>
          api.updateChapter(projectId, item.key, { position: item.index })
        )
      )
    } catch {
      chapters.value = previous
      throw new Error('章节排序保存失败')
    }
  }

  return {
    chapters, loading,
    fetchChapters, addChapter, updateChapter, removeChapter, reorderChapters,
  }
})
