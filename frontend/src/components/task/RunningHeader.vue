<template>
  <header class="running-header">
    <div class="task-info">
      <div class="spinner-icon">
        <i class="fas fa-microscope"></i>
      </div>
      <div class="task-text">
        <h2 class="task-title" :title="title">{{ title || '未命名研究' }}</h2>
        <div class="task-meta">
          <span class="status-badge">{{ statusLabel }}</span>
          <span class="meta-dot">·</span>
          <span>当前阶段：{{ phaseText }}</span>
          <span class="meta-dot">·</span>
          <span class="elapsed-time">已用时 {{ formattedElapsed }}</span>
        </div>
      </div>
    </div>

    <button
      class="cancel-btn"
      :disabled="cancelLoading"
      @click="$emit('cancel')"
    >
      <i v-if="cancelLoading" class="fas fa-spinner fa-spin"></i>
      <i v-else class="fas fa-ban"></i>
      {{ cancelLoading ? '取消中...' : '取消研究' }}
    </button>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { formatElapsedTime } from '@/utils/format'
import { normalizePhaseKey, PHASE_LABELS } from '@/utils/phase'

const props = defineProps({
  title: { type: String, default: '' },
  status: { type: String, default: 'running' },
  currentPhase: { type: String, default: null },
  elapsedMs: { type: Number, default: 0 },
  cancelLoading: { type: Boolean, default: false },
})

defineEmits(['cancel'])

const statusLabel = computed(() => {
  const map = {
    pending: '待执行',
    running: '运行中',
  }
  return map[props.status] || props.status
})

const phaseText = computed(() => {
  const short = normalizePhaseKey(props.currentPhase)
  return short ? PHASE_LABELS[short] : '准备中'
})

const formattedElapsed = computed(() => formatElapsedTime(props.elapsedMs))
</script>

<style scoped>
.running-header {
  background: var(--rm-bg-dark-card);
  border-bottom: 1px solid var(--rm-border-dark);
  padding: var(--rm-space-4);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

.task-info {
  display: flex;
  align-items: center;
  gap: var(--rm-space-3);
  overflow: hidden;
}

.spinner-icon {
  width: 36px;
  height: 36px;
  background: rgba(20, 184, 166, 0.1);
  border: 1px solid rgba(20, 184, 166, 0.2);
  color: #2DD4BF;
  border-radius: var(--rm-radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.task-text {
  overflow: hidden;
}

.task-title {
  font-size: var(--rm-text-sm);
  font-weight: var(--rm-weight-bold);
  color: white;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin: 0;
}

.task-meta {
  font-size: var(--rm-text-2xs);
  color: var(--rm-text-inverse-secondary);
  display: flex;
  align-items: center;
  gap: var(--rm-space-1_5);
  margin-top: 2px;
}

.status-badge {
  color: #5EEAD4;
  font-weight: var(--rm-weight-semibold);
}

.meta-dot {
  color: var(--rm-text-inverse-dim);
}

.elapsed-time {
  color: #5EEAD4;
  font-family: var(--rm-font-mono);
  font-weight: var(--rm-weight-semibold);
}

.cancel-btn {
  height: 32px;
  padding: 0 12px;
  background: var(--rm-danger-light);
  color: var(--rm-danger);
  border: 1px solid var(--rm-danger-border);
  border-radius: var(--rm-radius-md);
  font-size: var(--rm-text-xs);
  font-weight: var(--rm-weight-medium);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: var(--rm-space-1);
  transition: all var(--rm-transition-fast);
  flex-shrink: 0;
  font-family: inherit;
}

.cancel-btn:hover:not(:disabled) {
  background: var(--rm-danger-border);
}

.cancel-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
