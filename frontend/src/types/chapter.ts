/**
 * 章节类型定义（对齐后端 ChapterView / ChapterCreate / ChapterUpdate）
 */

export type ChapterStatus = 'draft' | 'writing' | 'done'

export interface ChapterView {
  chapter_id: string
  project_id: string
  title: string
  outline: string
  position: number
  status: ChapterStatus
}

export interface ChapterCreate {
  title: string
  outline?: string
  position?: number
  status?: ChapterStatus
}

export interface ChapterUpdate {
  title?: string
  outline?: string
  position?: number
  status?: ChapterStatus
}

export const CHAPTER_STATUS_META: Record<ChapterStatus, { label: string; color: string }> = {
  draft: { label: '草稿', color: '#95a5a6' },
  writing: { label: '写作中', color: '#f39c12' },
  done: { label: '完成', color: '#2ecc71' },
}
