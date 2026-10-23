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

  return {
    characters, locations, foreshadowings,
    fetchAll, addCharacter, removeCharacter, addLocation, addForeshadowing,
  }
})
