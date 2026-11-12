<script setup lang="ts">
import { ref, computed, onMounted, provide, onBeforeUnmount } from 'vue'
import { useProjectStore } from './stores/projectStore'
import { useAgentStore } from './stores/agentStore'
import { useAssetStore } from './stores/assetStore'
import { useGenerationStore } from './stores/generationStore'
import { useTaskStore } from './stores/taskStore'
import { useChapterStore } from './stores/chapterStore'
import { useSceneStore } from './stores/sceneStore'
import { useApi } from './composables/useApi'
import GamePanel from './components/GamePanel.vue'
import ChapterPanel from './components/ChapterPanel.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'

import type { AgentConfig, AgentConfigInput, AgentMessage, AgentType } from './types/agent'
import type { TaskConfig, TaskConfigInput } from './types/task'
import type { CharacterAsset } from './types/asset'
import type { SceneView } from './types/scene'
import { AGENT_TYPE_META } from './types/agent'
import { FORESHADOW_STATUS_META } from './types/asset'

const api = useApi()
const projectStore = useProjectStore()
const agentStore = useAgentStore()
const assetStore = useAssetStore()
const genStore = useGenerationStore()
const taskStore = useTaskStore()
const chapterStore = useChapterStore()
const sceneStore = useSceneStore()

// ---- 状态 ----
const serverOnline = ref(false)
const activeTab = ref<'chapters' | 'crew'>('chapters')
const rightTab = ref<'characters' | 'locations' | 'foreshadowings' | 'metrics'>('characters')

// ---- 侧边栏宽度与折叠 ----
const SIDE_MIN = 48 // 折叠后的窄条宽度
const LEFT_MIN = 200
const LEFT_MAX = 800
const RIGHT_MIN = 180
const RIGHT_MAX = 600
const leftWidth = ref(280)
const rightWidth = ref(320)
const leftCollapsed = ref(false)
const rightCollapsed = ref(false)
const leftWideBase = ref(560) // layout-wide 时左栏默认宽度

const effectiveLeftWidth = computed(() =>
  leftCollapsed.value ? SIDE_MIN : (activeTab.value === 'chapters' || activeTab.value === 'crew' ? leftWideBase.value : leftWidth.value)
)
const effectiveRightWidth = computed(() =>
  rightCollapsed.value ? SIDE_MIN : rightWidth.value
)

// 把宽度应用到 grid
const layoutStyle = computed(() => ({
  '--left-width': effectiveLeftWidth.value + 'px',
  '--right-width': effectiveRightWidth.value + 'px',
}))

// 从 localStorage 恢复宽度
onMounted(() => {
  try {
    const saved = localStorage.getItem('storyloom.layout')
    if (saved) {
      const d = JSON.parse(saved)
      if (typeof d.leftWidth === 'number') leftWidth.value = d.leftWidth
      if (typeof d.rightWidth === 'number') rightWidth.value = d.rightWidth
      if (typeof d.leftWideBase === 'number') leftWideBase.value = d.leftWideBase
      if (d.leftCollapsed) leftCollapsed.value = true
      if (d.rightCollapsed) rightCollapsed.value = true
    }
  } catch { /* ignore */ }
})

function persistLayout() {
  try {
    localStorage.setItem('storyloom.layout', JSON.stringify({
      leftWidth: leftWidth.value,
      rightWidth: rightWidth.value,
      leftWideBase: leftWideBase.value,
      leftCollapsed: leftCollapsed.value,
      rightCollapsed: rightCollapsed.value,
    }))
  } catch { /* ignore */ }
}

// ---- 拖拽调整 ----
let dragSide: 'left' | 'right' | null = null
let dragStartX = 0
let dragStartWidth = 0

function onResizeStart(side: 'left' | 'right', e: MouseEvent) {
  e.preventDefault()
  dragSide = side
  dragStartX = e.clientX
  dragStartWidth = side === 'left'
    ? (activeTab.value === 'chapters' || activeTab.value === 'crew' ? leftWideBase.value : leftWidth.value)
    : rightWidth.value
  window.addEventListener('mousemove', onResizeMove)
  window.addEventListener('mouseup', onResizeEnd)
  document.body.style.cursor = side === 'left' ? 'col-resize' : 'col-resize'
  document.body.style.userSelect = 'none'
}

function onResizeMove(e: MouseEvent) {
  if (!dragSide) return
  const dx = e.clientX - dragStartX
  if (dragSide === 'left') {
    // 拖拽左 handle：handle 在 aside-left 右边，向右拖增加左栏宽度
    let w = dragStartWidth + dx
    if (activeTab.value === 'chapters' || activeTab.value === 'crew') {
      w = Math.max(LEFT_MIN, Math.min(LEFT_MAX, w))
      leftWideBase.value = w
    } else {
      w = Math.max(LEFT_MIN, Math.min(LEFT_MAX, w))
      leftWidth.value = w
    }
    leftCollapsed.value = false
  } else {
    // 拖拽右 handle：handle 在 aside-right 左边，向左拖增加右栏宽度
    let w = dragStartWidth - dx
    w = Math.max(RIGHT_MIN, Math.min(RIGHT_MAX, w))
    rightWidth.value = w
    rightCollapsed.value = false
  }
}

function onResizeEnd() {
  dragSide = null
  window.removeEventListener('mousemove', onResizeMove)
  window.removeEventListener('mouseup', onResizeEnd)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  persistLayout()
}

function toggleLeftCollapse() {
  leftCollapsed.value = !leftCollapsed.value
  persistLayout()
}
function toggleRightCollapse() {
  rightCollapsed.value = !rightCollapsed.value
  persistLayout()
}

onBeforeUnmount(() => {
  window.removeEventListener('mousemove', onResizeMove)
  window.removeEventListener('mouseup', onResizeEnd)
})
const sceneBrief = ref('')
const selectedChars = ref<string[]>([])

// ---- 写作工作台（主舞台）----
type SaveState = 'idle' | 'unsaved' | 'saving' | 'saved' | 'error'
const SAVE_STATE_LABEL: Record<SaveState, string> = {
  idle: '',
  unsaved: '未保存',
  saving: '保存中…',
  saved: '已保存',
  error: '保存失败',
}
const targetChapterId = ref('') // '' 表示不归属
const editorSceneId = ref<string | null>(null)
const editorProse = ref('')
const lastSavedProse = ref('')
const saveState = ref<SaveState>('idle')
const showProcess = ref(false)
let saveTimer: number | undefined

const currentScene = computed<SceneView | null>(() =>
  editorSceneId.value
    ? sceneStore.scenes.find(s => s.scene_id === editorSceneId.value) ?? null
    : null,
)

const wordCount = computed(() => editorProse.value.replace(/\s/g, '').length)

const currentSceneMeta = computed(() => {
  const s = currentScene.value
  if (!s) return ''
  const ch = s.chapter_id
    ? chapterStore.chapters.find(c => c.chapter_id === s.chapter_id)
    : null
  const parts = [ch ? ch.title : '未归属']
  if (s.created_at) {
    const d = new Date(s.created_at)
    if (!Number.isNaN(d.getTime())) parts.push(d.toLocaleString())
  }
  return parts.join(' · ')
})

const canGenerate = computed(
  () => !genStore.isGenerating && !!sceneBrief.value.trim() && selectedChars.value.length > 0,
)

