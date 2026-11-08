<script setup lang="ts">
/**
 * 章节管理面板（左侧栏「章节」标签）
 * 章节 CRUD + 排序 + 场景归属/编辑/重跑/删除
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useChapterStore } from '../stores/chapterStore'
import { useSceneStore } from '../stores/sceneStore'
import { CHAPTER_STATUS_META } from '../types/chapter'
import type { ChapterView, ChapterCreate, ChapterUpdate, ChapterStatus } from '../types/chapter'
import ConfirmDialog from './ConfirmDialog.vue'

const props = defineProps<{ projectId: string }>()

const emit = defineEmits<{
  (e: 'select-scene', sceneId: string): void
  (e: 'select-chapter', chapterId: string): void
}>()

const chapterStore = useChapterStore()
const sceneStore = useSceneStore()

// ---- 章节展开状态 ----
const expanded = ref<Record<string, boolean>>({})
function toggleExpand(cid: string) {
  expanded.value = { ...expanded.value, [cid]: !expanded.value[cid] }
}

// ---- 章节对话框 ----
const showChapterDialog = ref(false)
const editingChapterId = ref<string | null>(null)
const chapterForm = ref<ChapterCreate>({ title: '', outline: '', status: 'draft' })

function openCreateChapter() {
  editingChapterId.value = null
  chapterForm.value = { title: '', outline: '', status: 'draft' }
  showChapterDialog.value = true
}

function openEditChapter(ch: ChapterView) {
  editingChapterId.value = ch.chapter_id
  chapterForm.value = { title: ch.title, outline: ch.outline, status: ch.status }
  showChapterDialog.value = true
}

async function handleSaveChapter() {
  if (!chapterForm.value.title.trim()) return
  if (editingChapterId.value) {
    const patch: ChapterUpdate = {
      title: chapterForm.value.title,
      outline: chapterForm.value.outline,
      status: chapterForm.value.status as ChapterStatus,
    }
    await chapterStore.updateChapter(props.projectId, editingChapterId.value, patch)
  } else {
    await chapterStore.addChapter(props.projectId, {
      title: chapterForm.value.title,
      outline: chapterForm.value.outline || '',
      status: chapterForm.value.status as ChapterStatus,
    })
  }
  showChapterDialog.value = false
}

// ---- 删除章节 ----
const deletingChapterId = ref<string | null>(null)
function openDeleteChapter(ch: ChapterView) {
  deletingChapterId.value = ch.chapter_id
}
async function confirmDeleteChapter() {
  if (!deletingChapterId.value) return
  await chapterStore.removeChapter(props.projectId, deletingChapterId.value)
  // 删除章节后其场景自动变未归属（后端 SET NULL），刷新场景
  await sceneStore.fetchScenes(props.projectId)
  deletingChapterId.value = null
}

// ---- 章节拖拽排序 ----
const dragChapterIndex = ref<number | null>(null)
async function handleChapterDrop(to: number) {
  const from = dragChapterIndex.value
  dragChapterIndex.value = null
  if (from === null || from === to) return
  const list = [...chapterStore.chapters]
  const [moved] = list.splice(from, 1)
  list.splice(to, 0, moved)
  await chapterStore.reorderChapters(props.projectId, list)
}

// ---- 场景正文：交给主舞台编辑 ----
function openProse(sid: string) {
  emit('select-scene', sid)
}

// ---- 场景重跑（统一确认弹窗）----
const regeneratingId = ref<string | null>(null)
const pendingRegenerateId = ref<string | null>(null)

function handleRegenerate(sid: string) {
  pendingRegenerateId.value = sid
}

async function confirmRegenerate() {
  const sid = pendingRegenerateId.value
  pendingRegenerateId.value = null
  if (!sid) return
  regeneratingId.value = sid
  try {
    await sceneStore.regenerateScene(props.projectId, sid)
  } finally {
    regeneratingId.value = null
  }
}

// ---- 场景删除 ----
const deletingSceneId = ref<string | null>(null)
function openDeleteScene(sid: string) {
  deletingSceneId.value = sid
}
async function confirmDeleteScene() {
  if (!deletingSceneId.value) return
  await sceneStore.removeScene(props.projectId, deletingSceneId.value)
  deletingSceneId.value = null
}

// ---- 场景归属 ----
async function handleAssign(sid: string, chapterId: string) {
  await sceneStore.assignScene(props.projectId, sid, chapterId || null)
}
async function handleUnassign(sid: string) {
  await sceneStore.unassignScene(props.projectId, sid)
}

// ---- 统计 ----
const totalScenes = computed(() => sceneStore.scenes.length)
const unassignedCount = computed(() => sceneStore.unassignedScenes.length)

function scenesOfChapter(cid: string) {
  return sceneStore.scenes.filter(s => s.chapter_id === cid)
}

function sceneCountOf(cid: string) {
  return sceneStore.sceneCountByChapter[cid] || 0
}

function qualityColor(score: number | null) {
  if (score == null) return 'var(--text-secondary)'
  return score < 0.6 ? 'var(--error)' : 'var(--success)'
}

function formatTime(ms: number | null) {
  if (ms == null) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}

// ---- 生命周期 ----
onMounted(load)
watch(() => props.projectId, load)

async function load() {
  if (!props.projectId) return
  await Promise.all([
    chapterStore.fetchChapters(props.projectId),
    sceneStore.fetchScenes(props.projectId),
  ])
}
</script>

<template>
  <div class="chapter-panel">
    <!-- 头部 -->
    <div class="panel-head">
      <span class="panel-title">📚 章节结构</span>
      <span class="panel-stats">
        共 {{ chapterStore.chapters.length }} 章 · {{ unassignedCount }} 未归属
      </span>
      <button class="btn btn-sm btn-primary" @click="openCreateChapter">＋ 新建</button>
    </div>

    <div class="chapter-list">
      <!-- 空状态 -->
      <div v-if="!chapterStore.chapters.length && !chapterStore.loading" class="empty">
        暂无章节，点击「新建」开始组织结构
      </div>

      <!-- 章节卡片 -->
      <div
        v-for="(ch, idx) in chapterStore.chapters"
        :key="ch.chapter_id"
        class="chapter-card"
        :class="{ dragging: dragChapterIndex === idx }"
        draggable="true"
        @dragstart="dragChapterIndex = idx"
        @dragend="dragChapterIndex = null"
        @dragover.prevent
        @drop.prevent="handleChapterDrop(idx)"
      >
        <div class="chapter-head" @click="emit('select-chapter', ch.chapter_id)">
          <button class="expand-btn" @click="toggleExpand(ch.chapter_id)">
            {{ expanded[ch.chapter_id] ? '▾' : '▸' }}
          </button>
          <span class="chapter-title">第{{ idx + 1 }}章 {{ ch.title }}</span>
          <span class="status-tag" :style="{ background: CHAPTER_STATUS_META[ch.status].color }">
            {{ CHAPTER_STATUS_META[ch.status].label }}
          </span>
          <span class="scene-count">{{ sceneCountOf(ch.chapter_id) }}场景</span>
          <div class="chapter-actions">
            <button class="btn-icon" @click.stop="openEditChapter(ch)" title="编辑">✎</button>
            <button class="btn-icon danger" @click.stop="openDeleteChapter(ch)" title="删除">✕</button>
          </div>
        </div>

        <div v-if="ch.outline" class="chapter-outline">大纲：{{ ch.outline }}</div>

        <!-- 展开的场景列表 -->
        <div v-if="expanded[ch.chapter_id]" class="scene-list">
          <div v-if="!scenesOfChapter(ch.chapter_id).length" class="scene-empty">
            该章节暂无场景
          </div>
          <div v-for="scene in scenesOfChapter(ch.chapter_id)" :key="scene.scene_id" class="scene-row">
            <div class="scene-brief">{{ scene.brief || '(无 brief)' }}</div>
            <div class="scene-meta">
              <span :style="{ color: qualityColor(scene.quality_score) }">
                {{ scene.quality_score != null ? scene.quality_score.toFixed(2) : '—' }}
              </span>
              <span>{{ formatTime(scene.duration_ms) }}</span>
            </div>
            <div class="scene-actions">
              <button class="btn btn-xs btn-secondary" @click="openProse(scene.scene_id)">正文</button>
              <button
                class="btn btn-xs btn-secondary"
                :disabled="regeneratingId === scene.scene_id"
                @click="handleRegenerate(scene.scene_id)"
              >{{ regeneratingId === scene.scene_id ? '…' : '重跑' }}</button>
              <button class="btn btn-xs btn-secondary" @click="handleUnassign(scene.scene_id)">移出</button>
            </div>
          </div>
        </div>
      </div>

      <!-- 未归属场景 -->
      <div v-if="unassignedCount > 0" class="unassigned-block">
        <div class="unassigned-title">📌 未归属场景（{{ unassignedCount }}）</div>
        <div v-for="scene in sceneStore.unassignedScenes" :key="scene.scene_id" class="scene-row">
          <div class="scene-brief">{{ scene.brief || '(无 brief)' }}</div>
          <div class="scene-meta">
            <span :style="{ color: qualityColor(scene.quality_score) }">
              {{ scene.quality_score != null ? scene.quality_score.toFixed(2) : '—' }}
            </span>
          </div>
          <div class="scene-actions">
            <select
              class="assign-select"
              :value="''"
              @change="(e) => handleAssign(scene.scene_id, (e.target as HTMLSelectElement).value)"
            >
              <option value="" disabled>归属到…</option>
              <option v-for="ch in chapterStore.chapters" :key="ch.chapter_id" :value="ch.chapter_id">
                {{ ch.title }}
              </option>
            </select>
            <button class="btn btn-xs btn-secondary" @click="openProse(scene.scene_id)">正文</button>
            <button
              class="btn btn-xs btn-secondary"
              :disabled="regeneratingId === scene.scene_id"
              @click="handleRegenerate(scene.scene_id)"
            >{{ regeneratingId === scene.scene_id ? '…' : '重跑' }}</button>
            <button class="btn btn-xs btn-secondary danger" @click="openDeleteScene(scene.scene_id)">删除</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 新建/编辑章节对话框 -->
    <div v-if="showChapterDialog" class="dialog-overlay" @click.self="showChapterDialog = false">
      <div class="dialog">
        <h3>{{ editingChapterId ? '编辑章节' : '新建章节' }}</h3>
        <div class="form-group">
          <label>标题</label>
          <input v-model="chapterForm.title" placeholder="例：初入江湖" autofocus />
        </div>
        <div class="form-group">
          <label>大纲</label>
          <textarea v-model="chapterForm.outline" rows="3" placeholder="本章大致内容…"></textarea>
        </div>
        <div class="form-group">
          <label>状态</label>
          <select v-model="chapterForm.status">
            <option value="draft">草稿</option>
            <option value="writing">写作中</option>
            <option value="done">完成</option>
          </select>
        </div>
        <div class="form-actions">
          <button class="btn btn-secondary" @click="showChapterDialog = false">取消</button>
          <button class="btn btn-primary" :disabled="!chapterForm.title.trim()" @click="handleSaveChapter">
            {{ editingChapterId ? '保存' : '创建' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 删除章节确认 -->
    <div v-if="deletingChapterId" class="dialog-overlay" @click.self="deletingChapterId = null">
      <div class="dialog">
        <h3>删除章节</h3>
        <p>该章节下的场景将变为「未归属」，不会丢失。确定删除？</p>
        <div class="form-actions">
          <button class="btn btn-secondary" @click="deletingChapterId = null">取消</button>
          <button class="btn btn-primary" @click="confirmDeleteChapter">删除</button>
        </div>
      </div>
    </div>

    <!-- 删除场景确认 -->
    <div v-if="deletingSceneId" class="dialog-overlay" @click.self="deletingSceneId = null">
      <div class="dialog">
        <h3>删除场景</h3>
        <p>场景正文将被永久删除，确定？</p>
        <div class="form-actions">
          <button class="btn btn-secondary" @click="deletingSceneId = null">取消</button>
          <button class="btn btn-primary" @click="confirmDeleteScene">删除</button>
        </div>
      </div>
    </div>

    <!-- 场景正文由主舞台编辑，此处不再弹窗 -->

    <!-- 重跑确认 -->
    <ConfirmDialog
      :show="!!pendingRegenerateId"
      title="重跑场景"
      message="重跑将用原 brief 重新生成正文，并覆盖当前正文。此操作暂不支持恢复，确定继续？"
      confirm-text="重跑"
      @confirm="confirmRegenerate"
      @cancel="pendingRegenerateId = null"
    />
  </div>
</template>

<style scoped>
.chapter-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.panel-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.panel-title { font-weight: 600; font-size: 14px; }
.panel-stats { font-size: 11px; color: var(--text-secondary); flex: 1; }
.chapter-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}
.empty {
  text-align: center;
  color: var(--text-secondary);
  padding: 40px 16px;
  font-size: 13px;
}
.chapter-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 8px;
  background: var(--bg-input);
}
.chapter-card.dragging { opacity: 0.4; }
.chapter-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  cursor: grab;
}
.expand-btn {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
  padding: 0;
  width: 16px;
}
.chapter-title {
  font-size: 13px;
  font-weight: 500;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.status-tag {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 8px;
  color: #fff;
  flex-shrink: 0;
}
.scene-count {
  font-size: 11px;
  color: var(--text-secondary);
  flex-shrink: 0;
}
.chapter-actions { display: flex; gap: 2px; flex-shrink: 0; }
.btn-icon {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 13px;
  padding: 2px 4px;
  border-radius: 4px;
}
.btn-icon:hover { background: var(--bg-hover, rgba(255,255,255,0.08)); }
.btn-icon.danger { color: var(--error); }
.chapter-outline {
  font-size: 11px;
  color: var(--text-secondary);
  padding: 0 10px 8px 32px;
  line-height: 1.4;
}
.scene-list {
  border-top: 1px solid var(--border);
  padding: 6px 10px;
}
.scene-empty {
  font-size: 11px;
  color: var(--text-secondary);
  padding: 8px 0;
  text-align: center;
}
.scene-row {
  padding: 6px 0;
  border-bottom: 1px dashed var(--border);
}
.scene-row:last-child { border-bottom: none; }
.scene-brief {
  font-size: 12px;
  line-height: 1.4;
  margin-bottom: 4px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.scene-meta {
  display: flex;
  gap: 10px;
  font-size: 11px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}
.scene-actions {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.btn-xs {
  font-size: 11px;
  padding: 2px 8px;
}
.btn-xs.danger { color: var(--error); }
.assign-select {
  font-size: 11px;
  padding: 2px 6px;
  background: var(--bg-input);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: 4px;
}
.unassigned-block {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 2px solid var(--border);
}
.unassigned-title {
  font-size: 12px;
  color: var(--accent);
  margin-bottom: 6px;
  font-weight: 500;
}

/* 对话框（复用全局 .dialog 样式的覆盖） */
.dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.5);
}
.dialog {
  width: 420px;
  max-width: 90vw;
  padding: 20px;
  border-radius: 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.dialog h3 { font-size: 16px; }
.dialog p { font-size: 13px; color: var(--text-secondary); }
.form-group { display: flex; flex-direction: column; gap: 4px; }
.form-group label { font-size: 12px; color: var(--text-secondary); }
.form-group input,
.form-group textarea,
.form-group select {
  background: var(--bg-input);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 13px;
  font-family: inherit;
}
.form-group textarea { resize: vertical; }
.form-actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
