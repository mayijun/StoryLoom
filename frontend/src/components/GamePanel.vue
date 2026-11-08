<script setup lang="ts">
/**
 * 游戏 / 扮演模式面板（M0）
 * 对话框 + 选项 + backlog + 存读档 + 模式切换 + 记忆后端切换
 */
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useApi } from '../composables/useApi'

const props = defineProps<{
  projectId: string
  projectTitle?: string
  // 面板是否可见：由父组件控制，切换导演模式时仅隐藏而不卸载
  active?: boolean
}>()
const emit = defineEmits<{ close: [notice?: string] }>()

const api = useApi()
const INSTANCE_ID = 'ui'

const state = ref<any>(null)
// 每条对话记录可携带「该回合结束时」的短/长期记忆快照
type MemorySnapshot = { short_term: any[]; long_term: any[] }
const backlog = ref<Array<{
  role: 'player' | 'narrator' | 'system'
  text: string
  directives?: Array<{ kind: string; params?: Record<string, any> }>
  memory?: MemorySnapshot
}>>([])
const choices = ref<Array<any>>([])
const input = ref('')
const mode = ref<'game' | 'director'>('game')
const busy = ref(false)
const idleTurns = ref(0)
const quality = ref(1)
const statusText = ref('')
const saves = ref<any[]>([])
const showCheckpoints = ref(false)
const storySaves = computed(() => saves.value.filter((s) => (s.kind || 'story') === 'story'))
const checkpointSaves = computed(() => saves.value.filter((s) => s.kind === 'checkpoint'))
const backend = ref('fts')
const memoryCounts = ref<Record<string, number>>({})
// 分层核心记忆：总开关 + 各层级展开状态
const memory = ref<any>(null)
const memoryOpen = ref(false)
const openTiers = ref<Record<string, boolean>>({})
const extensions = ref<any[]>([])
const logEl = ref<HTMLElement | null>(null)

async function refreshState() {
  const res = await api.getGameState(props.projectId, INSTANCE_ID)
  state.value = res.data.state
  mode.value = res.data.state.mode
  backend.value = res.data.memory.backend
  memoryCounts.value = res.data.memory.counts || {}
}

async function refreshMemory() {
  try {
    const res = await api.getMemory(props.projectId)
    memory.value = res.data
    memoryCounts.value = res.data.counts || {}
    backend.value = res.data.backend
  } catch {
    memory.value = null
  }
}

const MEMORY_TIER_META: Array<{ key: string; label: string }> = [
  { key: 'working', label: '工作记忆' },
  { key: 'short_term', label: '短期记忆' },
  { key: 'long_term', label: '长期记忆' },
  { key: 'canon', label: '正史' },
  { key: 'archive', label: '世界书' },
]

// 侧边栏 tab：世界状态 / 世界书（原「检索库」）
const sideTab = ref<'world' | 'codex'>('world')

const memoryTiers = computed(() => {
  const items = memory.value?.items || []
  return MEMORY_TIER_META.map((tier) => ({
    ...tier,
    items: items
      .filter((item: any) => item.tier === tier.key)
      .sort((a: any, b: any) => (b.importance ?? 0) - (a.importance ?? 0)),
  }))
})

// 中央区只保留当前核心层：工作记忆 + 正史
const coreMemoryTiers = computed(() =>
  memoryTiers.value.filter((tier) => ['working', 'canon'].includes(tier.key)),
)

const coreMemoryTotal = computed(() =>
  coreMemoryTiers.value.reduce((sum, tier) => sum + tier.items.length, 0),
)

// 世界书：原 archive 检索库，落位到侧边栏
const worldBookItems = computed(
  () => memoryTiers.value.find((tier) => tier.key === 'archive')?.items || [],
)

function tierLabel(key: string) {
  return MEMORY_TIER_META.find((tier) => tier.key === key)?.label || key
}

function itemSourceLabel(item: any) {
  const tags: string[] = item.tags || []
  if (tags.includes('secret')) return '秘密'
  if (tags.includes('character')) return '角色'
  if (tags.includes('location')) return '地点'
  if (tags.includes('scene')) return '场景'
  return item.source || '条目'
}