/** 生成按钮不可用时说明原因，而不是只变灰 */
const generationHint = computed(() => {
  if (genStore.isGenerating) return ''
  if (assetStore.characters.length === 0) return '请先在右侧「角色」中添加角色'
  if (!sceneBrief.value.trim()) return '请先填写场景 brief'
  if (selectedChars.value.length === 0) return '请选择至少一位在场角色'
  return ''
})

/** 统一确认弹窗 */
const confirmState = ref<{
  title: string
  message: string
  confirmText: string
  onConfirm: () => void | Promise<void>
} | null>(null)

function askConfirm(opts: {
  title: string
  message: string
  confirmText?: string
  onConfirm: () => void | Promise<void>
}) {
  confirmState.value = { confirmText: '确定', ...opts }
}

async function runConfirm() {
  const action = confirmState.value?.onConfirm
  confirmState.value = null
  await action?.()
}

function resetWritingState() {
  if (saveTimer) {
    window.clearTimeout(saveTimer)
    saveTimer = undefined
  }
  sceneBrief.value = ''
  selectedChars.value = []
  targetChapterId.value = ''
  editorSceneId.value = null
  editorProse.value = ''
  lastSavedProse.value = ''
  saveState.value = 'idle'
  showProcess.value = false
  genStore.reset()
  agentStore.clearMessages()
}

function setEditorScene(scene: SceneView | null) {
  if (saveTimer) {
    window.clearTimeout(saveTimer)
    saveTimer = undefined
  }
  editorSceneId.value = scene?.scene_id ?? null
  editorProse.value = scene?.prose ?? ''
  lastSavedProse.value = scene?.prose ?? ''
  saveState.value = scene ? 'saved' : 'idle'
  if (scene) targetChapterId.value = scene.chapter_id ?? ''
  genStore.setCurrentScene(scene?.scene_id ?? null)
}

async function saveProseNow() {
  if (!editorSceneId.value) return
  if (editorProse.value === lastSavedProse.value) {
    if (saveState.value === 'unsaved') saveState.value = 'saved'
    return
  }
  const pid = projectStore.currentProjectId
  if (!pid) return
  saveState.value = 'saving'
  try {
    await sceneStore.updateSceneProse(pid, editorSceneId.value, editorProse.value)
    lastSavedProse.value = editorProse.value
    saveState.value = 'saved'
  } catch {
    saveState.value = 'error'
  }
}

/** 输入后 800ms 防抖保存 */
function handleProseInput() {
  saveState.value = 'unsaved'
  if (saveTimer) window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(() => {
    saveTimer = undefined
    void saveProseNow()
  }, 800)
}

async function flushSave() {
  if (saveTimer) {
    window.clearTimeout(saveTimer)
    saveTimer = undefined
  }
  await saveProseNow()
}

async function loadWritingData(pid: string) {
  await Promise.all([chapterStore.fetchChapters(pid), sceneStore.fetchScenes(pid)])
}

function sceneLabel(s: SceneView) {
  const ch = s.chapter_id
    ? chapterStore.chapters.find(c => c.chapter_id === s.chapter_id)
    : null
  const brief = (s.brief || '无 brief').replace(/\s+/g, ' ').slice(0, 18)
  return `${ch ? ch.title : '未归属'} · ${brief}`
}

async function handleSceneSwitch(sceneId: string) {
  await flushSave()
  if (!sceneId) {
    setEditorScene(null)
    return
  }
  const scene = sceneStore.scenes.find(s => s.scene_id === sceneId)
  if (scene) setEditorScene(scene)
}

async function handleSelectSceneFromPanel(sceneId: string) {
  await flushSave()
  const scene = sceneStore.scenes.find(s => s.scene_id === sceneId)
  if (scene) setEditorScene(scene)
}

/** 目标章节变化：有当前场景时同步移动归属 */
async function handleTargetChapterChange() {
  const pid = projectStore.currentProjectId
  if (!pid || !editorSceneId.value) return
  const updated = await sceneStore.assignScene(
    pid,
    editorSceneId.value,
    targetChapterId.value || null,
  )
  if (updated) setEditorScene(updated)
}

function handleHintClick() {
  if (assetStore.characters.length === 0) switchRightTab('characters')
}

// 对话框状态
const showCreateProject = ref(false)
const showCreateAgent = ref(false)
const showCreateCharacter = ref(false)
const showCreateLocation = ref(false)
const showGame = ref(false)
// 首次打开后游戏面板常驻，切换导演模式只隐藏不卸载，避免对话记录丢失
const gameMounted = ref(false)
// 从游戏面板切回导演模式时的一次性提示
const gameNotice = ref('')
let gameNoticeTimer: number | undefined

function openGame() {
  gameMounted.value = true
  showGame.value = true
  gameNotice.value = ''
}

function handleGameClose(notice?: string) {
  showGame.value = false
  if (!notice) return
  gameNotice.value = notice
  window.clearTimeout(gameNoticeTimer)
  gameNoticeTimer = window.setTimeout(() => {
    gameNotice.value = ''
  }, 3000)
}

// 配置编辑：null 表示新建
const editingAgentKey = ref<string | null>(null)
const editingTaskKey = ref<string | null>(null)
const showTaskDialog = ref(false)

// 表单数据
const newProject = ref({ title: '', style: '' })
// 新建项目对话框里选中的试用模板：'' 表示空白项目
const selectedTemplateId = ref('')
const agentForm = ref<AgentConfigInput>({
  key: '',
  role: '',
  goal: '',
  backstory: '',
  enabled: true,
})
const taskForm = ref<TaskConfigInput>({
  key: '',
  description: '',
  expected_output: '',
  agent_key: null,
  context_keys: [],
  enabled: true,
})
const newChar = ref<Partial<CharacterAsset>>({
  name: '', importance_tier: 'primary', persona: '', motivation: '', secrets: '',
})
const newLoc = ref({ name: '', description: '' })

// ---- 生命周期 ----
// Agent / Task 配置从属于小说项目；未选项目时使用内置 demo 示例项目
const currentProjectId = computed(() => projectStore.currentProjectId ?? 'demo')

onMounted(async () => {
  try {
    await api.checkHealth()
    serverOnline.value = true
    await projectStore.fetchProjects()
    await projectStore.fetchTemplates()
    await agentStore.fetchAgents(currentProjectId.value)
    await taskStore.fetchTasks(currentProjectId.value)
    if (projectStore.currentProjectId) {
      await loadWritingData(projectStore.currentProjectId)
    }
  } catch {
    serverOnline.value = false
  }
})

// ---- 方法 ----
async function handleCreateProject() {
  if (selectedTemplateId.value) {
    await projectStore.applyTemplate(selectedTemplateId.value, newProject.value.title || undefined)
  } else {
    await projectStore.createProject(newProject.value.title, newProject.value.style)
  }
  showCreateProject.value = false
  newProject.value = { title: '', style: '' }
  selectedTemplateId.value = ''
  if (projectStore.currentProjectId) {
    await flushSave()
    resetWritingState()
    await Promise.all([
      assetStore.fetchAll(projectStore.currentProjectId),
      loadWritingData(projectStore.currentProjectId),
    ])
  }
}

