<script setup lang="ts">
import { ref, onMounted, provide } from 'vue'
import { useProjectStore } from './stores/projectStore'
import { useAgentStore } from './stores/agentStore'
import { useAssetStore } from './stores/assetStore'
import { useGenerationStore } from './stores/generationStore'
import { useTaskStore } from './stores/taskStore'
import { useApi } from './composables/useApi'

import type { AgentConfig, AgentConfigInput, AgentMessage, AgentType } from './types/agent'
import type { TaskConfig, TaskConfigInput } from './types/task'
import type { CharacterAsset } from './types/asset'
import { AGENT_TYPE_META } from './types/agent'
import { FORESHADOW_STATUS_META } from './types/asset'

const api = useApi()
const projectStore = useProjectStore()
const agentStore = useAgentStore()
const assetStore = useAssetStore()
const genStore = useGenerationStore()
const taskStore = useTaskStore()

// ---- 状态 ----
const serverOnline = ref(false)
const activeTab = ref<'agents' | 'flow'>('agents')
const rightTab = ref<'characters' | 'locations' | 'foreshadowings'>('characters')
const sceneBrief = ref('')
const selectedChars = ref<string[]>([])

// 对话框状态
const showCreateProject = ref(false)
const showCreateAgent = ref(false)
const showCreateCharacter = ref(false)
const showCreateLocation = ref(false)

// 配置编辑：null 表示新建
const editingAgentKey = ref<string | null>(null)
const editingTaskKey = ref<string | null>(null)
const showTaskDialog = ref(false)

// 表单数据
const newProject = ref({ title: '', style: '' })
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
onMounted(async () => {
  try {
    await api.checkHealth()
    serverOnline.value = true
    await projectStore.fetchProjects()
    await agentStore.fetchAgents()
    await taskStore.fetchTasks()
  } catch {
    serverOnline.value = false
  }
})

// ---- 方法 ----
async function handleCreateProject() {
  await projectStore.createProject(newProject.value.title, newProject.value.style)
  showCreateProject.value = false
  newProject.value = { title: '', style: '' }
  if (projectStore.currentProjectId) {
    await assetStore.fetchAll(projectStore.currentProjectId)
  }
}

async function handleSelectProject(id: string) {
  await projectStore.selectProject(id)
  await assetStore.fetchAll(id)
  selectedChars.value = []
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
    await agentStore.updateAgent(editingAgentKey.value, patch)
  } else {
    await agentStore.addAgent({ ...agentForm.value })
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
    await taskStore.updateTask(editingTaskKey.value, patch)
  } else {
    await taskStore.addTask({ ...taskForm.value })
  }
  showTaskDialog.value = false
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
  if (!projectStore.currentProjectId || !sceneBrief.value.trim()) return
  await genStore.generateScene(
    projectStore.currentProjectId,
    sceneBrief.value,
    selectedChars.value,
  )
}
</script>

