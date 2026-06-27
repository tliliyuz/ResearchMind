<template>
  <div class="pipeline-progress">
    <div class="phase-nodes">
      <template v-for="(key, idx) in PHASE_ORDER" :key="key">
        <div class="phase-connector" v-if="idx > 0" :class="connectorClass(key)"></div>
        <div class="phase-item" :class="`phase-${stateOf(key)}`">
          <div class="phase-node" :class="stateOf(key)">
            <i :class="phaseIcon(key)"></i>
          </div>
          <div class="phase-label" :class="stateOf(key)">
            {{ PHASE_LABELS[key] }}
          </div>
          <div v-if="durationOf(key)" class="phase-duration">
            {{ formatDuration(durationOf(key)) }}
          </div>
        </div>
      </template>
    </div>

    <div class="overall-progress">
      <div class="progress-header">
        <span class="progress-title">整体进度</span>
        <span class="progress-text">{{ progressText }}</span>
      </div>
      <div class="pipeline-progress-bar">
        <div class="pipeline-progress-fill" :style="{ width: progressPercent + '%' }"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { PHASE_ORDER, PHASE_LABELS, PHASE_ICONS, normalizePhaseKey } from '@/utils/phase'
import { formatDuration } from '@/utils/format'

const props = defineProps({
  phases: { type: Object, default: () => ({}) },
  progress: { type: Object, default: () => ({ completed_steps: 0, total_steps: 0, progress: 0 }) },
  phaseDurations: { type: Object, default: () => ({}) },
})

function stateOf(key) {
  const raw = props.phases[key] || 'pending'
  // taskStore 使用 'running'，UI 类名使用 'current'
  return raw === 'running' ? 'current' : raw
}

function phaseIcon(key) {
  const state = stateOf(key)
  const base = `fas ${PHASE_ICONS[key] || 'fa-circle'}`
  if (state === 'current') return `${base} fa-spin`
  return base
}

function connectorClass(key) {
  const idx = PHASE_ORDER.indexOf(key)
  if (idx <= 0) return ''
  const prevKey = PHASE_ORDER[idx - 1]
  // 前置阶段已完成或当前阶段正在进行，则连接线高亮
  if (stateOf(prevKey) === 'done' || stateOf(key) !== 'pending') {
    return 'active'
  }
  return ''
}

function durationOf(key) {
  return props.phaseDurations[key]
}

const completedSteps = computed(() => props.progress?.completed_steps || 0)

// 全局进度固定为七阶段：Planning→Search→Fetch→Rerank→Synthesis→EvidenceGraph→Render
// 分母不再随子 step 创建而增长，避免 100%→33% 的回退问题
const FIXED_TOTAL_STEPS = 7

const progressPercent = computed(() => {
  const p = props.progress?.progress
  if (p != null) return Math.round(p * 100)
  return Math.round((completedSteps.value / FIXED_TOTAL_STEPS) * 100)
})

const isPlanning = computed(() => stateOf('planning') === 'current')

const progressText = computed(() => {
  if (isPlanning.value) {
    return '任务规划中…'
  }
  return `${progressPercent.value}%（${completedSteps.value}/${FIXED_TOTAL_STEPS} 步骤）`
})
</script>

<style scoped>
.pipeline-progress {
  background: var(--rm-bg-card);
  border: 1px solid var(--rm-border);
  border-radius: var(--rm-radius-xl);
  padding: var(--rm-space-5);
  margin: var(--rm-space-4);
  box-shadow: var(--rm-shadow-sm);
}

.phase-nodes {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: var(--rm-space-5);
}

.phase-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
  position: relative;
}

.phase-node {
  width: 32px;
  height: 32px;
  border-radius: var(--rm-radius-full);
  border: 2px solid;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--rm-text-3xs);
  font-weight: var(--rm-weight-bold);
  transition: all 0.3s ease;
  position: relative;
  z-index: 10;
}

.phase-node.done {
  background: #0D9488;
  border-color: #14B8A6;
  color: white;
}

.phase-node.current {
  background: var(--rm-secondary);
  border-color: #3B82F6;
  color: white;
  animation: pulse-blue 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}

.phase-node.pending {
  background: var(--rm-bg-sidebar-active);
  border-color: var(--rm-border-darker);
  color: var(--rm-text-inverse-dim);
}

.phase-label {
  font-size: var(--rm-text-3xs);
  font-weight: var(--rm-weight-medium);
  margin-top: var(--rm-space-2);
  text-align: center;
  white-space: nowrap;
}

.phase-label.done { color: var(--rm-success); }
.phase-label.current { color: #60A5FA; font-weight: var(--rm-weight-bold); }
.phase-label.pending { color: var(--rm-text-inverse-dim); }

.phase-duration {
  font-size: var(--rm-text-3xs);
  color: var(--rm-text-tertiary);
  margin-top: 2px;
}

.phase-connector {
  flex: 1;
  height: 2px;
  background: var(--rm-border-darker);
  margin-top: 16px;
  min-width: 8px;
}

.phase-connector.active {
  background: linear-gradient(to right, #14B8A6, #3B82F6);
}

.overall-progress {
  border-top: 1px solid var(--rm-border-light);
  padding-top: var(--rm-space-4);
}

.progress-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--rm-space-2);
}

.progress-title {
  font-size: var(--rm-text-xs);
  font-weight: var(--rm-weight-semibold);
  color: var(--rm-text-primary);
}

.progress-text {
  font-size: var(--rm-text-2xs);
  color: var(--rm-text-secondary);
  font-family: var(--rm-font-mono);
}

.pipeline-progress-bar {
  width: 100%;
  height: 8px;
  background: var(--rm-bg-sidebar-active);
  border-radius: 9999px;
  overflow: hidden;
}

.pipeline-progress-fill {
  height: 100%;
  background: linear-gradient(to right, #14B8A6, #3B82F6);
  border-radius: 9999px;
  transition: width 0.3s ease;
}

@keyframes pulse-blue {
  0%, 100% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.4); }
  50% { box-shadow: 0 0 0 8px rgba(59, 130, 246, 0); }
}
</style>