function openCreateProject() {
  newProject.value = { title: '', style: '' }
  selectedTemplateId.value = ''
  showCreateProject.value = true
}

function onSelectTemplate(tid: string) {
  selectedTemplateId.value = tid
  if (tid) {
    const tpl = projectStore.templates.find(t => t.template_id === tid)
    if (tpl) {
      newProject.value.title = tpl.title
      newProject.value.style = tpl.style
    }
  } else {
    newProject.value = { title: '', style: '' }
  }
}

async function handleSelectProject(id: string) {
  if (!id || id === projectStore.currentProjectId) return
  // 先保存当前场景，再切换，避免丢失编辑
  await flushSave()
  resetWritingState()
  await projectStore.selectProject(id)
  await assetStore.fetchAll(id)
  // 切换项目后，Agent / Task 配置也要切换到该项目自己的
  await agentStore.fetchAgents(currentProjectId.value)
  await taskStore.fetchTasks(currentProjectId.value)
  await loadWritingData(id)
}

function handleRemoveAgent(key: string, role: string) {
  askConfirm({
    title: '删除 Agent',
    message: `确定删除「${role}」（${key}）？删除后无法恢复。`,
    confirmText: '删除',
    onConfirm: () => agentStore.removeAgent(key, currentProjectId.value),
  })
}

function handleRemoveTask(key: string) {
  askConfirm({
    title: '删除 Task',
    message: `确定删除 Task「${key}」？删除后无法恢复。`,
    confirmText: '删除',
    onConfirm: () => taskStore.removeTask(key, currentProjectId.value),
  })
}

function openCreateAgent() {
  editingAgentKey.value = null
  agentForm.value = { key: '', role: '', goal: '', backstory: '', enabled: true }
  showCreateAgent.value = true
}

function openEditAgent(agent: AgentConfig) {
  editingAgentKey.value = agent.key
  agentForm.value = {
    key: agent.key,
    role: agent.role,
    goal: agent.goal,
    backstory: agent.backstory,
    enabled: agent.enabled,
  }
  showCreateAgent.value = true
}

async function handleSaveAgent() {
  if (editingAgentKey.value) {
    const { key, ...patch } = agentForm.value
    await agentStore.updateAgent(editingAgentKey.value, patch, currentProjectId.value)
  } else {
    await agentStore.addAgent({ ...agentForm.value }, currentProjectId.value)
  }
  showCreateAgent.value = false
}

function openCreateTask() {
  editingTaskKey.value = null
  taskForm.value = {
    key: '',
    description: '',
    expected_output: '',
    agent_key: null,
    context_keys: [],
    enabled: true,
  }
  showTaskDialog.value = true
}

function openEditTask(task: TaskConfig) {
  editingTaskKey.value = task.key
  taskForm.value = {
    key: task.key,
    description: task.description,
    expected_output: task.expected_output,
    agent_key: task.agent_key ?? null,
    context_keys: [...task.context_keys],
    enabled: task.enabled,
  }
  showTaskDialog.value = true
}

async function handleSaveTask() {
  if (editingTaskKey.value) {
    const { key, ...patch } = taskForm.value
    await taskStore.updateTask(editingTaskKey.value, patch, currentProjectId.value)
  } else {
    await taskStore.addTask({ ...taskForm.value }, currentProjectId.value)
  }
  showTaskDialog.value = false
}

// ---- 拖拽排序 ----
const dragAgentIndex = ref<number | null>(null)
const dragTaskIndex = ref<number | null>(null)

async function handleAgentDrop(to: number) {
  const from = dragAgentIndex.value
  dragAgentIndex.value = null
  if (from === null || from === to) return
  const list = [...agentStore.agents]
  const [moved] = list.splice(from, 1)
  list.splice(to, 0, moved)
  await agentStore.reorderAgents(list, currentProjectId.value)
}

async function handleTaskDrop(to: number) {
  const from = dragTaskIndex.value
  dragTaskIndex.value = null
  if (from === null || from === to) return
  const list = [...taskStore.tasks]
  const [moved] = list.splice(from, 1)
  list.splice(to, 0, moved)
  await taskStore.reorderTasks(list, currentProjectId.value)
}

async function handleCreateCharacter() {
  if (!projectStore.currentProjectId) return
  await assetStore.addCharacter(projectStore.currentProjectId, newChar.value as CharacterAsset)
  showCreateCharacter.value = false
  newChar.value = { name: '', importance_tier: 'primary', persona: '', motivation: '', secrets: '' }
}

async function handleCreateLocation() {
  if (!projectStore.currentProjectId) return
  await assetStore.addLocation(projectStore.currentProjectId, newLoc.value as any)
  showCreateLocation.value = false
  newLoc.value = { name: '', description: '' }
}

function toggleCharSelection(name: string) {
  const idx = selectedChars.value.indexOf(name)
  if (idx >= 0) selectedChars.value.splice(idx, 1)
  else selectedChars.value.push(name)
}

async function handleGenerate() {
  if (!projectStore.currentProjectId || !canGenerate.value) return
  const pid = projectStore.currentProjectId

  // 后端会根据选中的章节自动归属（GenerateSceneRequest.chapter_id），
  // 不再需要生成后再单独 assignScene。这里仍把 targetChapterId 传透，
  // 让后端 scene 落库时 chapter_id 直接正确。
  await genStore.generateScene(
    pid,
    sceneBrief.value,
    selectedChars.value,
    targetChapterId.value || undefined,
  )

  const sid = genStore.currentSceneId
  if (!sid) return

  // 刷新场景列表，让新场景进入章节树 / 未归属区
  await sceneStore.fetchScenes(pid)

  // 理论上后端已自动归属，这里再 assign 一次做幂等 fallback
  // （兼容旧后端 / 直接调 API 生成的场景）
  if (targetChapterId.value) {
    try {
      await sceneStore.assignScene(pid, sid, targetChapterId.value)
    } catch {
      /* 已归属时 assign 可能报错，忽略 */
    }
  }

  const scene = sceneStore.scenes.find(s => s.scene_id === sid)
  if (scene) {
    setEditorScene(scene)
  } else {
    editorSceneId.value = sid
    editorProse.value = genStore.finalProse
    lastSavedProse.value = genStore.finalProse
    saveState.value = 'saved'
    genStore.setCurrentScene(sid)
  }
  showProcess.value = false
}

// ---- 小说导出（Markdown / TXT）----
function handleExportNovel(format: 'md' | 'txt') {
  if (!projectStore.currentProjectId) return
  window.open(api.exportNovelUrl(projectStore.currentProjectId, format), '_blank')
}

// ---- 成本与质量指标 ----
const metrics = ref<any | null>(null)
const metricsLoading = ref(false)

async function loadMetrics() {
  if (!projectStore.currentProjectId) return
  metricsLoading.value = true
  try {
    const res = await api.getMetrics(projectStore.currentProjectId)
    metrics.value = res.data
  } finally {
    metricsLoading.value = false
  }
}

function switchRightTab(tab: 'characters' | 'locations' | 'foreshadowings' | 'metrics') {
  rightTab.value = tab
  if (tab === 'metrics') loadMetrics()
}

function formatDuration(ms: number | null | undefined) {
  if (ms == null) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}