<template>
  <div class="app-layout" :class="{ 'layout-wide': activeTab === 'agents' }">
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

      <button class="btn btn-secondary btn-sm" @click="showCreateProject = true">
        ＋ 新建项目
      </button>

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
        <div class="tab" :class="{ active: activeTab === 'agents' }" @click="activeTab = 'agents'">
          🤖 Agents
        </div>
        <div class="tab" :class="{ active: activeTab === 'flow' }" @click="activeTab = 'flow'">
          🔗 Flow
        </div>
      </div>

      <!-- Agent / Task 双栏编辑 -->
      <template v-if="activeTab === 'agents'">
        <div class="config-columns">
          <!-- 左栏：Agents -->
          <div class="panel">
            <div class="panel-title">
              <span>🤖 Agents</span>
              <button class="btn btn-sm btn-primary" @click="openCreateAgent" style="margin-left:auto;">
                ＋ 添加
              </button>
            </div>

            <div
              v-for="agent in agentStore.agents"
              :key="agent.key"
              class="agent-card"
              :class="{ disabled: !agent.enabled }"
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
                @click.stop="agentStore.removeAgent(agent.key)"
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
              v-for="task in taskStore.tasks"
              :key="task.key"
              class="agent-card"
              :class="{ disabled: !task.enabled }"
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
                @click.stop="taskStore.removeTask(task.key)"
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
      </template>

      <!-- Flow编辑器预留 -->
      <template v-if="activeTab === 'flow'">
        <div class="flow-editor-placeholder">
          <div class="icon">🔗</div>
          <div class="title">Flow 可视化编辑器</div>
          <div class="desc">
            Phase 2 将接入 Vue Flow<br>
            支持拖曳式Agent工作流编排<br><br>
            <small style="color:var(--accent);">
              数据结构已预留，兼容 Vue Flow 节点/边格式
            </small>
          </div>
        </div>
      </template>
    </aside>

    <!-- ==================== 主内容区：场景剧场 ==================== -->
    <main class="main-content">
      <template v-if="projectStore.currentProjectId">
        <div class="scene-theater">
          <!-- 消息流 -->
          <div class="scene-messages">
            <!-- 系统消息 -->
            <div v-if="agentStore.messages.length === 0 && !genStore.finalProse"
              style="text-align:center;color:var(--text-secondary);padding:60px 20px;">
              <div style="font-size:48px;margin-bottom:16px;">🎭</div>
              <div style="font-size:16px;margin-bottom:8px;">准备好创作了吗？</div>
              <div style="font-size:13px;">
                在下方输入场景描述，选择在场角色，开始生成
              </div>
            </div>

            <!-- Agent消息 -->
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

            <!-- 生成中动画 -->
            <div v-if="genStore.isGenerating" class="message-bubble system">
              <span class="loading-dots">{{ genStore.currentStep }} 生成中</span>
            </div>

            <!-- 最终正文 -->
            <div v-if="genStore.finalProse" class="final-prose">
              <div style="font-size:12px;color:var(--accent);margin-bottom:12px;font-family:sans-serif;">
                📖 最终正文
              </div>
              {{ genStore.finalProse }}
            </div>
          </div>

          <!-- 在场角色选择 -->
          <div style="padding:8px 16px;display:flex;gap:6px;flex-wrap:wrap;border-top:1px solid var(--border);">
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
          </div>

          <!-- 输入区 -->
          <div class="scene-input">
            <textarea
              v-model="sceneBrief"
              placeholder="描述这个场景的大致内容..."
              @keydown.ctrl.enter="handleGenerate"
            ></textarea>
            <button
              class="btn btn-primary"
              :disabled="genStore.isGenerating || !sceneBrief.trim() || selectedChars.length === 0"
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
          <button class="btn btn-primary" @click="showCreateProject = true">
            ＋ 新建项目
          </button>
        </div>
      </template>
    </main>

    <!-- ==================== 右侧边栏：资产管理 ==================== -->
    <aside class="sidebar-right">
      <template v-if="projectStore.currentProjectId">
        <div class="tabs">
          <div class="tab" :class="{ active: rightTab === 'characters' }" @click="rightTab = 'characters'">
            🎭 角色
          </div>
          <div class="tab" :class="{ active: rightTab === 'locations' }" @click="rightTab = 'locations'">
            📍 场景
          </div>
          <div class="tab" :class="{ active: rightTab === 'foreshadowings' }" @click="rightTab = 'foreshadowings'">
            📌 伏笔
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

        <!-- 场景列表 -->
        <template v-if="rightTab === 'locations'">
          <div class="panel">
            <div class="panel-title">
              场景资产
              <button class="btn btn-sm btn-secondary" @click="showCreateLocation = true" style="margin-left:auto;">＋</button>
            </div>
            <div v-for="loc in assetStore.locations" :key="loc.name" class="character-card">
              <div class="char-name">📍 {{ loc.name }}</div>
              <div class="char-persona">{{ loc.description }}</div>
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
            </div>
            <div v-if="assetStore.foreshadowings.length === 0" style="text-align:center;color:var(--text-secondary);padding:20px;font-size:13px;">
              暂无伏笔
            </div>
          </div>
        </template>
      </template>
    </aside>

    <!-- ==================== 对话框：创建项目 ==================== -->
    <div v-if="showCreateProject" class="dialog-overlay" @click.self="showCreateProject = false">
      <div class="dialog">
        <h3>📚 新建小说项目</h3>
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
          <button class="btn btn-primary" @click="handleCreateProject" :disabled="!newProject.title">创建</button>
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

    <!-- ==================== 对话框：创建场景 ==================== -->
    <div v-if="showCreateLocation" class="dialog-overlay" @click.self="showCreateLocation = false">
      <div class="dialog">
        <h3>📍 新建场景</h3>
        <div class="form-group">
          <label>场景名称</label>
          <input v-model="newLoc.name" placeholder="例：雾港旅店" />
        </div>
        <div class="form-group">
          <label>场景描述</label>
          <textarea v-model="newLoc.description" rows="3" placeholder="例：潮湿、灯光昏暗的小旅店大堂"></textarea>
        </div>
        <div class="form-actions">
          <button class="btn btn-secondary" @click="showCreateLocation = false">取消</button>
          <button class="btn btn-primary" @click="handleCreateLocation" :disabled="!newLoc.name">创建</button>
        </div>
      </div>
    </div>
  </div>
</template>
