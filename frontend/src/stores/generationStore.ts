import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useApi } from '@/composables/useApi'
import { useAgentStore } from './agentStore'
import type { AgentMessage } from '@/types/agent'

export const useGenerationStore = defineStore('generation', () => {
  const api = useApi()
  const agentStore = useAgentStore()

  const isGenerating = ref(false)
  const currentStep = ref('')
  const finalProse = ref('')
  const generationHistory = ref<{ scene_id: string; prose: string; timestamp: number }[]>([])

  async function generateScene(projectId: string, sceneBrief: string, presentChars: string[]) {
    isGenerating.value = true
    currentStep.value = '准备中...'
    agentStore.clearMessages()

    try {
      const res = await api.generateScene({
        project_id: projectId,
        scene_brief: sceneBrief,
        present_character_names: presentChars,
        render_mode: 'text_only',
      })

      const data = res.data
      finalProse.value = data.final_prose

      // 将步骤转为消息
      for (const step of data.steps) {
        agentStore.addMessage({
          message_id: `msg_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
          agent_id: step.agent_name,
          agent_type: step.agent_type as any,
          agent_name: step.agent_name,
          content: step.content || `[${step.agent_name}] 完成`,
          timestamp: Date.now(),
          message_type: 'system',
        })
      }

      generationHistory.value.push({
        scene_id: data.scene_id,
        prose: data.final_prose,
        timestamp: Date.now(),
      })

    } finally {
      isGenerating.value = false
      currentStep.value = ''
    }
  }

  return {
    isGenerating, currentStep, finalProse, generationHistory,
    generateScene,
  }
})