// 抓取当前短/长期记忆，作为某个回合的记忆快照
function snapshotMemory(): MemorySnapshot {
  const items = memory.value?.items || []
  const pick = (tier: string) =>
    items
      .filter((item: any) => item.tier === tier)
      .sort((a: any, b: any) => (b.importance ?? 0) - (a.importance ?? 0))
  return { short_term: pick('short_term'), long_term: pick('long_term') }
}

function toggleTier(key: string) {
  openTiers.value = { ...openTiers.value, [key]: !openTiers.value[key] }
}

async function refreshSaves() {
  const res = await api.listGameSaves(props.projectId)
  saves.value = res.data.saves || []
}

async function refreshExtensions() {
  try {
    const res = await api.resolveExtensions(INSTANCE_ID)
    extensions.value = res.data.skills || []
  } catch {
    extensions.value = []
  }
}

onMounted(loadSession)

// 记录当前已载入的项目，项目切换时重新载入会话
let loadedProjectId = ''

async function loadSession() {
  loadedProjectId = props.projectId
  try {
    await refreshState()
    // 作者主界面即导演模式；进入游戏面板时确保后端已切回游戏模式
    if (mode.value === 'director') {
      await switchToMode('game')
    }
    await refreshSaves()
    await refreshExtensions()
    await refreshMemory()
    choices.value = []
    idleTurns.value = 0
    quality.value = 1
    backlog.value = [
      {
        role: 'system',
        text: '世界已载入。你可以自由输入行动，也可以从下方选项中选择。',
      },
    ]
  } catch (err) {
    statusText.value = '无法载入世界状态，请确认后端在线。'
  }
}

// 游戏面板保持挂载；从导演工作台返回时恢复游戏模式并刷新状态，对话记录不丢失
watch(
  () => props.active,
  async (visible) => {
    if (!visible) return
    if (loadedProjectId !== props.projectId) {
      await loadSession()
      return
    }
    try {
      await refreshState()
      if (mode.value === 'director') {
        await switchToMode('game')
      }
      await refreshSaves()
      await refreshMemory()
      await scrollDown()
    } catch (err) {
      statusText.value = '刷新游戏状态失败，请稍后重试。'
    }
  },
)

// 面板隐藏时切换项目：等下次打开时由上面的 watcher 重新载入
watch(
  () => props.projectId,
  async () => {
    if (props.active) await loadSession()
  },
)

async function scrollDown() {
  await nextTick()
  if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
}

async function play(intent: any, label: string, isIdle = false) {
  if (busy.value) return
  busy.value = true
  statusText.value = ''
  backlog.value.push({ role: 'player', text: label })
  try {
    const res = await api.playTurn(props.projectId, {
      instance_id: INSTANCE_ID,
      mode: mode.value,
      intent,
      idle_turns: idleTurns.value,
      max_duration_ms: 60000,
    })
    const data = res.data
    state.value = data.state
    choices.value = data.choices || []
    quality.value = data.quality
    if (data.quality_flags?.length) {
      statusText.value = `质量标记：${data.quality_flags.join('、')}`
    }
    if (data.status === 'timeout') {
      statusText.value = '本回合超时，世界保持原状。'
    }
    backlog.value.push({
      role: 'narrator',
      text: data.text || '（这一回合没有新的叙述）',
      directives: data.scene?.directives || [],
    })
    // 通过响应式数组取回这条记录，后续写入记忆快照才能触发界面更新
    const entry = backlog.value[backlog.value.length - 1]
    idleTurns.value = isIdle ? idleTurns.value + 1 : 0
    await refreshMemory()
    // 记忆随回合演进：把本回合结束时的短/长期记忆快照挂到这条输出记录上
    entry.memory = snapshotMemory()
    await refreshSaves()
  } catch (err: any) {
    statusText.value = err?.response?.data?.detail || '回合执行失败。'
  } finally {
    busy.value = false
    await scrollDown()
  }
}

function sendText() {
  const text = input.value.trim()
  if (!text) return
  input.value = ''
  play({ kind: 'text', payload: { text } }, text)
}