// ---- 伏笔状态流转 ----
const fsTransitionError = ref('')
const FS_ACTIONS: Record<string, { action: string; label: string }[]> = {
  planted: [
    { action: 'reinforce', label: '强化' },
    { action: 'activate', label: '激活' },
    { action: 'subvert', label: '颠覆' },
    { action: 'abandon', label: '废弃' },
  ],
  reinforced: [
    { action: 'activate', label: '激活' },
    { action: 'subvert', label: '颠覆' },
    { action: 'abandon', label: '废弃' },
  ],
  activated: [
    { action: 'resolve', label: '回收' },
    { action: 'subvert', label: '颠覆' },
  ],
  resolved: [{ action: 'replant', label: '重埋' }],
  subverted: [{ action: 'replant', label: '重埋' }],
  abandoned: [{ action: 'replant', label: '重埋' }],
}

async function handleFsTransition(fid: string, action: string) {
  if (!projectStore.currentProjectId) return
  fsTransitionError.value = ''
  try {
    await assetStore.transitionForeshadowing(projectStore.currentProjectId, fid, action)
  } catch (e: any) {
    fsTransitionError.value = e?.response?.data?.detail || '流转失败'
  }
}

// ---- Agent / Task 配置导入导出与跨项目复制 ----
const configMsg = ref('')
const configFileInput = ref<HTMLInputElement | null>(null)
const importMode = ref<'merge' | 'overwrite'>('merge')
const showCopyConfig = ref(false)
const copySourceId = ref('')

async function handleExportConfig() {
  if (!projectStore.currentProjectId) return
  const res = await api.exportConfig(projectStore.currentProjectId)
  const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `storyloom-config-${projectStore.currentProjectId}.json`
  a.click()
  URL.revokeObjectURL(a.href)
  configMsg.value = '配置已导出'
}

async function handleImportConfigFile(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  ;(e.target as HTMLInputElement).value = ''
  if (!file || !projectStore.currentProjectId) return
  try {
    const data = JSON.parse(await file.text())
    await api.importConfig(projectStore.currentProjectId, {
      agents: data.agents ?? [],
      tasks: data.tasks ?? [],
      mode: importMode.value,
    })
    await agentStore.fetchAgents(currentProjectId.value)
    await taskStore.fetchTasks(currentProjectId.value)
    configMsg.value = `导入成功（${importMode.value === 'merge' ? '合并' : '覆盖'}）`
  } catch (err: any) {
    configMsg.value = err?.response?.data?.detail || '导入失败：文件格式不正确'
  }
}

function handleCopyConfig() {
  if (!projectStore.currentProjectId || !copySourceId.value) return
  const source = copySourceId.value
  askConfirm({
    title: '覆盖当前配置',
    message: `将用项目「${source}」的 Agent / Task 配置覆盖当前项目，现有配置会被替换。确定继续？`,
    confirmText: '覆盖',
    onConfirm: doCopyConfig,
  })
}

async function doCopyConfig() {
  if (!projectStore.currentProjectId || !copySourceId.value) return
  try {
    await api.copyConfigFrom(projectStore.currentProjectId, copySourceId.value, 'overwrite')
    await agentStore.fetchAgents(currentProjectId.value)
    await taskStore.fetchTasks(currentProjectId.value)
    configMsg.value = `已从 ${copySourceId.value} 复制配置（覆盖）`
    showCopyConfig.value = false
    copySourceId.value = ''
  } catch (err: any) {
    configMsg.value = err?.response?.data?.detail || '复制失败'
  }
}
</script>

