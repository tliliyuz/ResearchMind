<template>
  <div class="canceled-card">
    <div class="card-body">
      <div class="card-content">
        <div class="canceled-icon">
          <i class="fas fa-ban"></i>
        </div>

        <h2 class="canceled-title">研究已取消</h2>
        <p class="canceled-topic">{{ topic }}</p>

        <div v-if="completedPhases.length > 0" class="completed-summary">
          <div class="summary-title">已完成阶段</div>
          <div class="summary-list">
            <div
              v-for="phase in completedPhases"
              :key="phase.key"
              class="summary-item"
            >
              <i class="fas fa-check-circle"></i>
              <span>{{ PHASE_LABELS[phase.key] }}</span>
              <span v-if="phase.duration" class="summary-duration">{{ formatDuration(phase.duration) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="card-footer">
      <button class="back-btn" @click="$emit('back')">
        <i class="fas fa-arrow-left"></i>
        返回新建研究
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { PHASE_ORDER, PHASE_LABELS } from '@/utils/phase'
import { formatDuration } from '@/utils/format'

const props = defineProps({
  topic: { type: String, default: '' },
  phases: { type: Object, default: () => ({}) },
  phaseDurations: { type: Object, default: () => ({}) },
})

defineEmits(['back'])

const completedPhases = computed(() => {
  return PHASE_ORDER.filter(key => props.phases[key] === 'done').map(key => ({
    key,
    duration: props.phaseDurations[key] || null,
  }))
})
</script>

<style scoped>
.canceled-card {
  width: 560px;
  max-width: calc(100% - var(--rm-space-8));
  min-height: 520px;
  max-height: 720px;
  background: var(--rm-bg-card);
  border: 1px solid var(--rm-border);
  border-radius: var(--rm-radius-xl);
  box-shadow: var(--rm-shadow-sm);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.card-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  padding: var(--rm-space-8) var(--rm-space-8) 0;
  overflow-y: auto;
  min-height: 0;
}

.card-content {
  width: 100%;
  text-align: center;
}

.card-footer {
  flex-shrink: 0;
  padding: var(--rm-space-6) var(--rm-space-8) var(--rm-space-8);
  text-align: center;
}

.canceled-icon {
  width: 72px;
  height: 72px;
  background: var(--rm-bg-elevated);
  color: var(--rm-text-secondary);
  border-radius: var(--rm-radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto var(--rm-space-5);
  font-size: 28px;
}

.canceled-title {
  font-size: var(--rm-text-2xl);
  font-weight: var(--rm-weight-bold);
  color: var(--rm-text-primary);
  margin: 0 0 var(--rm-space-3) 0;
}

.canceled-topic {
  font-size: var(--rm-text-lg);
  font-weight: var(--rm-weight-medium);
  color: var(--rm-text-primary);
  margin: 0 0 var(--rm-space-5) 0;
}

.completed-summary {
  text-align: left;
  background: var(--rm-bg-page);
  border: 1px solid var(--rm-border-light);
  border-radius: var(--rm-radius-lg);
  padding: var(--rm-space-4);
  margin: 0 auto var(--rm-space-6) auto;
  max-width: 420px;
}

.summary-title {
  font-size: var(--rm-text-xs);
  font-weight: var(--rm-weight-semibold);
  color: var(--rm-text-primary);
  margin-bottom: var(--rm-space-2);
}

.summary-item {
  display: flex;
  align-items: center;
  gap: var(--rm-space-2);
  font-size: var(--rm-text-xs);
  color: var(--rm-text-secondary);
  padding: var(--rm-space-1) 0;
}

.summary-item i {
  color: var(--rm-success);
}

.summary-duration {
  margin-left: auto;
  color: var(--rm-text-tertiary);
  font-family: var(--rm-font-mono);
}

.back-btn {
  height: 40px;
  padding: 0 24px;
  background: var(--rm-bg-elevated);
  color: var(--rm-text-secondary);
  border: 1px solid var(--rm-border);
  border-radius: var(--rm-radius-sm);
  font-size: var(--rm-text-body);
  font-weight: var(--rm-weight-medium);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: var(--rm-space-1_5);
  transition: all var(--rm-transition-fast);
  font-family: inherit;
}

.back-btn:hover {
  background: var(--rm-border-light);
}
</style>