function choose(option: any) {
  play(
    {
      kind: 'choice',
      payload: {
        action: option.action,
        target: option.target,
        label: option.label,
      },
    },
    option.label,
  )
}

function waitTurn() {
  play({ kind: 'skip' }, '（原地等待）', true)
}

async function switchToMode(target: 'game' | 'director'): Promise<boolean> {
  try {
    const res = await api.switchGameMode(props.projectId, target, INSTANCE_ID)
    state.value = res.data.state
    mode.value = res.data.mode
    return true
  } catch (err: any) {
    statusText.value = err?.response?.data?.detail || '模式切换失败。'
    return false
  }
}

async function toggleMode() {
  // 导演模式对应作者主界面：切换成功后关闭游戏面板并返回
  if (mode.value === 'director') {
    await switchToMode('game')
    return
  }
  if (await switchToMode('director')) {
    emit('close', '已切换到导演模式，返回作者主界面（切换前已落 checkpoint）')
  }
}

async function changeBackend(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  try {
    const res = await api.patchMemory(props.projectId, value)
    memory.value = res.data
    backend.value = res.data.backend
    memoryCounts.value = res.data.counts || {}
    backlog.value.push({
      role: 'system',
      text: `记忆检索后端已切换为 ${backend.value}。`,
    })
    await scrollDown()
  } catch (err: any) {
    statusText.value = err?.response?.data?.detail || '后端切换失败。'
    backend.value = backend.value
  }
}

const showSaveDialog = ref(false)
const saveName = ref('')

function openSaveDialog() {
  const s = state.value
  const loc = s?.characters?.['玩家']?.location || '未知地点'
  saveName.value = `${loc} · 第${s?.turn ?? 0}回合`
  showSaveDialog.value = true
}

async function confirmSave() {
  const name = saveName.value.trim()
  if (!name) {
    statusText.value = '请填写存档名称。'
    return
  }
  try {
    await api.createGameSave(props.projectId, {
      instance_id: INSTANCE_ID,
      label: name,
      // 把当前对话记录随存档一起保存，读档时用于恢复上下文
      backlog: backlog.value.slice(-200),
    })
    showSaveDialog.value = false
    await refreshSaves()
  } catch {
    statusText.value = '存档失败。'
  }
}

async function loadGame(saveId: string) {
  try {
    const res = await api.loadGameSave(props.projectId, saveId, INSTANCE_ID)
    await refreshState()
    const saved = res.data || {}
    const restored = saved.metadata?.backlog || []
    backlog.value = [
      {
        role: 'system',
        text: `已读档：${saved.label || '存档'} · ${saved.mode === 'director' ? '导演' : '游戏'}模式`,
      },
    ]
    if (restored.length) {
      // 恢复存档时点的完整对话记录
      backlog.value.push(...restored)
    } else if (saved.text) {
      // 旧存档 / 系统检查点只保留了最后一幕
      backlog.value.push({
        role: 'narrator',
        text: saved.text,
        directives: saved.directives || [],
      })
    }
    // 恢复存档时点的行动选项，读档后可继续推进剧情
    choices.value = saved.choices || []
    await refreshMemory()
    await scrollDown()
  } catch {
    statusText.value = '读档失败。'
  }
}

function checkpointLabel(save: any) {
  const label = save.label || ''
  if (label === 'switch_to_game') return '切到游戏模式'
  if (label === 'switch_to_director') return '切到导演模式'
  if (label.startsWith('before_override_')) return '导演改写前'
  return label || '系统日志'
}

// 世界优先的 HUD：叙事节拍、在场角色、真实世界状态（非伪数值）
const ARC_PHASE_LABELS: Record<string, string> = {
  setup: '起',
  rising: '承',
  climax: '转',
  resolution: '合',
}

const arcInfo = computed(() => {
  const arc = state.value?.arc
  if (!arc) return null
  return {
    label: ARC_PHASE_LABELS[arc.phase] || arc.phase,
    tension: Number(arc.tension_target ?? 0).toFixed(2),
    beats: arc.beats_remaining ?? 0,
  }
})

