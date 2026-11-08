import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { SceneView } from '@/types/scene'
import { useApi } from '@/composables/useApi'

export const useSceneStore = defineStore('scene', () => {
  const api = useApi()
  const scenes = ref<SceneView[]>([])
  const loading = ref(false)

  /** 一次性拉取项目全部场景，前端按 chapter_id 分组 */
  async function fetchScenes(projectId: string) {
    loading.value = true
    try {
      const res = await api.listScenes(projectId)
      scenes.value = res.data as any
    } finally {
      loading.value = false
    }
  }

  const scenesByChapter = (chapterId: string) =>
    computed(() => scenes.value.filter(s => s.chapter_id === chapterId))

  const unassignedScenes = computed(() =>
    scenes.value.filter(s => s.chapter_id === null)
  )

  const sceneCountByChapter = computed(() => {
    const counts: Record<string, number> = {}
    for (const s of scenes.value) {
      if (s.chapter_id) counts[s.chapter_id] = (counts[s.chapter_id] || 0) + 1
    }
    return counts
  })

  async function assignScene(projectId: string, sceneId: string, chapterId: string | null) {
    const res = await api.assignSceneToChapter(projectId, sceneId, chapterId)
    const updated = res.data as SceneView
    const idx = scenes.value.findIndex(s => s.scene_id === sceneId)
    if (idx >= 0) scenes.value[idx] = updated
    return updated
  }

  function unassignScene(projectId: string, sceneId: string) {
    return assignScene(projectId, sceneId, null)
  }

  async function updateSceneProse(projectId: string, sceneId: string, prose: string) {
    const res = await api.updateScene(projectId, sceneId, { prose })
    const updated = res.data as SceneView
    const idx = scenes.value.findIndex(s => s.scene_id === sceneId)
    if (idx >= 0) scenes.value[idx] = updated
    return updated
  }

  async function regenerateScene(projectId: string, sceneId: string) {
    const res = await api.regenerateScene(projectId, sceneId)
    // regenerate 返回的是 GenerateSceneResponse，从中取 scene 更新
    const data = (res.data as any)
    const sceneIdActual = data.scene_id || sceneId
    // 重新拉取该场景确保数据最新
    const sceneRes = await api.getScene(projectId, sceneIdActual)
    const idx = scenes.value.findIndex(s => s.scene_id === sceneIdActual)
    if (idx >= 0) {
      scenes.value[idx] = sceneRes.data as SceneView
    } else {
      scenes.value.push(sceneRes.data as SceneView)
    }
    return sceneRes.data as SceneView
  }

  async function removeScene(projectId: string, sceneId: string) {
    await api.deleteScene(projectId, sceneId)
    scenes.value = scenes.value.filter(s => s.scene_id !== sceneId)
  }

  return {
    scenes, loading,
    fetchScenes, scenesByChapter, unassignedScenes, sceneCountByChapter,
    assignScene, unassignScene, updateSceneProse, regenerateScene, removeScene,
  }
})
