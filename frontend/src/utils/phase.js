/**
 * Pipeline 七阶段元数据与 key 归一化
 *
 * 对齐 FRONTEND.md §4.4.2 + UIDESIGN.md §4.9：
 * - SSE / 后端 snapshot 使用长 key：searching/fetching/reranking/synthesizing/building_evidence_graph/rendering
 * - UI 与 Trace 使用短 key：search/fetch/rerank/synthesis/evidence_graph/render
 * - 统一通过 normalizePhaseKey() 与 PHASE_ORDER 做映射
 */

/** 七阶段短 key（UI 与 Trace 使用） */
export const PHASE_ORDER = [
  'planning',
  'search',
  'fetch',
  'rerank',
  'synthesis',
  'evidence_graph',
  'render',
]

/** 短 key → 显示名称 */
export const PHASE_LABELS = {
  planning: '任务规划',
  search: '搜索',
  fetch: '抓取',
  rerank: '重排',
  synthesis: '综合',
  evidence_graph: '来源图谱',
  render: '报告渲染',
}

/** 短 key → Font Awesome 图标 */
export const PHASE_ICONS = {
  planning: 'fa-brain',
  search: 'fa-search',
  fetch: 'fa-download',
  rerank: 'fa-sort-amount-down',
  synthesis: 'fa-project-diagram',
  evidence_graph: 'fa-sitemap',
  render: 'fa-file-alt',
}

/** 长 key（SSE / 后端） → 短 key（UI） */
const LONG_TO_SHORT = {
  planning: 'planning',
  searching: 'search',
  fetching: 'fetch',
  reranking: 'rerank',
  synthesizing: 'synthesis',
  building_evidence_graph: 'evidence_graph',
  rendering: 'render',
}

/** 短 key（UI） → 长 key（SSE / 后端） */
const SHORT_TO_LONG = {
  planning: 'planning',
  search: 'searching',
  fetch: 'fetching',
  rerank: 'reranking',
  synthesis: 'synthesizing',
  evidence_graph: 'building_evidence_graph',
  render: 'rendering',
}

/**
 * 将任意 phase key 归一化为短 key（UI 使用）
 * @param {string|null|undefined} phase
 * @returns {string|null}
 */
export function normalizePhaseKey(phase) {
  if (!phase) return null
  const short = LONG_TO_SHORT[phase]
  if (short) return short
  // 传入的已经是短 key
  if (PHASE_ORDER.includes(phase)) return phase
  return null
}

/**
 * 将短 key 转换为 SSE/后端使用的长 key
 * @param {string|null|undefined} shortKey
 * @returns {string|null}
 */
export function toLongPhaseKey(shortKey) {
  if (!shortKey) return null
  return SHORT_TO_LONG[shortKey] || null
}

/**
 * 获取阶段在七阶段顺序中的索引（从 0 开始）
 * @param {string|null|undefined} phase
 * @returns {number}
 */
export function getPhaseIndex(phase) {
  const short = normalizePhaseKey(phase)
  if (!short) return -1
  return PHASE_ORDER.indexOf(short)
}

/**
 * 初始化七阶段状态对象
 * @returns {Record<string, 'pending'|'running'|'done'|'skipped'>}
 */
export function initPhaseStates() {
  const states = {}
  for (const key of PHASE_ORDER) {
    states[key] = 'pending'
  }
  return states
}

/**
 * 根据当前阶段短 key，生成各阶段状态映射
 * 当前阶段之前的阶段为 done，当前阶段为 running，之后为 pending
 * @param {string|null|undefined} currentPhase
 * @returns {Record<string, 'pending'|'running'|'done'>}
 */
export function buildPhaseStates(currentPhase) {
  const states = initPhaseStates()
  const currentIndex = getPhaseIndex(currentPhase)
  if (currentIndex === -1) return states

  for (let i = 0; i < PHASE_ORDER.length; i++) {
    const key = PHASE_ORDER[i]
    if (i < currentIndex) {
      states[key] = 'done'
    } else if (i === currentIndex) {
      states[key] = 'running'
    } else {
      states[key] = 'pending'
    }
  }
  return states
}

/**
 * 根据 Step 快照数组重建各阶段状态映射
 * - 含有 completed step 的 phase 标记为 done
 * - 当前 phase（由 currentPhase 或最后一个 completed step 推断）标记为 running（若未 done）
 * - 其余为 pending
 *
 * 用于切页/重载后恢复 canceled / failed / completed 等终态任务的阶段视图。
 * @param {Array<{step_type: string, status: string}>} steps
 * @param {string|null|undefined} currentPhase
 * @returns {Record<string, 'pending'|'running'|'done'>}
 */
export function buildPhaseStatesFromSteps(steps, currentPhase) {
  const states = initPhaseStates()
  if (!Array.isArray(steps) || steps.length === 0) {
    return states
  }

  // 标记含有 completed step 的 phase 为 done
  const donePhases = new Set()
  for (const step of steps) {
    if (step.status === 'completed') {
      const phase = normalizePhaseKey(step.step_type)
      if (phase) donePhases.add(phase)
    }
  }
  for (const phase of donePhases) {
    states[phase] = 'done'
  }

  // 推断当前 phase：优先用传入的 currentPhase，否则取最后一个 completed step 的 phase
  let activePhase = normalizePhaseKey(currentPhase)
  if (!activePhase) {
    const lastCompleted = [...steps]
      .reverse()
      .find(s => s.status === 'completed')
    activePhase = normalizePhaseKey(lastCompleted?.step_type)
  }

  if (activePhase && states[activePhase] !== 'done') {
    states[activePhase] = 'running'
  }

  return states
}