const presentCharacters = computed(() => {
  const s = state.value
  if (!s?.characters) return []
  const loc = s.characters['玩家']?.location
  return Object.values(s.characters)
    .filter((c: any) => c.location === loc && c.status === 'active')
    .map((c: any) => ({
      name: c.name,
      emotion: c.emotion || '平静',
      health: c.health ?? 100,
    }))
})

const flagEntries = computed(() => Object.entries(state.value?.flags || {}))
const relationshipEntries = computed(() =>
  Object.entries(state.value?.relationships || {}),
)

// 只展示对玩家有意义的舞台指令，状态栏/选项等已有单独位置
function visibleDirectives(entry: any) {
  return (entry.directives || []).filter(
    (d: any) => !['say', 'end', 'show', 'choice'].includes(d.kind),
  )
}

function directiveLabel(d: any) {
  if (d.kind === 'move') {
    return `移动 ${d.params?.from || '?'} → ${d.params?.to || '?'}`
  }
  if (d.kind === 'bg') return `场景 ${d.params?.location || ''}`
  if (d.kind === 'effect' && d.params?.name === 'blocked') {
    return `受阻 ${d.params?.error_code || ''}`
  }
  return d.kind
}

const statusBar = () => {
  const s = state.value
  if (!s) return '载入中…'
  const loc = s.characters?.['玩家']?.location || ''
  const present = Object.values(s.characters || {})
    .filter((c: any) => c.location === loc && c.status === 'active')
    .map((c: any) => c.name)
    .join('、')
  return `${s.mode === 'game' ? '游戏' : '导演'} · 第${s.turn}回合 · ${loc || '未知地点'} · ${present || '无人在场'}`
}
</script>

