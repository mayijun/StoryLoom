<script setup lang="ts">
/**
 * 游戏 / 扮演模式面板（M0）
 * 对话框 + 选项 + backlog + 存读档 + 模式切换 + 记忆后端切换
 */
import { ref, computed, onMounted, nextTick } from 'vue'
import { useApi } from '../composables/useApi'

const props = defineProps<{ projectId: string; projectTitle?: string }>()
const emit = defineEmits<{ close: [notice?: string] }>()

const api = useApi()
const INSTANCE_ID = 'ui'

const state = ref<any>(null)
const backlog = ref<Array<{
  role: 'player' | 'narrator' | 'system'
  text: string
  directives?: Array<{ kind: string; params?: Record<string, any> }>
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
  { key: 'archive', label: '检索库' },
]

const memoryTiers = computed(() => {
  const items = memory.value?.items || []
  return MEMORY_TIER_META.map((tier) => ({
    ...tier,
    items: items
      .filter((item: any) => item.tier === tier.key)
      .sort((a: any, b: any) => (b.importance ?? 0) - (a.importance ?? 0)),
  }))
})

const memoryTotal = computed(() =>
  memoryTiers.value.reduce((sum, tier) => sum + tier.items.length, 0),
)

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

onMounted(async () => {
  try {
    await refreshState()
    // 作者主界面即导演模式；进入游戏面板时确保后端已切回游戏模式
    if (mode.value === 'director') {
      await switchToMode('game')
    }
    await refreshSaves()
    await refreshExtensions()
    await refreshMemory()
    backlog.value.push({
      role: 'system',
      text: '世界已载入。你可以自由输入行动，也可以从下方选项中选择。',
    })
  } catch (err) {
    statusText.value = '无法载入世界状态，请确认后端在线。'
  }
})

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
    idleTurns.value = isIdle ? idleTurns.value + 1 : 0
    await refreshMemory()
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
            </div>
          </div>
          <div v-if="busy" class="entry narrator">
            <div class="bubble">世界正在回应…</div>
          </div>
        </div>

        <!-- 分层核心记忆：替代原先无意义的 move / bg 指令 chips -->
        <div class="memory-block">
          <button class="memory-toggle" @click="memoryOpen = !memoryOpen">
            <span>🧠 核心记忆</span>
            <span class="memory-meta">{{ memoryTotal }} 条 · {{ backend }}</span>
            <span class="memory-caret">{{ memoryOpen ? '▾' : '▸' }}</span>
          </button>
          <div v-if="memoryOpen" class="memory-tiers">
            <div v-for="tier in memoryTiers" :key="tier.key" class="memory-tier">
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
          >{{ option.label }}</button>
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
          <div class="side-label">世界状态</div>
          <div class="kv"><span>模式</span><b>{{ mode === 'game' ? '游戏 / 扮演' : '导演' }}</b></div>
          <div class="kv"><span>时间</span><b>{{ state?.time_minutes != null ? `${Math.floor(state.time_minutes / 60)}:${String(state.time_minutes % 60).padStart(2, '0')}` : '—' }}</b></div>
          <div class="kv"><span>回合</span><b>{{ state?.turn ?? 0 }}</b></div>
          <div class="kv"><span>质量</span><b>{{ quality.toFixed(2) }}</b></div>
          <div class="kv"><span>等待</span><b>{{ idleTurns }} 回合</b></div>
        </div>

        <div class="side-block">
          <div class="side-label">记忆检索</div>
          <select :value="backend" @change="changeBackend">
            <option value="fts">fts（默认）</option>
            <option value="vector">vector</option>
            <option value="hybrid">hybrid</option>
          </select>
          <div class="counts">
            <span v-for="(value, tier) in memoryCounts" :key="tier">{{ tier }}:{{ value }}</span>
          </div>
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
.kv { display: flex; justify-content: space-between; font-size: 12px; }
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
