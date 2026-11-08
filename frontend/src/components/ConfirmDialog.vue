<script setup lang="ts">
/**
 * 统一确认弹窗：替代原生 confirm 与直接执行的危险操作
 */
withDefaults(
  defineProps<{
    show: boolean
    title: string
    message: string
    confirmText?: string
    cancelText?: string
    danger?: boolean
  }>(),
  { confirmText: '确定', cancelText: '取消', danger: true },
)

defineEmits<{
  (e: 'confirm'): void
  (e: 'cancel'): void
}>()
</script>

<template>
  <div v-if="show" class="dialog-overlay" @click.self="$emit('cancel')">
    <div class="dialog confirm-dialog">
      <h3>{{ title }}</h3>
      <p class="confirm-message">{{ message }}</p>
      <div class="form-actions">
        <button class="btn btn-secondary" @click="$emit('cancel')">{{ cancelText }}</button>
        <button
          class="btn"
          :class="danger ? 'btn-danger' : 'btn-primary'"
          @click="$emit('confirm')"
        >{{ confirmText }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.confirm-dialog {
  width: 420px;
  max-width: 90vw;
}
.confirm-message {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
  white-space: pre-wrap;
}
</style>
