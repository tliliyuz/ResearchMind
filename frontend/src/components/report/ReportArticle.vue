<template>
  <article ref="articleRef" class="report-article" @click="handleCitationClick">
    <div class="max-width-prose">
      <section
        v-for="section in sections"
        :id="`section-${section.id}`"
        :key="section.id"
        class="report-section"
      >
        <div class="section-content" v-html="renderedContent(section.content)"></div>
      </section>
    </div>
  </article>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { renderMarkdown, wrapCodeBlocks } from '@/utils/markdown'

const props = defineProps({
  sections: { type: Array, default: () => [] },
  highlightedIndex: { type: Number, default: null },
  selectedSectionId: { type: String, default: null },
})

const emit = defineEmits(['citation-click'])

const articleRef = ref(null)

function renderedContent(content) {
  const html = renderMarkdown(content)
  return wrapCodeBlocks(html)
}

function handleCitationClick(e) {
  const target = e.target.closest('.citation-link')
  if (!target) return
  e.preventDefault()
  const indexStr = target.getAttribute('data-evidence-index')
  if (!indexStr) return
  const firstIndex = Number(indexStr.trim().split(/\s+/)[0])
  if (Number.isNaN(firstIndex)) return
  emit('citation-click', firstIndex)
}

watch(() => props.highlightedIndex, (index) => {
  if (index == null) return
  nextTick(() => {
    if (!articleRef.value) return
    // 清除旧高亮
    articleRef.value.querySelectorAll('.citation-link.flash').forEach(el => el.classList.remove('flash'))
    // 给所有匹配的锚点添加高亮（点击 Evidence 条目时高亮正文引用位置）
    const selector = `[data-evidence-index~="${index}"]`
    const anchors = articleRef.value.querySelectorAll(selector)
    anchors.forEach(el => el.classList.add('flash'))
    // 注意：点击正文 [来源N] 时不应滚动正文，只由 EvidencePanel 滚动到对应来源条目
  })
})

// 章节导航点击后平滑滚动到对应 section
watch(() => props.selectedSectionId, (sectionId) => {
  if (!sectionId) return
  nextTick(() => {
    const el = document.getElementById(`section-${sectionId}`)
    if (el && articleRef.value?.contains(el)) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  })
})
</script>

<style scoped>
.report-article {
  width: var(--rm-report-article-width);
  overflow-y: auto;
  padding: var(--rm-space-6) var(--rm-space-4);
  background: var(--rm-bg-card);
  line-height: var(--rm-leading-relaxed);
}

.max-width-prose {
  max-width: 100%;
  margin: 0 auto;
}

.report-section {
  margin-bottom: var(--rm-space-8);
}

.report-section :deep(h1),
.report-section :deep(h2),
.report-section :deep(h3),
.report-section :deep(h4) {
  color: var(--rm-text-primary);
  font-weight: var(--rm-weight-bold);
  margin: var(--rm-space-6) 0 var(--rm-space-3) 0;
  line-height: var(--rm-leading-title);
}

.report-section :deep(h1) { font-size: var(--rm-text-2xl); }
.report-section :deep(h2) { font-size: var(--rm-text-xl); }
.report-section :deep(h3) { font-size: var(--rm-text-lg); }
.report-section :deep(h4) { font-size: var(--rm-text-base); }

.report-section :deep(p) {
  color: var(--rm-text-secondary);
  margin-bottom: var(--rm-space-3);
}

.report-section :deep(ul),
.report-section :deep(ol) {
  color: var(--rm-text-secondary);
  margin-bottom: var(--rm-space-3);
  padding-left: var(--rm-space-5);
}

.report-section :deep(li) {
  margin-bottom: var(--rm-space-1);
}

.report-section :deep(a.citation-link) {
  display: inline-block;
  background: var(--rm-evidence-highlight-bg);
  color: var(--rm-evidence-highlight-text);
  font-size: var(--rm-text-xs);
  padding: 2px 6px;
  border-radius: var(--rm-radius-xs);
  font-family: var(--rm-font-mono);
  font-weight: var(--rm-weight-semibold);
  border: 1px solid var(--rm-evidence-highlight-border);
  cursor: pointer;
  margin: 0 2px;
  transition: all var(--rm-transition-fast);
}

.report-section :deep(a.citation-link:hover) {
  background: #99F6E4;
}

.report-section :deep(a.citation-link.flash) {
  background: #FEF3C7;
  border-color: #F59E0B;
  box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.3);
  animation: flash-pulse 1s ease-in-out 2;
}

@keyframes flash-pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.1); }
}

.report-section :deep(pre) {
  background: var(--rm-bg-code);
  color: var(--rm-text-code);
  border-radius: var(--rm-radius-md);
  padding: var(--rm-space-3);
  overflow-x: auto;
  margin-bottom: var(--rm-space-3);
}

.report-section :deep(code) {
  font-family: var(--rm-font-mono);
  font-size: 0.9em;
}

.report-section :deep(:not(pre) > code) {
  background: var(--rm-code-inline-bg);
  padding: 2px 4px;
  border-radius: 4px;
}

.report-section :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: var(--rm-space-3);
}

.report-section :deep(th),
.report-section :deep(td) {
  border: 1px solid var(--rm-border);
  padding: var(--rm-space-2);
  text-align: left;
}

.report-section :deep(th) {
  background: var(--rm-bg-elevated);
  font-weight: var(--rm-weight-semibold);
}

.report-section :deep(blockquote) {
  border-left: 4px solid var(--rm-primary);
  padding-left: var(--rm-space-3);
  color: var(--rm-text-secondary);
  margin-bottom: var(--rm-space-3);
}

.code-block-wrapper {
  position: relative;
  margin-bottom: var(--rm-space-3);
}

.code-copy-btn {
  position: absolute;
  top: var(--rm-space-2);
  right: var(--rm-space-2);
  width: 28px;
  height: 28px;
  background: var(--rm-code-copy-btn-bg);
  border: none;
  border-radius: var(--rm-radius-sm);
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--rm-transition-fast);
}

.code-copy-btn:hover {
  background: var(--rm-code-copy-btn-hover-bg);
}

.code-copy-btn .fa-check {
  display: none;
}

.code-copy-btn.copied .fa-copy {
  display: none;
}

.code-copy-btn.copied .fa-check {
  display: inline;
}
</style>
