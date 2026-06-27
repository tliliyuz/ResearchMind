<template>
  <div class="trace-panel">
    <div class="trace-header" @click="expanded = !expanded">
      <span class="trace-title">Trace 执行摘要</span>
      <i :class="['fas', expanded ? 'fa-chevron-down' : 'fa-chevron-right']"></i>
    </div>

    <div v-show="expanded" class="trace-body">
      <div v-for="key in PHASE_ORDER" :key="key" class="trace-row">
        <div class="stage-main">
          <span class="stage-name">{{ PHASE_LABELS[key] }}</span>
          <span class="stage-detail">{{ stageDetail(key) }}</span>
          <span class="stage-time">{{ formatDuration(stageDuration(key)) }}</span>
        </div>
        <div class="stage-bar-bg">
          <div class="stage-bar" :style="{ width: stageBarWidth(key) }"></div>
        </div>
      </div>

      <div class="trace-total">
        <span>总计</span>
        <span class="value">{{ formatDuration(totalDuration) }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { PHASE_ORDER, PHASE_LABELS } from '@/utils/phase'
import { formatDuration } from '@/utils/format'

const props = defineProps({
  trace: { type: Object, default: () => null },
})

const expanded = ref(false)

function stageData(key) {
  return props.trace?.[key] || null
}

function stageDuration(key) {
  return stageData(key)?.duration_ms
}

function stageBarWidth(key) {
  const total = totalDuration.value
  if (!total) return '0%'
  const ms = stageDuration(key)
  if (ms == null || ms <= 0) return '0%'
  return `${Math.min(100, (ms / total) * 100)}%`
}

function stageDetail(key) {
  const data = stageData(key)
  if (!data) return ''
  switch (key) {
    case 'search':
      if (data.success_count != null && data.total_results != null) {
        return `${data.success_count}/${data.total_results}`
      }
      break
    case 'fetch':
      if (data.success_count != null && data.total_urls != null) {
        return `${data.success_count}/${data.total_urls}`
      }
      break
    case 'rerank':
      if (data.bm25_candidates != null && data.llm_reranked != null) {
        return `${data.bm25_candidates}→${data.llm_reranked}`
      }
      break
    case 'evidence_graph':
      if (data.evidence_count != null) return `${data.evidence_count}`
      break
    case 'render':
      if (data.sections_count != null && data.citations_count != null) {
        return `${data.sections_count}/${data.citations_count}`
      }
      break
  }
  return ''
}

const totalDuration = computed(() => {
  if (!props.trace) return null
  return PHASE_ORDER.reduce((sum, key) => {
    const ms = stageDuration(key)
    return ms != null ? sum + ms : sum
  }, 0)
})
</script>

<style scoped>
.trace-panel {
  background: var(--rm-bg-code);
  color: var(--rm-text-inverse-secondary);
  border-radius: var(--rm-radius-md);
  padding: var(--rm-space-3);
  font-size: var(--rm-text-3xs);
  font-family: var(--rm-font-mono);
  box-shadow: var(--rm-shadow-inner);
  margin-top: var(--rm-space-4);
}

.trace-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  user-select: none;
}

.trace-title {
  font-weight: var(--rm-weight-semibold);
  color: var(--rm-text-inverse);
}

.trace-body {
  margin-top: var(--rm-space-2);
}

.trace-row {
  display: flex;
  flex-direction: column;
  padding: 2px 0;
  gap: 2px;
}

.stage-main {
  display: flex;
  justify-content: space-between;
  gap: var(--rm-space-2);
}

.stage-name {
  color: var(--rm-text-inverse-dim);
  flex: 1;
}

.stage-detail {
  color: var(--rm-text-inverse-dim);
  text-align: right;
}

.stage-time {
  color: #2DD4BF;
  width: 50px;
  text-align: right;
  flex-shrink: 0;
}

.stage-bar-bg {
  height: 3px;
  background: var(--rm-border-dark);
  border-radius: 2px;
  overflow: hidden;
}

.stage-bar {
  height: 100%;
  background: var(--rm-primary);
  border-radius: 2px;
  transition: width 0.3s ease;
}

.trace-total {
  border-top: 1px solid var(--rm-border-dark);
  padding-top: var(--rm-space-1);
  margin-top: var(--rm-space-1);
  font-weight: var(--rm-weight-bold);
  color: var(--rm-text-inverse);
  display: flex;
  justify-content: space-between;
}

.trace-total .value {
  color: #5EEAD4;
}
</style>
