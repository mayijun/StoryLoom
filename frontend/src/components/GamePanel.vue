<script setup lang="ts">
/**
 * 游戏 / 扮演模式面板（M0）
 * 对话框 + 选项 + backlog + 存读档 + 模式切换 + 记忆后端切换
 */
import { ref, onMounted, nextTick } from 'vue'
import { useApi } from '../composables/useApi'

const props = defineProps<{ projectId: string; projectTitle?: string }>()
const emit = defineEmits<{ close: [] }>()

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
const backend = ref('fts')
const memoryCounts = ref<Record<string, number>>({})
const extensions = ref<any[]>([])
const showDirectives = ref(true)
const logEl = ref<HTMLElement | null>(null)

async function refreshState() {
  const res = await api.getGameState(props.projectId, INSTANCE_ID)
  state.value = res.data.state
  mode.value = res.data.state.mode
  backend.value = res.data.memory.backend
  memoryCounts.value = res.data.memory.counts || {}
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
    await refreshSaves()
    await refreshExtensions()
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

async function toggleMode() {
  const target = mode.value === 'game' ? 'director' : 'game'
  try {
    const res = await api.switchGameMode(props.projectId, target, INSTANCE_ID)
    state.value = res.data.state
    mode.value = res.data.mode
    backlog.value.push({
      role: 'system',
      text: `已切换到${target === 'game' ? '游戏' : '导演'}模式；切换前已落 checkpoint。`,
    })
    await scrollDown()
  } catch (err: any) {
    statusText.value = err?.response?.data?.detail || '模式切换失败。'
  }
}

async function changeBackend(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  try {
    const res = await api.patchMemory(props.projectId, value)
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

async function saveGame() {
  try {
    await api.createGameSave(props.projectId, {
      instance_id: INSTANCE_ID,
      label: `第${state.value?.turn ?? 0}回合`,
    })
    await refreshSaves()
  } catch {
    statusText.value = '存档失败。'
  }
}

async function loadGame(saveId: string) {
  try {
    await api.loadGameSave(props.projectId, saveId, INSTANCE_ID)
    await refreshState()
    backlog.value = [{ role: 'system', text: '已读档，世界恢复到存档时点。' }]
    await scrollDown()
  } catch {
    statusText.value = '读档失败。'
  }
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
        <button class="btn btn-secondary btn-sm" @click="saveGame">💾 存档</button>
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
                v-if="showDirectives && entry.directives && entry.directives.length"
                class="directives"
              >
                <span
                  v-for="(directive, dIndex) in entry.directives"
                  :key="dIndex"
                  class="chip"
                  :title="JSON.stringify(directive.params || {})"
                >{{ directive.kind }}</span>
              </div>
            </div>
          </div>
          <div v-if="busy" class="entry narrator">
            <div class="bubble">世界正在回应…</div>
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
          <div class="side-label">存档</div>
          <div v-if="!saves.length" class="empty">暂无存档</div>
          <div v-for="save in saves" :key="save.save_id" class="save-item">
            <div>
              <div>{{ save.label }}</div>
              <small>{{ save.mode }} · {{ save.created_at?.slice(0, 19) }}</small>
            </div>
            <button class="btn btn-secondary btn-sm" @click="loadGame(save.save_id)">读取</button>
          </div>
        </div>

        <div class="side-block">
          <label class="toggle">
            <input v-model="showDirectives" type="checkbox" />
            显示舞台指令
          </label>
        </div>
      </aside>
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
.directives { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 4px; }
.chip {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 8px;
  background: rgba(91, 141, 239, 0.18);
  color: var(--accent, #5b8def);
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
}
.save-item small { color: var(--text-secondary, #9aa0aa); }
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