<template>
  <div
    class="app-layout"
    :class="{
      'layout-wide': activeTab === 'chapters' || activeTab === 'crew',
      'left-collapsed': leftCollapsed,
      'right-collapsed': rightCollapsed,
    }"
    :style="layoutStyle"
  >
    <!-- ==================== 顶栏 ==================== -->
    <header class="app-header">
      <h1>🧵 织章 StoryLoom</h1>

      <!-- 项目选择 -->
      <select
        v-if="projectStore.projects.length > 0"
        :value="projectStore.currentProjectId || ''"
        @change="handleSelectProject(($event.target as HTMLSelectElement).value)"
        style="background:var(--bg-input);color:var(--text-primary);border:1px solid var(--border);border-radius:6px;padding:6px 10px;font-size:13px;"
      >
        <option value="" disabled>选择项目...</option>
        <option v-for="p in projectStore.projects" :key="p.project_id" :value="p.project_id">
          {{ p.title }} ({{ p.scene_count }}场景)
        </option>
      </select>

      <button class="btn btn-secondary btn-sm" @click="openCreateProject">
        ＋ 新建项目
      </button>

      <!-- 小说导出 -->
      <template v-if="projectStore.currentProjectId">
        <button class="btn btn-secondary btn-sm" title="进入游戏 / 扮演模式" @click="openGame">
          🎮 游戏模式
        </button>
        <span v-if="gameNotice" style="font-size:12px;color:var(--accent);">{{ gameNotice }}</span>
        <button class="btn btn-secondary btn-sm" title="导出整本小说为 Markdown" @click="handleExportNovel('md')">
          📤 导出 MD
        </button>
        <button class="btn btn-secondary btn-sm" title="导出整本小说为纯文本" @click="handleExportNovel('txt')">
          📤 导出 TXT
        </button>
      </template>

      <div style="flex:1"></div>

      <!-- 服务器状态 -->
      <div style="display:flex;align-items:center;gap:6px;font-size:12px;">
        <div :style="{
          width:'8px',height:'8px',borderRadius:'50%',
          background: serverOnline ? 'var(--success)' : 'var(--error)'
        }"></div>
        {{ serverOnline ? 'API 在线' : 'API 离线' }}
      </div>
    </header>

    <!-- ==================== 左侧边栏：Agent管理 ==================== -->
    <aside class="sidebar-left">
      <!-- 标签切换 -->
      <div class="tabs">
        <div class="tab" :class="{ active: activeTab === 'chapters' }" @click="activeTab = 'chapters'">
          📚 章节
        </div>
        <div class="tab" :class="{ active: activeTab === 'crew' }" @click="activeTab = 'crew'">
          ⚙️ 剧组
        </div>
      </div>

      <!-- 章节面板 -->
      <template v-if="activeTab === 'chapters'">
        <ChapterPanel
          v-if="projectStore.currentProjectId"
          :project-id="currentProjectId"
          @select-scene="handleSelectSceneFromPanel"
          @select-chapter="targetChapterId = $event"
        />
        <div v-else style="text-align:center;color:var(--text-secondary);padding:40px 20px;font-size:13px;">
          请先选择或创建项目
        </div>
      </template>

      <!-- 剧组配置：Agent / Task 双栏 + Flow 占位 -->
      <template v-if="activeTab === 'crew'">
        <div class="config-columns">
          <!-- 左栏：Agents -->
          <div class="panel">
            <div class="panel-title">
              <span>🤖 Agents</span>
              <button class="btn btn-sm btn-primary" @click="openCreateAgent" style="margin-left:auto;">
                ＋ 添加
              </button>
            </div>

            <!-- 配置导入导出 / 跨项目复制工具栏 -->
            <div style="display:flex;gap:6px;align-items:center;padding:6px 8px;border-bottom:1px solid var(--border);font-size:12px;flex-wrap:wrap;">
              <button class="btn btn-sm btn-secondary" title="导出当前项目 Agent/Task 配置为 JSON" @click="handleExportConfig">
                📤 导出配置
              </button>
              <button class="btn btn-sm btn-secondary" title="从 JSON 文件导入配置" @click="configFileInput?.click()">
                📥 导入配置
              </button>
              <select v-model="importMode" title="导入模式"
                style="background:var(--bg-input);color:var(--text-primary);border:1px solid var(--border);border-radius:6px;padding:3px 6px;font-size:12px;">
                <option value="merge">合并</option>
                <option value="overwrite">覆盖</option>
              </select>
              <button class="btn btn-sm btn-secondary" title="从其他项目复制配置" @click="showCopyConfig = true">
                📋 从项目复制
              </button>
              <input ref="configFileInput" type="file" accept=".json,application/json" style="display:none" @change="handleImportConfigFile" />
              <span v-if="configMsg" style="color:var(--accent);">{{ configMsg }}</span>
            </div>

            <div
              v-for="(agent, idx) in agentStore.agents"
              :key="agent.key"
              class="agent-card"
              :class="{ disabled: !agent.enabled, dragging: dragAgentIndex === idx }"
              draggable="true"
              @dragstart="dragAgentIndex = idx"
              @dragend="dragAgentIndex = null"
              @dragover.prevent
              @drop.prevent="handleAgentDrop(idx)"
              @click="openEditAgent(agent)"
            >
              <div class="agent-icon">{{ AGENT_TYPE_META[agent.key as AgentType]?.icon || '⚙️' }}</div>
              <div class="agent-info">
                <div class="agent-name">{{ agent.role }}</div>
                <div class="agent-model">
                  {{ agent.key }}
                  <template v-if="!agent.enabled"> · 已停用</template>
                </div>
              </div>
              <div
                class="agent-status"
                :class="{
                  thinking: agentStore.runtimeStates.get(agent.key)?.status === 'thinking'
                }"
              ></div>
              <button
                class="btn btn-icon btn-sm"
                @click.stop="handleRemoveAgent(agent.key, agent.role)"
                title="删除"
                style="color:var(--error);background:transparent;border:none;"
              >✕</button>
            </div>

            <div v-if="agentStore.agents.length === 0" style="text-align:center;color:var(--text-secondary);padding:20px;font-size:13px;">
              暂无Agent，点击上方"添加"创建
            </div>
          </div>

          <!-- 右栏：Tasks -->
          <div class="panel">
            <div class="panel-title">
              <span>📝 Tasks</span>
              <button class="btn btn-sm btn-primary" @click="openCreateTask" style="margin-left:auto;">
                ＋ 添加
              </button>
            </div>

            <div
              v-for="(task, idx) in taskStore.tasks"
              :key="task.key"
              class="agent-card"
              :class="{ disabled: !task.enabled, dragging: dragTaskIndex === idx }"
              draggable="true"
              @dragstart="dragTaskIndex = idx"
              @dragend="dragTaskIndex = null"
              @dragover.prevent
              @drop.prevent="handleTaskDrop(idx)"
              @click="openEditTask(task)"
            >
              <div class="agent-icon">📝</div>
              <div class="agent-info">
                <div class="agent-name">{{ task.key }}</div>
                <div class="agent-model">
                  {{ task.agent_key || '未绑定 Agent' }} · {{ task.context_keys.length }} 上下文
                  <template v-if="!task.enabled"> · 已停用</template>
                </div>
              </div>
              <button
                class="btn btn-icon btn-sm"
                @click.stop="handleRemoveTask(task.key)"
                title="删除"
                style="color:var(--error);background:transparent;border:none;"
              >✕</button>
            </div>

            <div v-if="taskStore.tasks.length === 0" style="text-align:center;color:var(--text-secondary);padding:20px;font-size:13px;">
              暂无Task，点击上方"添加"创建
            </div>
          </div>
        </div>

        <!-- 预留Agent类型展示 -->
        <div class="panel" style="margin-top:12px;">
          <div class="panel-title">🔮 预留类型</div>
          <div
            v-for="(meta, type) in AGENT_TYPE_META"
            :key="type"
            v-show="!meta.implemented"
            class="agent-card disabled"
          >
            <div class="agent-icon">{{ meta.icon }}</div>
            <div class="agent-info">
              <div class="agent-name">{{ meta.label }}</div>
              <div class="agent-model">{{ meta.description }}</div>
            </div>
          </div>
        </div>

        <!-- Flow 可视化编辑器（占位，Phase 2 接入 Vue Flow） -->
        <div class="flow-editor-placeholder" style="margin-top:12px;">
          <div class="icon">🔗</div>
          <div class="title">Flow 可视化编辑器</div>
          <div class="desc">
            Phase 2 将接入 Vue Flow<br>
            支持拖曳式 Agent 工作流编排<br><br>
            <small style="color:var(--accent);">
              数据结构已预留，兼容 Vue Flow 节点/边格式
            </small>
          </div>
        </div>
      </template>
    </aside>

    <!-- 左侧 resize handle -->
    <div
      class="resize-handle resize-handle-left"
      @mousedown="(e: MouseEvent) => onResizeStart('left', e)"
      @dblclick="toggleLeftCollapse"
      :title="leftCollapsed ? '双击展开左栏' : '拖拽调整宽度 · 双击折叠'"
    >
      <button class="collapse-btn" @click="toggleLeftCollapse" :title="leftCollapsed ? '展开' : '折叠'">
        {{ leftCollapsed ? '»' : '«' }}
      </button>
    </div>

    <!-- ==================== 主内容区：写作工作台 ==================== -->
    <main class="main-content">
      <template v-if="projectStore.currentProjectId">
        <div class="scene-theater">
          <!-- 场景头：目标章节 / 当前场景 / 字数 / 保存状态 -->
          <div class="scene-header">
            <label class="scene-field">
              <span>目标章节</span>
              <select v-model="targetChapterId" @change="handleTargetChapterChange">
                <option value="">不归属</option>
                <option v-for="ch in chapterStore.chapters" :key="ch.chapter_id" :value="ch.chapter_id">
                  {{ ch.title }}
                </option>
              </select>
            </label>

            <label class="scene-field">
              <span>当前场景</span>
              <select
                :value="editorSceneId || ''"
                @change="handleSceneSwitch(($event.target as HTMLSelectElement).value)"
              >
                <option value="">未选择场景</option>
                <option v-for="s in sceneStore.scenes" :key="s.scene_id" :value="s.scene_id">
                  {{ sceneLabel(s) }}
                </option>
              </select>
            </label>

            <div class="scene-header-meta">
              <span v-if="currentSceneMeta">{{ currentSceneMeta }}</span>
              <span v-if="editorSceneId" class="word-count">{{ wordCount }} 字</span>
              <span
                v-if="editorSceneId && SAVE_STATE_LABEL[saveState]"
                class="save-status"
                :class="saveState"
              >{{ SAVE_STATE_LABEL[saveState] }}</span>
            </div>
          </div>

          <!-- 正文编辑区：生成后可直接编辑，失焦 / 防抖自动保存 -->
          <div class="prose-editor-area">
            <div v-if="!editorSceneId" class="editor-empty">
              <div style="font-size:48px;margin-bottom:12px;">🖋️</div>
              <div style="font-size:16px;margin-bottom:8px;">还没有正在编辑的场景</div>
              <div style="font-size:13px;">
                在左侧点击场景「正文」，或填写下方 brief 生成第一段
              </div>
            </div>
            <textarea
              v-else
              v-model="editorProse"
              class="prose-editor"
              placeholder="正文为空，可以直接开始写作…"
              @input="handleProseInput"
              @blur="flushSave"
            ></textarea>
          </div>

          <!-- 生成过程：默认折叠，与正文分区 -->
          <div v-if="agentStore.messages.length || genStore.isGenerating" class="process-panel">
            <button class="process-toggle" @click="showProcess = !showProcess">
              {{ showProcess ? '▾' : '▸' }} 生成过程（{{ agentStore.messages.length }} 步）
              <span v-if="genStore.isGenerating" style="color:var(--warning);">
                · {{ genStore.currentStep }} 生成中
              </span>
            </button>
            <div v-if="showProcess" class="process-messages">
              <div
                v-for="msg in agentStore.messages"
                :key="msg.message_id"
                class="message-bubble"
                :class="msg.message_type"
              >
                <div class="msg-header">
                  <span class="msg-agent-icon">{{ AGENT_TYPE_META[msg.agent_type]?.icon || '⚙️' }}</span>
                  <span class="msg-agent-name" :style="{ color: AGENT_TYPE_META[msg.agent_type]?.color }">
                    {{ msg.agent_name }}
                  </span>
                  <span style="font-size:11px;color:var(--text-secondary);margin-left:auto;">
                    {{ AGENT_TYPE_META[msg.agent_type]?.label }}
                  </span>
                </div>
                <div class="msg-content">{{ msg.content }}</div>
              </div>
              <div v-if="genStore.isGenerating" class="message-bubble system">
                <span class="loading-dots">{{ genStore.currentStep }} 生成中</span>
              </div>
            </div>
          </div>

          <!-- 在场角色选择 -->
          <div class="character-picker">
            <span style="font-size:12px;color:var(--text-secondary);line-height:28px;">在场角色：</span>
            <button
              v-for="char in assetStore.characters"
              :key="char.name"
              class="btn btn-sm"
              :class="selectedChars.includes(char.name) ? 'btn-primary' : 'btn-secondary'"
              @click="toggleCharSelection(char.name)"
            >
              {{ char.name }}
            </button>
            <span
              v-if="assetStore.characters.length === 0"
              style="font-size:12px;color:var(--warning);line-height:28px;"
            >还没有角色，请先在右侧添加</span>
          </div>

          <!-- 输入区 -->
          <div class="scene-input">
            <div class="brief-wrap">
              <textarea
                v-model="sceneBrief"
                placeholder="描述这个场景的大致内容..."
                @keydown.ctrl.enter="handleGenerate"
              ></textarea>
              <div
                v-if="generationHint"
                class="generation-hint"
                :class="{ clickable: assetStore.characters.length === 0 }"
                @click="handleHintClick"
              >{{ generationHint }}</div>
            </div>
            <button
              class="btn btn-primary"
              :disabled="!canGenerate"
              @click="handleGenerate"
              style="align-self:flex-end;min-width:80px;"
            >
              {{ genStore.isGenerating ? '生成中...' : '🎬 生成' }}
            </button>
          </div>
        </div>
      </template>

      <!-- 未选择项目 -->
      <template v-else>
        <div style="display:flex;align-items:center;justify-content:center;height:100%;flex-direction:column;gap:16px;">
          <div style="font-size:64px;">📚</div>
          <div style="font-size:18px;">请先选择或创建一个小说项目</div>
          <button class="btn btn-primary" @click="openCreateProject">
            ＋ 新建项目
          </button>
        </div>
      </template>
    </main>

    <!-- 右侧 resize handle -->
    <div
      class="resize-handle resize-handle-right"
      @mousedown="(e: MouseEvent) => onResizeStart('right', e)"
      @dblclick="toggleRightCollapse"
      :title="rightCollapsed ? '双击展开右栏' : '拖拽调整宽度 · 双击折叠'"
    >
      <button class="collapse-btn" @click="toggleRightCollapse" :title="rightCollapsed ? '展开' : '折叠'">
        {{ rightCollapsed ? '«' : '»' }}
      </button>
    </div>

    <!-- ==================== 右侧边栏：资产管理 ==================== -->
    <aside class="sidebar-right">
      <template v-if="projectStore.currentProjectId">
        <div class="tabs">
          <div
            class="tab"
            :class="{ active: rightTab === 'characters', attention: assetStore.characters.length === 0 }"
            @click="switchRightTab('characters')"
          >
            🎭 角色
          </div>
          <div class="tab" :class="{ active: rightTab === 'locations' }" @click="switchRightTab('locations')" aria-label="地点">
            📍 地点
          </div>
          <div class="tab" :class="{ active: rightTab === 'foreshadowings' }" @click="switchRightTab('foreshadowings')">
            📌 伏笔
          </div>
          <div class="tab" :class="{ active: rightTab === 'metrics' }" @click="switchRightTab('metrics')">
            📊 指标
          </div>
        </div>

        <!-- 角色列表 -->
        <template v-if="rightTab === 'characters'">
          <div class="panel">
            <div class="panel-title">
              角色资产
              <button class="btn btn-sm btn-secondary" @click="showCreateCharacter = true" style="margin-left:auto;">＋</button>
            </div>
            <div v-for="char in assetStore.characters" :key="char.name" class="character-card">
              <div>
                <span class="char-name">{{ char.name }}</span>
                <span class="char-tier" :class="char.importance_tier">{{ char.importance_tier }}</span>
              </div>
              <div class="char-persona">{{ char.persona }}</div>
              <div style="font-size:11px;color:var(--accent);margin-top:4px;">
                动机：{{ char.motivation }}
              </div>
            </div>
            <div v-if="assetStore.characters.length === 0" style="text-align:center;color:var(--text-secondary);padding:20px;font-size:13px;">
              暂无角色
            </div>
          </div>
        </template>

        <!-- 地点列表 -->
        <template v-if="rightTab === 'locations'">
          <div class="panel">
            <div class="panel-title">
              地点资产
              <button class="btn btn-sm btn-secondary" @click="showCreateLocation = true" style="margin-left:auto;">＋</button>
            </div>
            <div v-for="loc in assetStore.locations" :key="loc.name" class="character-card">
              <div class="char-name">📍 {{ loc.name }}</div>
              <div class="char-persona">{{ loc.description }}</div>
            </div>
            <div v-if="assetStore.locations.length === 0" style="text-align:center;color:var(--text-secondary);padding:20px;font-size:13px;">
              暂无地点
            </div>
          </div>
        </template>

        <!-- 伏笔追踪 -->
        <template v-if="rightTab === 'foreshadowings'">
          <div class="panel">
            <div class="panel-title">伏笔追踪器</div>
            <div
              v-for="fs in assetStore.foreshadowings"
              :key="fs.foreshadow_id"
              class="foreshadow-item"
              :class="{ urgent: fs.scenes_since_last_mention >= fs.max_dormant_scenes - 1 }"
              :style="{ borderLeftColor: FORESHADOW_STATUS_META[fs.status]?.color }"
            >
              <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
                <span>{{ FORESHADOW_STATUS_META[fs.status]?.emoji }}</span>
                <strong>{{ fs.description }}</strong>
              </div>
              <div style="color:var(--text-secondary);">
                状态: {{ FORESHADOW_STATUS_META[fs.status]?.label }}
                · 强化{{ fs.reinforcement_count }}次
                · 沉睡{{ fs.scenes_since_last_mention }}/{{ fs.max_dormant_scenes }}场景
              </div>
              <div style="margin-top:4px;color:var(--accent);">
                → {{ fs.target_revelation }}
              </div>
              <!-- 状态流转按钮 -->
              <div style="display:flex;gap:4px;margin-top:6px;flex-wrap:wrap;">
                <button
                  v-for="a in FS_ACTIONS[fs.status] || []"
                  :key="a.action"
                  class="btn btn-sm btn-secondary"
                  style="font-size:11px;padding:2px 8px;"
                  @click="handleFsTransition(fs.foreshadow_id, a.action)"
                >{{ a.label }}</button>
              </div>
            </div>
            <div v-if="fsTransitionError" style="color:var(--error);font-size:12px;padding:4px 8px;">
              {{ fsTransitionError }}
            </div>
            <div v-if="assetStore.foreshadowings.length === 0" style="text-align:center;color:var(--text-secondary);padding:20px;font-size:13px;">
              暂无伏笔
            </div>
          </div>
        </template>

        <!-- 成本与质量指标 -->
        <template v-if="rightTab === 'metrics'">
          <div class="panel">
            <div class="panel-title">
              📊 成本与质量
              <button class="btn btn-sm btn-secondary" style="margin-left:auto;" @click="loadMetrics" :disabled="metricsLoading">
                {{ metricsLoading ? '加载中…' : '↻ 刷新' }}
              </button>
            </div>
            <div v-if="metrics" style="padding:8px;font-size:13px;">
              <!-- 汇总 -->
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px;">
                <div class="character-card" style="text-align:center;">
                  <div style="font-size:20px;color:var(--accent);">{{ metrics.scene_count }}</div>
                  <div style="font-size:11px;color:var(--text-secondary);">场景数</div>
                </div>
                <div class="character-card" style="text-align:center;">
                  <div style="font-size:20px;color:var(--accent);">
                    {{ metrics.avg_quality_score != null ? metrics.avg_quality_score.toFixed(2) : '—' }}
                  </div>
                  <div style="font-size:11px;color:var(--text-secondary);">平均质量分</div>
                </div>
                <div class="character-card" style="text-align:center;">
                  <div style="font-size:20px;color:var(--accent);">{{ formatDuration(metrics.total_duration_ms) }}</div>
                  <div style="font-size:11px;color:var(--text-secondary);">总耗时</div>
                </div>
                <div class="character-card" style="text-align:center;">
                  <div style="font-size:20px;color:var(--accent);">{{ formatDuration(metrics.avg_duration_ms) }}</div>
                  <div style="font-size:11px;color:var(--text-secondary);">平均耗时/场景</div>
                </div>
              </div>

              <!-- 模型调用量 -->
              <div style="font-size:12px;color:var(--text-secondary);margin-bottom:4px;">模型调用量</div>
              <div v-for="(n, model) in metrics.model_calls" :key="model"
                style="display:flex;justify-content:space-between;font-size:12px;padding:2px 0;">
                <span>{{ model }}</span><span style="color:var(--accent);">{{ n }} 次</span>
              </div>
              <div v-if="!Object.keys(metrics.model_calls).length" style="font-size:12px;color:var(--text-secondary);">
                尚无生成记录
              </div>

              <!-- Agent 调用量 -->
              <div style="font-size:12px;color:var(--text-secondary);margin:10px 0 4px;">Agent 调用量</div>
              <div v-for="(n, agent) in metrics.agent_calls" :key="agent"
                style="display:flex;justify-content:space-between;font-size:12px;padding:2px 0;">
                <span>{{ AGENT_TYPE_META[String(agent) as AgentType]?.icon || '⚙️' }} {{ agent }}</span>
                <span style="color:var(--accent);">{{ n }} 次</span>
              </div>

              <!-- 每场景明细 -->
              <div style="font-size:12px;color:var(--text-secondary);margin:10px 0 4px;">场景明细</div>
              <div v-for="s in [...metrics.scenes].reverse()" :key="s.scene_id"
                style="display:flex;justify-content:space-between;font-size:12px;padding:3px 0;border-bottom:1px solid var(--border);">
                <span>{{ s.scene_id }}<template v-if="s.chapter_id"> · {{ s.chapter_id }}</template></span>
                <span>
                  <span :style="{ color: s.quality_score != null && s.quality_score < 0.6 ? 'var(--error)' : 'var(--success)' }">
                    {{ s.quality_score != null ? s.quality_score.toFixed(2) : '—' }}
                  </span>
                  · {{ formatDuration(s.duration_ms) }}
                </span>
              </div>
              <div v-if="!metrics.scenes.length" style="font-size:12px;color:var(--text-secondary);">
                尚无场景
              </div>
            </div>
            <div v-else style="text-align:center;color:var(--text-secondary);padding:20px;font-size:13px;">
              {{ metricsLoading ? '加载中…' : '点击刷新加载指标' }}
            </div>
          </div>
        </template>
      </template>
    </aside>

    <!-- ==================== 游戏 / 扮演模式 ==================== -->
    <template v-if="gameMounted">
      <GamePanel
        v-show="showGame"
        :project-id="currentProjectId"
        :project-title="projectStore.currentProject?.title || ''"
        :active="showGame"
        @close="handleGameClose"
      />
    </template>

    <!-- ==================== 对话框：创建项目 ==================== -->
    <div v-if="showCreateProject" class="dialog-overlay" @click.self="showCreateProject = false">
      <div class="dialog">
        <h3>📚 新建小说项目</h3>
        <div class="form-group">
          <label>试用模板（可选：一键生成可直接试玩的示例项目，结束后可删除）</label>
          <select v-model="selectedTemplateId" @change="onSelectTemplate(selectedTemplateId)">
            <option value="">— 空白项目 —</option>
            <option v-for="t in projectStore.templates" :key="t.template_id" :value="t.template_id">
              {{ t.title }}（{{ t.style }}）
            </option>
          </select>
          <div v-if="selectedTemplateId" style="font-size:12px;color:#888;margin-top:4px;">
            {{ projectStore.templates.find(t => t.template_id === selectedTemplateId)?.description }}
          </div>
        </div>
        <div class="form-group">
          <label>标题</label>
          <input v-model="newProject.title" placeholder="例：雾中旅人" />
        </div>
        <div class="form-group">
          <label>文风基调</label>
          <input v-model="newProject.style" placeholder="例：克制、悬疑、第三人称有限视角" />
        </div>
        <div class="form-actions">
          <button class="btn btn-secondary" @click="showCreateProject = false">取消</button>
          <button class="btn btn-primary" @click="handleCreateProject" :disabled="!newProject.title">
            {{ selectedTemplateId ? '试用模板' : '创建' }}
          </button>
        </div>
      </div>
    </div>

    <!-- ==================== 对话框：新建/编辑 Agent ==================== -->
    <div v-if="showCreateAgent" class="dialog-overlay" @click.self="showCreateAgent = false">
      <div class="dialog">
        <h3>🤖 {{ editingAgentKey ? '编辑 Agent' : '添加 Agent' }}</h3>
        <div class="form-group">
          <label>Key（唯一标识：小写字母 / 数字 / 下划线）</label>
          <input v-model="agentForm.key" :disabled="!!editingAgentKey" placeholder="例：critic" />
        </div>
        <div class="form-group">
          <label>Role（角色定位）</label>
          <input v-model="agentForm.role" placeholder="例：文风批评家" />
        </div>
        <div class="form-group">
          <label>Goal（目标）</label>
          <input v-model="agentForm.goal" placeholder="例：挑出陈词滥调，保证文风统一" />
        </div>
        <div class="form-group">
          <label>Backstory（背景设定）</label>
          <textarea v-model="agentForm.backstory" rows="4" placeholder="例：你是苛刻的文学编辑，阅读过上千部小说…"></textarea>
        </div>
        <label class="checkbox-row">
          <input type="checkbox" v-model="agentForm.enabled" /> 启用该 Agent
        </label>
        <div class="form-actions">
          <button class="btn btn-secondary" @click="showCreateAgent = false">取消</button>
          <button class="btn btn-primary" @click="handleSaveAgent" :disabled="!agentForm.key || !agentForm.role || !agentForm.goal || !agentForm.backstory">
            {{ editingAgentKey ? '保存' : '添加' }}
          </button>
        </div>
      </div>
    </div>

    <!-- ==================== 对话框：新建/编辑 Task ==================== -->
    <div v-if="showTaskDialog" class="dialog-overlay" @click.self="showTaskDialog = false">
      <div class="dialog">
        <h3>📝 {{ editingTaskKey ? '编辑 Task' : '添加 Task' }}</h3>
        <div class="form-group">
          <label>Key（唯一标识：小写字母 / 数字 / 下划线）</label>
          <input v-model="taskForm.key" :disabled="!!editingTaskKey" placeholder="例：style_review" />
        </div>
        <div class="form-group">
          <label>Description（任务说明，可含 {占位符}）</label>
          <textarea v-model="taskForm.description" rows="4" placeholder="例：审查本场景正文的文风问题"></textarea>
        </div>
        <div class="form-group">
          <label>Expected Output（期望产出）</label>
          <textarea v-model="taskForm.expected_output" rows="3" placeholder="例：按严重程度排序的问题清单"></textarea>
        </div>
        <div class="form-group">
          <label>执行 Agent</label>
          <select v-model="taskForm.agent_key">
            <option :value="null">未绑定</option>
            <option v-for="agent in agentStore.agents" :key="agent.key" :value="agent.key">
              {{ agent.key }} · {{ agent.role }}
            </option>
          </select>
        </div>
        <div class="form-group">
          <label>上下文依赖（可多选，Ctrl/Cmd + 点击）</label>
          <select v-model="taskForm.context_keys" multiple size="4">
            <option
              v-for="task in taskStore.tasks.filter(t => t.key !== editingTaskKey)"
              :key="task.key"
              :value="task.key"
            >{{ task.key }}</option>
          </select>
        </div>
        <label class="checkbox-row">
          <input type="checkbox" v-model="taskForm.enabled" /> 启用该 Task
        </label>
        <div class="form-actions">
          <button class="btn btn-secondary" @click="showTaskDialog = false">取消</button>
          <button class="btn btn-primary" @click="handleSaveTask" :disabled="!taskForm.key || !taskForm.description || !taskForm.expected_output">
            {{ editingTaskKey ? '保存' : '添加' }}
          </button>
        </div>
      </div>
    </div>

    <!-- ==================== 对话框：创建角色 ==================== -->
    <div v-if="showCreateCharacter" class="dialog-overlay" @click.self="showCreateCharacter = false">
      <div class="dialog">
        <h3>🎭 新建角色</h3>
        <div class="form-group">
          <label>角色名</label>
          <input v-model="newChar.name" placeholder="例：林夏" />
        </div>
        <div class="form-group">
          <label>重要程度</label>
          <select v-model="newChar.importance_tier">
            <option value="primary">🔴 主要角色 (独立Agent)</option>
            <option value="secondary">🟡 次要角色 (群演Agent)</option>
            <option value="background">⚪ 背景角色 (群演Agent)</option>
          </select>
        </div>
        <div class="form-group">
          <label>性格 / 说话习惯</label>
          <textarea v-model="newChar.persona" rows="3" placeholder="例：冷静、善于隐藏情绪，习惯用反问句"></textarea>
        </div>
        <div class="form-group">
          <label>当前动机</label>
          <input v-model="newChar.motivation" placeholder="例：寻找失踪的姐姐" />
        </div>
        <div class="form-group">
          <label>隐藏设定（不会直接告诉角色Agent）</label>
          <textarea v-model="newChar.secrets" rows="2" placeholder="例：她其实知道姐姐去向"></textarea>
        </div>
        <div class="form-actions">
          <button class="btn btn-secondary" @click="showCreateCharacter = false">取消</button>
          <button class="btn btn-primary" @click="handleCreateCharacter" :disabled="!newChar.name">创建</button>
        </div>
      </div>
    </div>

    <!-- ==================== 对话框：创建地点 ==================== -->
    <div v-if="showCreateLocation" class="dialog-overlay" @click.self="showCreateLocation = false">
      <div class="dialog">
        <h3>📍 新建地点</h3>
        <div class="form-group">
          <label>地点名称</label>
          <input v-model="newLoc.name" placeholder="例：雾港旅店" />
        </div>
        <div class="form-group">
          <label>地点描述</label>
          <textarea v-model="newLoc.description" rows="3" placeholder="例：潮湿、灯光昏暗的小旅店大堂"></textarea>
        </div>
        <div class="form-actions">
          <button class="btn btn-secondary" @click="showCreateLocation = false">取消</button>
          <button class="btn btn-primary" @click="handleCreateLocation" :disabled="!newLoc.name">创建</button>
        </div>
      </div>
    </div>

    <!-- ==================== 对话框：从项目复制配置 ==================== -->
    <div v-if="showCopyConfig" class="dialog-overlay" @click.self="showCopyConfig = false">
      <div class="dialog">
        <h3>📋 从其他项目复制配置</h3>
        <div class="form-group">
          <label>源项目（将以覆盖方式复制其 Agent / Task 配置到当前项目）</label>
          <select v-model="copySourceId">
            <option value="" disabled>选择源项目...</option>
            <option
              v-for="p in projectStore.projects.filter(p => p.project_id !== projectStore.currentProjectId)"
              :key="p.project_id"
              :value="p.project_id"
            >{{ p.title }} ({{ p.project_id }})</option>
          </select>
        </div>
        <div class="form-actions">
          <button class="btn btn-secondary" @click="showCopyConfig = false">取消</button>
          <button class="btn btn-primary" @click="handleCopyConfig" :disabled="!copySourceId">复制（覆盖当前配置）</button>
        </div>
      </div>
    </div>

    <!-- ==================== 统一确认弹窗 ==================== -->
    <ConfirmDialog
      :show="!!confirmState"
      :title="confirmState?.title || ''"
      :message="confirmState?.message || ''"
      :confirm-text="confirmState?.confirmText"
      @confirm="runConfirm"
      @cancel="confirmState = null"
    />
  </div>
</template>
