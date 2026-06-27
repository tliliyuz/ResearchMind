import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as researchApi from '@/api/research'
import { PHASE_ORDER } from '@/utils/phase'

/**
 * 报告状态管理
 *
 * 管理已完成任务的研究报告：章节列表、Evidence Graph、Trace 摘要、
 * 章节导航高亮、Evidence 双向联动高亮、按章节筛选。
 */
export const useReportStore = defineStore('report', () => {
  // ========== 状态 ==========

  /** 原始报告数据 */
  const report = ref(null)

  /** 加载状态 */
  const loading = ref(false)

  /** 错误对象 */
  const error = ref(null)

  /** 规范化后的章节列表 */
  const sections = ref([])

  /** 规范化后的 Evidence 列表 */
  const evidence = ref([])

  /** Trace 摘要 */
  const trace = ref(null)

  /** 当前选中的章节 ID */
  const selectedSectionId = ref(null)

  /** 当前高亮的 Evidence 索引 */
  const highlightedEvidenceIndex = ref(null)

  /** Evidence 按章节筛选的章节 ID */
  const evidenceFilterSectionId = ref(null)

  // ========== Computed ==========

  /** 按当前章节筛选后的 Evidence */
  const filteredEvidence = computed(() => {
    if (!evidenceFilterSectionId.value) return evidence.value
    return evidence.value.filter(e =>
      e.usedInSections.includes(evidenceFilterSectionId.value)
    )
  })

  // ========== Actions ==========

  /**
   * 获取任务报告并规范化数据
   * @param {string} taskId - 任务 UUID
   */
  async function fetch(taskId) {
    loading.value = true
    error.value = null
    try {
      const res = await researchApi.getReport(taskId)
      const data = res.data.data
      report.value = data
      normalize(data)
      // 默认选中第一章节
      if (sections.value.length > 0 && !selectedSectionId.value) {
        selectedSectionId.value = sections.value[0].id
      }
    } catch (err) {
      error.value = err
      clear()
    } finally {
      loading.value = false
    }
  }

  /**
   * 规范化后端报告数据为前端可用结构
   */
  function normalize(data) {
    const reportData = data.report || {}
    const sourceMap = buildSourceMap(reportData.sources || [])

    // 章节：使用索引字符串作为 id
    sections.value = (reportData.sections || []).map((section, index) => ({
      id: String(index),
      heading: section.heading || `章节 ${index + 1}`,
      content: section.content || '',
      sources: (section.sources || []).map(s => ({
        id: s.id,
        evidenceIndex: s.evidence_index != null ? String(s.evidence_index) : null,
      })),
    }))

    // Evidence Graph：按 index 排序
    const items = (data.evidence_graph?.items || []).map(item => {
      const source = item.source_id != null ? sourceMap[item.source_id] : null
      return {
        index: item.index != null ? Number(item.index) : 0,
        sourceId: item.source_id,
        sourceUrl: source?.url || null,
        sourceTitle: source?.title || null,
        domain: source?.domain || null,
        content: item.content || '',
        relevanceScore: item.relevance_score != null ? Number(item.relevance_score) : null,
        usedInSections: (item.used_in_sections || []).map(String),
      }
    })
    evidence.value = items.sort((a, b) => a.index - b.index)

    // Trace 摘要：后端返回嵌套结构，扁平化为 TracePanel 期望的格式
    trace.value = normalizeTrace(data.trace)
  }

  /**
   * 将 report.sources[] 构建为以 source_id 为 key 的映射
   */
  function buildSourceMap(sources) {
    const map = {}
    for (const s of sources) {
      if (s.id != null) {
        map[s.id] = {
          url: s.url || null,
          title: s.title || null,
          domain: s.domain || null,
        }
      }
    }
    return map
  }

  /**
   * 将后端嵌套 trace 扁平化为 { phase: { duration_ms, ... } }
   */
  function normalizeTrace(rawTrace) {
    if (!rawTrace) return null
    const phases = rawTrace.phases || {}
    const durations = rawTrace.phase_durations_ms || {}
    const flat = {}
    for (const key of PHASE_ORDER) {
      const phaseData = phases[key] || {}
      const durationMs = durations[key] != null ? durations[key] : phaseData.duration_ms
      flat[key] = {
        ...phaseData,
        duration_ms: durationMs != null ? durationMs : null,
      }
    }
    return flat
  }

  /**
   * 选中章节
   * @param {string} sectionId
   */
  function selectSection(sectionId) {
    selectedSectionId.value = sectionId
  }

  /**
   * 高亮指定 Evidence 索引（用于正文 ↔ Evidence 面板双向联动）
   * @param {number|null} index
   */
  function highlightEvidence(index) {
    highlightedEvidenceIndex.value = index
  }

  /**
   * 设置 Evidence 按章节筛选
   * @param {string|null} sectionId
   */
  function setEvidenceFilter(sectionId) {
    evidenceFilterSectionId.value = sectionId
  }

  /**
   * 清空报告状态
   */
  function clear() {
    report.value = null
    sections.value = []
    evidence.value = []
    trace.value = null
    selectedSectionId.value = null
    highlightedEvidenceIndex.value = null
    evidenceFilterSectionId.value = null
  }

  // ========== 导出 ==========

  return {
    // 状态
    report,
    loading,
    error,
    sections,
    evidence,
    trace,
    selectedSectionId,
    highlightedEvidenceIndex,
    evidenceFilterSectionId,

    // Computed
    filteredEvidence,

    // Actions
    fetch,
    selectSection,
    highlightEvidence,
    setEvidenceFilter,
    clear,
  }
})