<template>
  <div class="game-shell">
    <header class="game-header">
      <div class="game-title">🎮 {{ projectTitle || projectId }}</div>
      <div class="game-status">{{ statusBar() }}</div>
      <div class="game-actions">
        <button class="btn btn-secondary btn-sm" @click="toggleMode">
          {{ mode === 'game' ? '切到导演模式' : '切到游戏模式' }}
        </button>
        <button class="btn btn-secondary btn-sm" @click="openSaveDialog">💾 存档</button>
        <button class="btn btn-secondary btn-sm" @click="emit('close')">退出</button>
      </div>
    </header>

    <div class="game-body">
      <section class="stage">
        <div class="backlog" ref="logEl">
          <div v-for="(entry, index) in backlog" :key="index" class="entry" :class="entry.role">
            <div class="bubble">
              <div class="entry-text">{{ entry.text }}</div>
              <div
                v-if="visibleDirectives(entry).length"
                class="directive-chips"
              >
                <span
                  v-for="(directive, di) in visibleDirectives(entry)"
                  :key="di"
                  class="directive-chip"
                >{{ directiveLabel(directive) }}</span>
              </div>
              <!-- 每回合输出内嵌短/长期记忆快照（默认折叠） -->
              <details
                v-if="entry.role === 'narrator' && entry.memory"
                class="entry-memory"
              >
                <summary>
                  记忆快照 · 短期 {{ entry.memory.short_term.length }} · 长期 {{ entry.memory.long_term.length }}
                </summary>
                <div class="mem-group">
                  <div class="mem-group-title">短期记忆</div>
                  <div v-if="!entry.memory.short_term.length" class="mem-empty">暂无</div>
                  <ul v-else class="mem-list">
                    <li v-for="item in entry.memory.short_term" :key="item.id">
                      {{ item.summary || item.text }}
                      <span class="mem-item-meta">场景 {{ item.scene_index }}</span>
                    </li>
                  </ul>
                </div>
                <div class="mem-group">
                  <div class="mem-group-title">长期记忆</div>
                  <div v-if="!entry.memory.long_term.length" class="mem-empty">暂无</div>
                  <ul v-else class="mem-list">
                    <li v-for="item in entry.memory.long_term" :key="item.id">
                      {{ item.summary || item.text }}
                      <span class="mem-item-meta">场景 {{ item.scene_index }}</span>
                    </li>
                  </ul>
                </div>
              </details>
            </div>
          </div>
          <div v-if="busy" class="entry narrator">
            <div class="bubble">世界正在回应…</div>
          </div>
        </div>

        <!-- 当前核心层（工作记忆 / 正史）；短期与长期记忆已内嵌到每条输出 -->
        <div class="memory-block">
          <button class="memory-toggle" @click="memoryOpen = !memoryOpen">
            <span>🧠 核心记忆</span>
            <span class="memory-meta">{{ coreMemoryTotal }} 条 · {{ backend }}</span>
            <span class="memory-caret">{{ memoryOpen ? '▾' : '▸' }}</span>
          </button>
          <div v-if="memoryOpen" class="memory-tiers">
            <div v-for="tier in coreMemoryTiers" :key="tier.key" class="memory-tier">
              <button
                class="tier-head"
                :disabled="!tier.items.length"
                @click="toggleTier(tier.key)"
              >
                <span>{{ tier.label }}</span>
                <span class="tier-count">{{ tier.items.length }}</span>
                <span class="memory-caret">{{ openTiers[tier.key] ? '▾' : '▸' }}</span>
              </button>
              <ul v-if="openTiers[tier.key] && tier.items.length" class="tier-items">
                <li v-for="item in tier.items" :key="item.id">
                  <div class="tier-text">{{ item.summary || item.text }}</div>
                  <div class="tier-tags">
                    <span>重要度 {{ Number(item.importance ?? 0).toFixed(2) }}</span>
                    <span>场景 {{ item.scene_index }}</span>
                    <span v-if="item.pinned">📌 固定</span>
                    <span v-if="item.active_foreshadow">活跃伏笔</span>
                    <span v-if="item.source === 'demoted'">已降级</span>
                  </div>
                </li>
              </ul>
            </div>
          </div>
        </div>

        <div v-if="statusText" class="status-note">{{ statusText }}</div>

        <div v-if="choices.length" class="choices">
          <button
            v-for="option in choices"
            :key="option.index"
            class="choice"
            :disabled="busy"
            @click="choose(option)"
          >
            <span class="choice-index">{{ (option.index ?? 0) + 1 }}</span>
            <span v-if="option.action" class="choice-kind">{{ option.action }}</span>
            {{ option.label }}
          </button>
        </div>

        <div class="input-row">
          <textarea
            v-model="input"
            rows="2"
            placeholder="描述你的行动，例如：我前往码头 / 拔剑刺向国王 / 问老板航海图是谁的"
            @keydown.enter.exact.prevent="sendText"
          ></textarea>
          <div class="input-actions">
            <button class="btn btn-primary" :disabled="busy || !input.trim()" @click="sendText">发送</button>
            <button class="btn btn-secondary" :disabled="busy" @click="waitTurn">等待</button>
          </div>
        </div>
      </section>

      <aside class="game-side">
        <div class="side-block">
          <!-- 世界状态 / 世界书（原检索库）合并为一个 tab 区 -->
          <div class="side-tabs">
            <button
              class="side-tab"
              :class="{ active: sideTab === 'world' }"
              @click="sideTab = 'world'"
            >世界状态</button>
            <button
              class="side-tab"
              :class="{ active: sideTab === 'codex' }"
              @click="sideTab = 'codex'"
            >世界书</button>
          </div>

          <template v-if="sideTab === 'world'">
            <div class="kv"><span>模式</span><b>{{ mode === 'game' ? '游戏 / 扮演' : '导演' }}</b></div>
            <div class="kv"><span>时间</span><b>{{ state?.time_minutes != null ? `${Math.floor(state.time_minutes / 60)}:${String(state.time_minutes % 60).padStart(2, '0')}` : '—' }}</b></div>
            <div class="kv"><span>回合</span><b>{{ state?.turn ?? 0 }}</b></div>
            <div class="kv"><span>质量</span><b>{{ quality.toFixed(2) }}</b></div>
            <div class="kv"><span>等待</span><b>{{ idleTurns }} 回合</b></div>

            <div v-if="arcInfo" class="hud-block">
              <div class="side-label">叙事节拍</div>
              <div class="hud-row">
                <span>{{ arcInfo.label }}</span>
                <span>张力 {{ arcInfo.tension }}</span>
                <span>剩余 {{ arcInfo.beats }}</span>
              </div>
            </div>

            <div v-if="presentCharacters.length" class="hud-block">
              <div class="side-label">在场角色</div>
              <div
                v-for="character in presentCharacters"
                :key="character.name"
                class="hud-row"
              >
                <span>{{ character.name }}</span>
                <span>{{ character.emotion }}</span>
                <span>HP {{ character.health }}</span>
              </div>
            </div>

            <div v-if="flagEntries.length" class="hud-block">
              <div class="side-label">世界标记</div>
              <div class="hud-row" v-for="[key, value] in flagEntries" :key="key">
                <span>{{ key }}</span>
                <span>{{ value }}</span>
              </div>
            </div>

            <div v-if="relationshipEntries.length" class="hud-block">
              <div class="side-label">关系</div>
              <div
                class="hud-row"
                v-for="[key, value] in relationshipEntries"
                :key="key"
              >
                <span>{{ key }}</span>
                <span>{{ value }}</span>
              </div>
            </div>

            <div class="side-label" style="margin-top:8px;">检索方式</div>
            <select :value="backend" @change="changeBackend">
              <option value="fts">fts（默认）</option>
              <option value="vector">vector</option>
              <option value="hybrid">hybrid</option>
            </select>
            <div class="counts">
              <span v-for="(value, tier) in memoryCounts" :key="tier">{{ tierLabel(tier) }}:{{ value }}</span>
            </div>
          </template>

          <template v-else>
            <div class="worldbook-head">
              <span>共 {{ worldBookItems.length }} 条</span>
              <span class="memory-meta">按重要度排序</span>
            </div>
            <div v-if="!worldBookItems.length" class="empty">暂无世界书条目</div>
            <ul v-else class="tier-items worldbook-items">
              <li v-for="item in worldBookItems" :key="item.id">
                <div class="tier-text">{{ item.summary || item.text }}</div>
                <div class="tier-tags">
                  <span>{{ itemSourceLabel(item) }}</span>
                  <span>重要度 {{ Number(item.importance ?? 0).toFixed(2) }}</span>
                  <span v-if="item.pinned">📌 固定</span>
                </div>
              </li>
            </ul>
          </template>
        </div>

        <div class="side-block" v-if="extensions.length">
          <div class="side-label">已加载扩展</div>
          <div v-for="skill in extensions" :key="skill.id" class="ext-item">
            {{ skill.name || skill.id }}
          </div>
        </div>

        <div class="side-block">
          <div class="side-label">故事存档</div>
          <div v-if="!storySaves.length" class="empty">暂无存档</div>
          <div
            v-for="save in storySaves"
            :key="save.save_id"
            class="save-item"
            title="点击读取该存档"
            @click="loadGame(save.save_id)"
          >
            <div>
              <div>{{ save.label }}</div>
              <small>{{ save.mode === 'director' ? '导演' : '游戏' }} · {{ save.created_at?.slice(0, 19) }}</small>
            </div>
            <button class="btn btn-secondary btn-sm" @click.stop="loadGame(save.save_id)">读取</button>
          </div>
        </div>

        <div class="side-block">
          <div class="side-label checkpoint-toggle" title="自动记录的操作快照，不计入故事存档" @click="showCheckpoints = !showCheckpoints">
            系统日志（{{ checkpointSaves.length }}）{{ showCheckpoints ? '▾' : '▸' }}
          </div>
          <template v-if="showCheckpoints">
            <div v-if="!checkpointSaves.length" class="empty">暂无日志</div>
            <div
              v-for="save in checkpointSaves"
              :key="save.save_id"
              class="save-item"
              title="点击回滚到该检查点"
              @click="loadGame(save.save_id)"
            >
              <div>
                <div>{{ checkpointLabel(save) }}</div>
                <small>第{{ save.turn }}回合 · {{ save.created_at?.slice(0, 19) }}</small>
              </div>
              <button class="btn btn-secondary btn-sm" @click.stop="loadGame(save.save_id)">回滚</button>
            </div>
          </template>
        </div>
      </aside>
    </div>

    <div v-if="showSaveDialog" class="modal-mask" @click.self="showSaveDialog = false">
      <div class="modal">
        <div class="modal-title">保存故事存档</div>
        <input
          v-model="saveName"
          class="modal-input"
          maxlength="40"
          placeholder="给这个存档起个名字"
          @keyup.enter="confirmSave"
        />
        <div class="modal-actions">
          <button class="btn btn-secondary btn-sm" @click="showSaveDialog = false">取消</button>
          <button class="btn btn-primary btn-sm" :disabled="!saveName.trim()" @click="confirmSave">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.game-shell {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary, #12141a);
}
.game-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border, #2a2d36);
}
.game-title { font-weight: 600; }
.game-status { font-size: 12px; color: var(--text-secondary, #9aa0aa); flex: 1; }
.game-actions { display: flex; gap: 8px; }
.game-body { flex: 1; display: flex; min-height: 0; }
.stage { flex: 1; display: flex; flex-direction: column; min-width: 0; padding: 16px; gap: 10px; }
.backlog {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-right: 6px;
}
.entry { display: flex; }
.entry.player { justify-content: flex-end; }
.bubble {
  max-width: 78%;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--bg-input, #1c1f27);
  border: 1px solid var(--border, #2a2d36);
  line-height: 1.6;
  white-space: pre-wrap;
}
.entry.player .bubble { border-color: var(--accent, #5b8def); }
.entry.system .bubble { background: transparent; color: var(--text-secondary, #9aa0aa); font-size: 12px; }
.entry-text { font-size: 14px; }
/* 单条输出内的短/长期记忆快照 */
.entry-memory {
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px dashed var(--border, #2a2d36);
  font-size: 12px;
}
.entry-memory > summary {
  cursor: pointer;
  color: var(--text-secondary, #9aa0aa);
  user-select: none;
  list-style: none;
}
.entry-memory > summary::-webkit-details-marker { display: none; }
.entry-memory > summary::before { content: '▸ '; }
.entry-memory[open] > summary::before { content: '▾ '; }
.mem-group { margin-top: 6px; }
.mem-group-title {
  margin-bottom: 4px;
  font-size: 11px;
  color: var(--accent, #5b8def);
}
.mem-list {
  list-style: none;
  margin: 0;
  padding: 0 0 0 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.mem-list li {
  padding-left: 6px;
  border-left: 2px solid var(--border, #2a2d36);
  line-height: 1.5;
}
.mem-item-meta { margin-left: 6px; font-size: 11px; color: var(--text-secondary, #9aa0aa); }
.mem-empty { font-size: 11px; color: var(--text-secondary, #9aa0aa); }
/* 分层核心记忆 */
.memory-block { border-top: 1px solid var(--border, #2a2d36); padding-top: 6px; }
.memory-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  border: none;
  background: transparent;
  color: var(--text-primary, #e6e8ec);
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
}
.memory-meta { font-size: 11px; color: var(--text-secondary, #9aa0aa); }
.memory-caret { margin-left: auto; font-size: 11px; color: var(--text-secondary, #9aa0aa); }
.memory-tiers { display: flex; flex-direction: column; gap: 4px; margin: 4px 0; }
.memory-tier { border: 1px solid var(--border, #2a2d36); border-radius: 6px; overflow: hidden; }
.tier-head {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: none;
  background: var(--bg-input, #1c1f27);
  color: var(--text-primary, #e6e8ec);
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
}
.tier-head:disabled { opacity: 0.45; cursor: default; }
.tier-count {
  min-width: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-secondary, #9aa0aa);
  font-size: 11px;
  text-align: center;
}
.tier-items {
  list-style: none;
  margin: 0;
  padding: 2px 8px 8px;
  max-height: 220px;
  overflow-y: auto;
}
.tier-items li { padding: 6px 0; border-top: 1px dashed var(--border, #2a2d36); }
.tier-text { font-size: 12px; line-height: 1.5; }
.tier-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 4px;
  font-size: 11px;
  color: var(--text-secondary, #9aa0aa);
}
.status-note { font-size: 12px; color: var(--warning, #d8a657); }
.choices { display: flex; flex-wrap: wrap; gap: 8px; }
.choice {
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid var(--border, #2a2d36);
  background: var(--bg-input, #1c1f27);
  color: var(--text-primary, #e6e8ec);
  cursor: pointer;
}
.choice:hover { border-color: var(--accent, #5b8def); }
.choice-index {
  display: inline-block;
  min-width: 16px;
  margin-right: 4px;
  color: var(--text-secondary, #9aa0aa);
  font-size: 11px;
}
.choice-kind {
  display: inline-block;
  margin-right: 4px;
  padding: 0 5px;
  border-radius: 4px;
  background: rgba(91, 141, 239, 0.14);
  color: var(--accent, #5b8def);
  font-size: 10px;
}
/* 舞台指令 chip：移动 / 场景 / 受阻 */
.directive-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.directive-chip {
  padding: 1px 6px;
  border: 1px solid var(--border, #2a2d36);
  border-radius: 10px;
  color: var(--text-secondary, #9aa0aa);
  font-size: 10px;
}
.input-row { display: flex; gap: 10px; align-items: stretch; }
.input-row textarea {
  flex: 1;
  resize: none;
  padding: 10px;
  border-radius: 8px;
  border: 1px solid var(--border, #2a2d36);
  background: var(--bg-input, #1c1f27);
  color: var(--text-primary, #e6e8ec);
  font-family: inherit;
}
.input-actions { display: flex; flex-direction: column; gap: 6px; }
.game-side {
  width: 260px;
  border-left: 1px solid var(--border, #2a2d36);
  padding: 16px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.side-block { display: flex; flex-direction: column; gap: 6px; }
.side-label { font-size: 12px; color: var(--text-secondary, #9aa0aa); }
/* 世界状态 / 世界书 tab */
.side-tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border, #2a2d36); }
.side-tab {
  padding: 5px 10px;
  border: none;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--text-secondary, #9aa0aa);
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
}
.side-tab.active {
  color: var(--text-primary, #e6e8ec);
  border-bottom-color: var(--accent, #5b8def);
}
.worldbook-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
}
.worldbook-items {
  max-height: none;
  padding: 0;
  margin: 0;
}
.worldbook-items li { padding: 6px 0; }
.kv { display: flex; justify-content: space-between; font-size: 12px; }
/* 世界优先 HUD：节拍 / 在场角色 / 标记 / 关系 */
.hud-block { margin-top: 8px; }
.hud-row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  color: var(--text-primary, #e6e8ec);
}
.counts { display: flex; flex-wrap: wrap; gap: 6px; font-size: 11px; color: var(--text-secondary, #9aa0aa); }
.ext-item { font-size: 12px; }
.save-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  padding: 6px 0;
  border-bottom: 1px solid var(--border, #2a2d36);
  cursor: pointer;
  border-radius: 4px;
}
.save-item:hover { background: var(--bg-hover, rgba(255, 255, 255, 0.05)); }
.save-item small { color: var(--text-secondary, #9aa0aa); }
.checkpoint-toggle { cursor: pointer; user-select: none; }
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.5);
}
.modal {
  width: 320px;
  padding: 18px;
  border-radius: 10px;
  background: var(--bg-primary, #12141a);
  border: 1px solid var(--border, #2a2d36);
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.modal-title { font-weight: 600; }
.modal-input {
  width: 100%;
  box-sizing: border-box;
  background: var(--bg-input, #1c1f27);
  color: var(--text-primary, #e6e8ec);
  border: 1px solid var(--border, #2a2d36);
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 13px;
}
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }
.empty { font-size: 12px; color: var(--text-secondary, #9aa0aa); }
.toggle { display: flex; align-items: center; gap: 6px; font-size: 12px; }
select {
  background: var(--bg-input, #1c1f27);
  color: var(--text-primary, #e6e8ec);
  border: 1px solid var(--border, #2a2d36);
  border-radius: 6px;
  padding: 6px 8px;
}
</style>
