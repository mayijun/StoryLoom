import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useApi } from '@/composables/useApi'
import { useAgentStore } from './agentStore'
import type { AgentMessage } from '@/types/agent'

export const useGenerationStore = defineStore('generation', () => {
  const api = useApi()
  const agentStore = useAgentStore()

  const isGenerating = ref(false)
  /** 当前可见的进度文字，如「第 3 步 演员互动 · 30%」 */
  const currentStep = ref('')
  /** 当前步骤细分进度（0-100），供 UI 进度条使用 */
  const progress = ref(0)
  const finalProse = ref('')
  /** 主舞台当前编辑的场景；生成成功后自动指向新场景 */
  const currentSceneId = ref<string | null>(null)
  const generationHistory = ref<{ scene_id: string; prose: string; timestamp: number }[]>([])
  /** 后端任务 id；用于轮询 & 后续 cleanup */
  const taskId = ref<string | null>(null)

  /** 从后端 8 步 Flow 映射到更易读的中文提示 */
  const STEP_LABELS: Record<string, string> = {
    意外Agent: '意外事件提案',
    伏笔Agent: '伏笔状态整理',
    导演Agent: '导演意图包',
    RAG检索: '检索素材',
    角色互动: '角色互动推演',
    一致性检测: '一致性校验',
    润色叙事: '润色成稿',
    更新记忆: '记忆写回',
  }

  async function generateScene(
    projectId: string,
    sceneBrief: string,
    presentChars: string[],
    chapterId?: string,
  ) {
    isGenerating.value = true
    currentStep.value = '提交任务...'
    progress.value = 0
    currentSceneId.value = null
    finalProse.value = ''
    agentStore.clearMessages()

    let localTaskId: string | null = null

    try {
      // 1) 提交
      currentStep.value = '提交任务...'
      const submitRes = await api.submitSceneGenerate({
        project_id: projectId,
        scene_brief: sceneBrief,
        present_character_names: presentChars,
        render_mode: 'text_only',
        chapter_id: chapterId || null,
      })
      localTaskId = submitRes.data.task_id
      taskId.value = localTaskId
      currentStep.value = '已提交，等待开始...'

      // 2) 轮询：每 1.5s 一次，最长 12 分钟（后端 CrewAI 8 步串行）
      const startedAt = Date.now()
      const POLL_INTERVAL_MS = 1500
      const POLL_TIMEOUT_MS = 12 * 60 * 1000
      let lastProgress = -1

      while (true) {
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS))

        const elapsed = Date.now() - startedAt
        if (elapsed > POLL_TIMEOUT_MS) {
          throw new Error('生成超时（12 分钟），任务可能仍在后台运行')
        }

        let res
        try {
          res = await api.getGenerateTask(localTaskId)
        } catch (e: any) {
          // 任务过期（404）或网络抖动：再等一轮
          if (e?.response?.status === 404) {
            currentStep.value = '后端任务已过期，结果可能已丢失'
            throw new Error('后端任务已过期，请重新生成')
          }
          currentStep.value = `轮询异常，重试中 (${(e as Error).message})`
          continue
        }

        const rec = res.data
        const newProgress = rec.progress ?? 0
        if (newProgress !== lastProgress) {
          progress.value = newProgress
          lastProgress = newProgress
        }
        if (rec.step) {
          const label = STEP_LABELS[rec.step] ?? rec.step
          currentStep.value = rec.status === 'running' ? `${label} · ${newProgress}%` : label
        }

        if (rec.status === 'done') {
          break
        }
        if (rec.status === 'failed') {
          throw new Error(rec.error || '生成失败（后端报错）')
        }
        // pending / running：继续
      }

      // 3) 处理结果
      const result = (await api.getGenerateTask(localTaskId)).data.result
      if (!result) {
        throw new Error('任务已完成但结果为空')
      }

      finalProse.value = result.final_prose ?? ''
      currentSceneId.value = result.scene_id ?? null

      // 把步骤转成 agentStore 里的 system 消息（保持 UI 右侧"剧组流水"一致）
      for (const step of result.steps ?? []) {
        agentStore.addMessage({
          message_id: `msg_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
          agent_id: step.agent_name,
          agent_type: (step.agent_type as any) ?? 'system',
          agent_name: step.agent_name,
          content: step.content || `[${step.agent_name}] 完成`,
          timestamp: Date.now(),
          message_type: 'system',
        })
      }

      generationHistory.value.push({
        scene_id: result.scene_id,
        prose: result.final_prose,
        timestamp: Date.now(),
      })

      // 4) 清理任务记录（可失败，不影响主流程）
      try {
        await api.deleteGenerateTask(localTaskId)
      } catch {
        /* 清理失败忽略，后端 TTL 自动回收 */
      }
    } finally {
      isGenerating.value = false
      currentStep.value = ''
      progress.value = 0
      taskId.value = null
    }
  }

  function setCurrentScene(sceneId: string | null) {
    currentSceneId.value = sceneId
  }

  /** 切换项目时清空写作态，避免上一项目残留 */
  function reset() {
    isGenerating.value = false
    currentStep.value = ''
    progress.value = 0
    finalProse.value = ''
    currentSceneId.value = null
    generationHistory.value = []
    taskId.value = null
  }

  return {
    isGenerating, currentStep, progress, finalProse, currentSceneId, generationHistory, taskId,
    generateScene, setCurrentScene, reset,
  }
})
