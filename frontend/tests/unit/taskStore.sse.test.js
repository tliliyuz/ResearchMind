/**
 * TaskStore SSE 事件处理补充测试 — 覆盖 src/stores/task.js
 *
 * 重点覆盖 Phase 3 新增的运行态状态：
 * - stepLogs / phaseStates / phaseDurations / lastCheckpoint / warnings
 * - step 事件映射与幂等
 * - task.status.snapshot 恢复 logs
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useTaskStore } from '@/stores/task'

vi.mock('@/api/research', () => ({
  createTask: vi.fn(),
  getTaskList: vi.fn(),
  getTaskDetail: vi.fn(),
  deleteTask: vi.fn(),
  cancelTask: vi.fn(),
  getTaskState: vi.fn(),
}))

vi.mock('@/utils/sse', () => ({
  connectSSE: vi.fn(() => ({ close: vi.fn() })),
}))

describe('TaskStore — SSE 事件处理（Phase 3 运行态）', () => {
  function makeStore() {
    const store = useTaskStore()
    store.current = {
      task_id: 'task-001',
      topic: '测试主题',
      status: 'running',
      current_phase: null,
      total_sources: 0,
      total_evidence: 0,
    }
    store.resetRuntimeState()
    return store
  }

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('phase.started 更新阶段状态并追加日志', () => {
    const store = makeStore()
    store.handleSSEEvent('phase.started', { phase: 'searching', timestamp: '2026-06-24T10:00:00Z' })

    expect(store.current.current_phase).toBe('search')
    expect(store.phaseStates.search).toBe('running')
    expect(store.phaseStates.planning).toBe('done')
    expect(store.stepLogs).toHaveLength(1)
    expect(store.stepLogs[0].message).toContain('搜索')
  })

  it('phase.completed 标记阶段完成并记录耗时', () => {
    const store = makeStore()
    store.phaseStates.planning = 'running'
    store.handleSSEEvent('phase.completed', { phase: 'planning', duration_ms: 1200, timestamp: '2026-06-24T10:00:01Z' })

    expect(store.phaseStates.planning).toBe('done')
    expect(store.phaseDurations.planning).toBe(1200)
    expect(store.stepLogs[0].message).toContain('任务规划 阶段完成')
  })

  it('step.started 追加 running 日志', () => {
    const store = makeStore()
    store.handleSSEEvent('step.started', {
      step_id: 's1',
      step_type: 'search',
      phase: 'searching',
      label: '搜索子问题 1',
      timestamp: '2026-06-24T10:00:02Z',
    })

    expect(store.stepLogs).toHaveLength(1)
    expect(store.stepLogs[0].stepId).toBe('s1')
    expect(store.stepLogs[0].status).toBe('running')
    expect(store.stepLogs[0].label).toBe('搜索子问题 1')
    expect(store.stepLogs[0].message).toBe('搜索子问题 1')
    expect(store.phaseStates.search).toBe('running')
  })

  it('step.progress 更新日志 progress 字段', () => {
    const store = makeStore()
    store.handleSSEEvent('step.started', { step_id: 's1', step_type: 'search', phase: 'searching', label: '搜索' })
    store.handleSSEEvent('step.progress', { step_id: 's1', results_found: 15 })

    const log = store.stepLogs.find(l => l.stepId === 's1')
    expect(log.progress).toEqual({ step_id: 's1', results_found: 15 })
  })

  it('step.completed 幂等_重复事件不重复计数', () => {
    const store = makeStore()
    store.handleSSEEvent('step.started', { step_id: 's1', step_type: 'search', phase: 'searching', label: '搜索' })
    store.handleSSEEvent('step.completed', { step_id: 's1', timestamp: '2026-06-24T10:00:03Z' })
    store.handleSSEEvent('step.completed', { step_id: 's1', timestamp: '2026-06-24T10:00:04Z' })

    expect(store.completedStepIds.size).toBe(1)
    const log = store.stepLogs.find(l => l.stepId === 's1')
    expect(log.status).toBe('completed')
  })

  it('step.failed 记录错误类型', () => {
    const store = makeStore()
    store.handleSSEEvent('step.started', { step_id: 's1', step_type: 'search', phase: 'searching', label: '搜索' })
    store.handleSSEEvent('step.failed', {
      step_id: 's1',
      error_type: 'E3102',
      error_description: '搜索后端不可用',
      timestamp: '2026-06-24T10:00:03Z',
    })

    const log = store.stepLogs.find(l => l.stepId === 's1')
    expect(log.status).toBe('failed')
    expect(log.errorType).toBe('E3102')
  })

  it('step.skipped 记录跳过原因', () => {
    const store = makeStore()
    store.handleSSEEvent('step.started', { step_id: 's1', step_type: 'search', phase: 'searching', label: '搜索' })
    store.handleSSEEvent('step.skipped', { step_id: 's1', reason: '无结果', timestamp: '2026-06-24T10:00:03Z' })

    const log = store.stepLogs.find(l => l.stepId === 's1')
    expect(log.status).toBe('skipped')
    expect(log.skipReason).toBe('无结果')
  })

  it('checkpoint.saved 设置 lastCheckpoint 并追加日志', () => {
    const store = makeStore()
    store.handleSSEEvent('checkpoint.saved', {
      phase: 'searching',
      last_completed_step_id: 's1',
      saved_at: '2026-06-24T10:00:05Z',
    })

    expect(store.lastCheckpoint).toEqual({ phase: 'search', stepId: 's1', savedAt: '2026-06-24T10:00:05Z' })
    expect(store.stepLogs[0].message).toBe('已保存进度')
  })

  it('task.warning 追加 warning 日志', () => {
    const store = makeStore()
    store.handleSSEEvent('task.warning', {
      step_id: 's1',
      error_description: '部分来源抓取失败，已降级',
      timestamp: '2026-06-24T10:00:06Z',
    })

    expect(store.warnings).toHaveLength(1)
    expect(store.warnings[0].description).toContain('降级')
    expect(store.stepLogs[0].level).toBe('warning')
  })

  it('task.status.snapshot 恢复 steps 重建 stepLogs', () => {
    const store = makeStore()
    store.handleSSEEvent('task.status.snapshot', {
      status: 'running',
      current_phase: 'fetching',
      progress: { completed_steps: 2, total_steps: 5, progress: 0.4 },
      stats: { total_sources: 3, total_evidence: 1 },
      steps: [
        {
          step_id: 's1',
          step_type: 'search',
          status: 'completed',
          label: '搜索子问题 1',
          duration_ms: 1000,
          started_at: '2026-06-24T10:00:00Z',
          completed_at: '2026-06-24T10:00:01Z',
          progress_label: '12 条结果',
          error_code: null,
        },
        {
          step_id: 's2',
          step_type: 'fetch',
          status: 'running',
          label: '抓取结果',
          duration_ms: null,
          started_at: '2026-06-24T10:00:02Z',
        },
      ],
    })

    expect(store.current.current_phase).toBe('fetch')
    expect(store.progress.completed_steps).toBe(2)
    expect(store.current.total_sources).toBe(3)
    // search: phase.start + step + phase.done + checkpoint; fetch: phase.start + step
    expect(store.stepLogs).toHaveLength(6)

    const searchStart = store.stepLogs[0]
    expect(searchStart.type).toBe('phase')
    expect(searchStart.message).toBe('进入 搜索 阶段')

    const searchStep = store.stepLogs[1]
    expect(searchStep.type).toBe('step')
    expect(searchStep.status).toBe('completed')
    expect(searchStep.message).toBe('搜索子问题 1')
    expect(searchStep.timestamp).toBe('2026-06-24T10:00:00Z')
    expect(searchStep.progress).toEqual({ label: '12 条结果' })
    expect(searchStep.icon).toBe('fa-check-circle')

    const searchDone = store.stepLogs[2]
    expect(searchDone.type).toBe('phase')
    expect(searchDone.message).toContain('搜索 阶段完成')
    expect(searchDone.level).toBe('success')

    const searchCheckpoint = store.stepLogs[3]
    expect(searchCheckpoint.type).toBe('checkpoint')
    expect(searchCheckpoint.message).toBe('已保存进度')
    expect(searchCheckpoint.level).toBe('warning')

    const fetchStart = store.stepLogs[4]
    expect(fetchStart.type).toBe('phase')
    expect(fetchStart.message).toBe('进入 抓取 阶段')

    const fetchStep = store.stepLogs[5]
    expect(fetchStep.type).toBe('step')
    expect(fetchStep.status).toBe('running')
    expect(fetchStep.timestamp).toBe('2026-06-24T10:00:02Z')
    expect(fetchStep.icon).toBe('fa-spinner fa-spin')
    expect(store.completedStepIds.has('s1')).toBe(true)
  })

  it('task.status.snapshot 重建时保留现有 step 日志的丰富字段', () => {
    const store = makeStore()
    // 先通过实时事件写入一条带 progress 的 running step 日志
    store.handleSSEEvent('step.started', {
      step_id: 's1',
      step_type: 'search',
      phase: 'searching',
      label: '搜索子问题 1',
      timestamp: '2026-06-24T10:00:00Z',
    })
    store.handleSSEEvent('step.progress', {
      step_id: 's1',
      results_found: 15,
      selected: 5,
    })

    // 重连快照将该 step 标记为 completed
    store.handleSSEEvent('task.status.snapshot', {
      status: 'running',
      current_phase: 'fetching',
      progress: { completed_steps: 1, total_steps: 5, progress: 0.2 },
      steps: [
        {
          step_id: 's1',
          step_type: 'search',
          status: 'completed',
          label: '搜索子问题 1',
          duration_ms: 800,
          started_at: '2026-06-24T10:00:00Z',
          completed_at: '2026-06-24T10:00:01Z',
          progress_label: '15 条结果',
        },
      ],
    })

    const log = store.stepLogs.find(l => l.stepId === 's1')
    expect(log.status).toBe('completed')
    expect(log.icon).toBe('fa-check-circle')
    // 保留 SSE step.progress 中的丰富 progress 对象
    expect(log.progress).toEqual({ step_id: 's1', results_found: 15, selected: 5 })
  })

  it('task.completed 更新状态并追加完成日志', () => {
    const store = makeStore()
    store.current.total_sources = 5
    store.current.total_evidence = 3
    store.handleSSEEvent('task.completed', {
      trace: { sources: 5, evidence: 3 },
      timestamp: '2026-06-24T10:00:10Z',
    })

    expect(store.current.status).toBe('completed')
    expect(store.sseStatus).toBe('disconnected')
    expect(store.stepLogs[store.stepLogs.length - 1].icon).toBe('fa-trophy')
  })

  it('task.failed 更新错误信息并断开 SSE', () => {
    const store = makeStore()
    store.handleSSEEvent('task.failed', {
      error_type: 'E3104',
      error_description: 'Synthesis 失败',
      recoverable: true,
      timestamp: '2026-06-24T10:00:10Z',
    })

    expect(store.current.status).toBe('failed')
    expect(store.current.error_code).toBe('E3104')
    expect(store.current.recoverable).toBe(true)
    expect(store.sseStatus).toBe('disconnected')
  })

  it('task.failed 将 SSE error_type 字符串映射为标准 E 码', () => {
    const store = makeStore()
    store.handleSSEEvent('task.failed', {
      error_type: 'RerankFailed',
      error_description: 'Rerank 输入格式错误或计算失败',
      recoverable: false,
      timestamp: '2026-06-24T10:00:10Z',
    })

    expect(store.current.status).toBe('failed')
    expect(store.current.error_code).toBe('E3105')
    expect(store.current.error_message).toBe('Rerank 输入格式错误或计算失败')
    expect(store.current.recoverable).toBe(false)
  })

  it('task.failed 未知 error_type 回退保留原始值', () => {
    const store = makeStore()
    store.handleSSEEvent('task.failed', {
      error_type: 'SomeCustomError',
      error_description: '自定义错误',
      recoverable: false,
      timestamp: '2026-06-24T10:00:10Z',
    })

    expect(store.current.status).toBe('failed')
    expect(store.current.error_code).toBe('SomeCustomError')
    expect(store.current.error_message).toBe('自定义错误')
  })

  it('task.canceled 更新状态并断开 SSE', () => {
    const store = makeStore()
    store.handleSSEEvent('task.canceled', { timestamp: '2026-06-24T10:00:10Z' })

    expect(store.current.status).toBe('canceled')
    expect(store.sseStatus).toBe('disconnected')
  })

  it('agent.thought 追加思考日志并截断内容', () => {
    const store = makeStore()
    const longThought = 'a'.repeat(300)
    store.handleSSEEvent('agent.thought', {
      iteration: 2,
      phase: 'searching',
      thought: longThought,
      timestamp: '2026-06-24T10:00:07Z',
    })

    expect(store.stepLogs).toHaveLength(1)
    const log = store.stepLogs[0]
    expect(log.type).toBe('agent')
    expect(log.icon).toBe('fa-brain')
    expect(log.level).toBe('info')
    expect(log.message).toContain('思考：')
    expect(log.message.length).toBeLessThan(longThought.length)
    expect(log.fullContent).toBe(longThought)
    expect(log.phase).toBe('search')
    expect(log.iteration).toBe(2)
    expect(log.timestamp).toBe('2026-06-24T10:00:07Z')
  })

  it('agent.action 追加动作日志并保留工具参数', () => {
    const store = makeStore()
    store.handleSSEEvent('agent.action', {
      iteration: 2,
      phase: 'searching',
      tool_call_id: 'call-001',
      tool_name: 'search_tool',
      arguments: { sub_question: '测试子问题' },
      timestamp: '2026-06-24T10:00:08Z',
    })

    expect(store.stepLogs).toHaveLength(1)
    const log = store.stepLogs[0]
    expect(log.type).toBe('agent')
    expect(log.icon).toBe('fa-terminal')
    expect(log.level).toBe('info')
    expect(log.message).toContain('search_tool')
    expect(log.message).toContain('测试子问题')
    expect(log.toolName).toBe('search_tool')
    expect(log.args).toEqual({ sub_question: '测试子问题' })
    expect(log.phase).toBe('search')
    expect(log.iteration).toBe(2)
  })

  it('agent.observation 追加观察日志，失败时 level 为 warning', () => {
    const store = makeStore()
    store.handleSSEEvent('agent.observation', {
      iteration: 2,
      phase: 'searching',
      tool_call_id: 'call-001',
      tool_name: 'search_tool',
      observation: '找到 12 条相关结果',
      success: true,
      timestamp: '2026-06-24T10:00:09Z',
    })

    expect(store.stepLogs).toHaveLength(1)
    const log = store.stepLogs[0]
    expect(log.type).toBe('agent')
    expect(log.icon).toBe('fa-eye')
    expect(log.level).toBe('info')
    expect(log.message).toContain('search_tool')
    expect(log.message).toContain('找到 12 条相关结果')
    expect(log.toolName).toBe('search_tool')
    expect(log.success).toBe(true)
  })

  it('agent.observation 失败时 level 为 warning', () => {
    const store = makeStore()
    store.handleSSEEvent('agent.observation', {
      iteration: 2,
      phase: 'searching',
      tool_call_id: 'call-001',
      tool_name: 'search_tool',
      observation: '工具不可用',
      success: false,
      timestamp: '2026-06-24T10:00:09Z',
    })

    expect(store.stepLogs[0].level).toBe('warning')
  })

  it('agent.* 事件不修改任务状态、阶段和进度', () => {
    const store = makeStore()
    const originalPhase = store.current.current_phase
    store.handleSSEEvent('agent.thought', { iteration: 1, phase: 'planning', thought: '思考' })
    store.handleSSEEvent('agent.action', { iteration: 1, phase: 'planning', tool_name: 'memory_tool', arguments: {} })
    store.handleSSEEvent('agent.observation', { iteration: 1, phase: 'planning', tool_name: 'memory_tool', observation: '完成', success: true })

    expect(store.current.status).toBe('running')
    expect(store.current.current_phase).toBe(originalPhase)
    expect(store.progress.completed_steps).toBe(0)
    expect(store.phaseStates.planning).toBe('pending')
    expect(store.stepLogs).toHaveLength(3)
  })
})
