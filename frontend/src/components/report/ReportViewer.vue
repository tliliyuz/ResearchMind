<template>
  <div class="report-viewer">
    <header class="report-header">
      <div class="report-title-wrap">
        <h1 class="report-title">{{ title }}</h1>
        <div class="report-meta">
          <span v-if="completedAt">完成时间：{{ formatDateTime(completedAt) }}</span>
          <span class="meta-dot">·</span>
          <el-tooltip content="成功获取的网页来源数量" placement="bottom">
            <span>{{ totalEvidence }}个参考来源</span>
          </el-tooltip>
        </div>
      </div>
      <button class="back-btn" @click="$emit('back')">
        <i class="fas fa-arrow-left"></i>
        返回新建研究
      </button>
    </header>

    <div class="report-body">
      <template v-if="reportStore.loading">
        <div class="section-nav section-nav-skeleton">
          <div class="section-nav-title">章节导航</div>
          <div v-for="n in 6" :key="n" class="skeleton-line skeleton-section"></div>
        </div>

        <div class="report-article report-article-loading">
          <div class="spinner-wrap">
            <i class="fas fa-spinner fa-spin spinner-icon"></i>
            <span class="spinner-text">正在加载报告…</span>
          </div>
        </div>

        <aside class="report-side-panel report-side-panel-skeleton">
          <div class="panel-header">
            <span class="panel-title">来源图谱</span>
          </div>
          <div v-for="n in 4" :key="n" class="skeleton-card">
            <div class="skeleton-line skeleton-card-title"></div>
            <div class="skeleton-line skeleton-card-content"></div>
            <div class="skeleton-line skeleton-card-content short"></div>
          </div>
        </aside>
      </template>

      <template v-else>
        <SectionNav
          :sections="reportStore.sections"
          :active-id="reportStore.selectedSectionId"
          :evidence="reportStore.evidence"
          @select="reportStore.selectSection"
        />

        <ReportArticle
          :sections="reportStore.sections"
          :highlighted-index="reportStore.highlightedEvidenceIndex"
          :selected-section-id="reportStore.selectedSectionId"
          @citation-click="reportStore.highlightEvidence"
        />

        <aside class="report-side-panel">
          <EvidencePanel
            :evidence="reportStore.filteredEvidence"
            :highlighted-index="reportStore.highlightedEvidenceIndex"
            :filter-section-id="reportStore.evidenceFilterSectionId"
            @select="reportStore.highlightEvidence"
            @filter="reportStore.setEvidenceFilter"
          />
          <TracePanel :trace="reportStore.trace" />
        </aside>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, watch } from 'vue'
import { useReportStore } from '@/stores/report'
import { formatDateTime } from '@/utils/format'
import SectionNav from './SectionNav.vue'
import ReportArticle from './ReportArticle.vue'
import EvidencePanel from './EvidencePanel.vue'
import TracePanel from './TracePanel.vue'

const props = defineProps({
  task: { type: Object, required: true },
})

const emit = defineEmits(['back'])

const reportStore = useReportStore()

const title = computed(() => reportStore.report?.report?.title || props.task?.topic || '研究报告')
const completedAt = computed(() => props.task?.completed_at)
const totalSources = computed(() => props.task?.total_sources || 0)
const totalEvidence = computed(() => props.task?.total_evidence || 0)

// 进入完成态时自动加载报告
watch(() => props.task?.task_id, (taskId) => {
  if (taskId) {
    reportStore.fetch(taskId)
  }
}, { immediate: true })
</script>

<style scoped>
.report-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--rm-bg-page);
}

.report-header {
  background: var(--rm-bg-card);
  border-bottom: 1px solid var(--rm-border);
  padding: var(--rm-space-2) var(--rm-space-1);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

.report-title-wrap {
  overflow: hidden;
}

.report-title {
  font-size: var(--rm-text-lg);
  font-weight: var(--rm-weight-bold);
  color: var(--rm-text-primary);
  margin: 0 0 var(--rm-space-1) 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.report-meta {
  font-size: var(--rm-text-2xs);
  color: var(--rm-text-tertiary);
  display: flex;
  align-items: center;
  gap: var(--rm-space-1_5);
}

.meta-dot {
  color: var(--rm-border-darker);
}

.back-btn {
  height: 34px;
  padding: 0 14px;
  background: var(--rm-bg-elevated);
  color: var(--rm-text-secondary);
  border: 1px solid var(--rm-border);
  border-radius: var(--rm-radius-sm);
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

.back-btn:hover {
  background: var(--rm-border-light);
}

.report-body {
  flex: 1;
  display: grid;
  grid-template-columns: var(--rm-section-nav-width) var(--rm-report-article-width) var(--rm-evidence-panel-width);
  overflow: hidden;
}

.report-side-panel {
  display: flex;
  flex-direction: column;
  background: var(--rm-bg-page);
  border-left: 1px solid var(--rm-border);
  overflow: hidden;
  padding: var(--rm-space-3);
}

/* EvidencePanel 占满侧栏剩余空间，内容在内部滚动，不挤占 TracePanel */
.report-side-panel :deep(.evidence-panel) {
  flex: 1 1 auto;
  min-height: 0;
  width: 100%;
  border-left: none;
  padding: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.report-side-panel :deep(.evidence-list) {
  flex: 1;
  overflow-y: auto;
  margin: 0 calc(-1 * var(--rm-space-3));
  padding: 0 var(--rm-space-3);
}

/* TracePanel 不收缩，始终保持在侧栏底部 */
.report-side-panel :deep(.trace-panel) {
  flex: 0 0 auto;
  margin-top: var(--rm-space-3);
}

/* ===== 加载态骨架屏 ===== */

.section-nav-skeleton {
  display: flex;
  flex-direction: column;
}

.skeleton-line {
  background: var(--rm-bg-elevated);
  border-radius: var(--rm-radius-sm);
  animation: skeleton-pulse 1.6s ease-in-out infinite;
}

.skeleton-section {
  height: 28px;
  margin-bottom: var(--rm-space-1_5);
  width: 100%;
}

.skeleton-section:nth-child(odd) {
  width: 85%;
}

.report-article-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--rm-bg-card);
}

.spinner-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--rm-space-3);
  color: var(--rm-text-tertiary);
}

.spinner-icon {
  font-size: 32px;
  color: var(--rm-primary);
}

.spinner-text {
  font-size: var(--rm-text-sm);
  color: var(--rm-text-secondary);
}

.report-side-panel-skeleton {
  overflow-y: auto;
}

.report-side-panel-skeleton .panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--rm-space-3);
}

.report-side-panel-skeleton .panel-title {
  font-size: var(--rm-text-xs);
  font-weight: var(--rm-weight-bold);
  color: var(--rm-text-primary);
}

.skeleton-card {
  background: var(--rm-bg-card);
  border: 1px solid var(--rm-border);
  border-radius: var(--rm-radius-lg);
  padding: var(--rm-space-3);
  margin-bottom: var(--rm-space-3);
}

.skeleton-card-title {
  height: 16px;
  width: 40%;
  margin-bottom: var(--rm-space-3);
}

.skeleton-card-content {
  height: 12px;
  width: 100%;
  margin-bottom: var(--rm-space-2);
}

.skeleton-card-content.short {
  width: 60%;
}

@keyframes skeleton-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}
</style>
