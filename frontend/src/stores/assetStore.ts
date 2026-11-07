import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { CharacterAsset, LocationAsset, Foreshadowing } from '@/types/asset'
import { useApi } from '@/composables/useApi'

export const useAssetStore = defineStore('asset', () => {
  const api = useApi()
  const characters = ref<CharacterAsset[]>([])
  const locations = ref<LocationAsset[]>([])
  const foreshadowings = ref<Foreshadowing[]>([])

  async function fetchAll(projectId: string) {
    const [charRes, locRes, fsRes] = await Promise.all([
      api.listCharacters(projectId),
      api.listLocations(projectId),
      api.listForeshadowings(projectId),
    ])
    characters.value = charRes.data as any
    locations.value = locRes.data as any
    foreshadowings.value = fsRes.data as any
  }

  async function addCharacter(projectId: string, char: CharacterAsset) {
    await api.addCharacter(projectId, char)
    characters.value.push(char)
  }

  async function removeCharacter(projectId: string, name: string) {
    await api.deleteCharacter(projectId, name)
    characters.value = characters.value.filter(c => c.name !== name)
  }

  async function addLocation(projectId: string, loc: LocationAsset) {
    await api.addLocation(projectId, loc)
    locations.value.push(loc)
  }

  async function addForeshadowing(projectId: string, fs: any) {
    await api.addForeshadowing(projectId, fs)
    foreshadowings.value.push(fs)
  }

  /** 伏笔状态显式流转（激活/回收/颠覆等），失败时抛出后端错误信息 */
  async function transitionForeshadowing(projectId: string, fid: string, action: string) {
    const res = await api.transitionForeshadowing(projectId, fid, action)
    const updated = res.data as Foreshadowing
    const idx = foreshadowings.value.findIndex(f => f.foreshadow_id === fid)
    if (idx >= 0) foreshadowings.value[idx] = updated
  }

  return {
    characters, locations, foreshadowings,
    fetchAll, addCharacter, removeCharacter, addLocation, addForeshadowing,
    transitionForeshadowing,
  }
})
