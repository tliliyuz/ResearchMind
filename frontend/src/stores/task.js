import { defineStore } from 'pinia'
import { ref, watch, computed } from 'vue'
import * as researchApi from '@/api/research'
import { connectSSE } from '@/utils/sse'
import { normalizePhaseKey, buildPhaseStates, buildPhaseStatesFromSteps, initPhaseStates, PHASE_LABELS } from '@/utils/phase'

export const useTaskStore = defineStore('task', () => {
  // ========== 状态 ==========

  /** 当前用户的任务历史列表 */
  const taskList = ref([])

  /** 当前聚焦的任务详情（null = 创建态） */
  const current = ref(null)

  /** 列表分页 */
  const currentPage = ref(1)
  const total = ref(0)
  const pageSize = ref(20)

  /** 加载状态 */
  const loading = ref(false)
  const listLoading = ref(false)

  /**
   * SSE 连接状态（5 态）
   * disconnected → connecting → connected → reconnecting → error
   */
  const sseStatus = ref('disconnected')

  /** 全局进度（execution_context.progress 快照） */
  const progress = ref({
    completed_steps: 0,
    total_steps: 0,
    progress: 0,
  })

  /** SSE 连接句柄（{ close } 对象） */
  const sseConnection = ref(null)

  // ========== 运行态实时状态（Phase 3 新增） ==========

  /** Step 实时日志条目 */
  const stepLogs = ref([])

  /** 七阶段状态映射 */
  const phaseStates = ref(initPhaseStates())

  /** 阶段耗时（毫秒） */
  const phaseDurations = ref({})

  /** 最近一次 checkpoint.saved 数据 */
  const lastCheckpoint = ref(null)

  /** 警告列表 */
  const warnings = ref([])

  /** 已完成的 step_id 集合，防止 step.completed 重复计数 */
  const completedStepIds = ref(new Set())

  // ========== 副作用：同步 current 到 taskList ==========

  /**
   * 当 current 任务状态变化时，同步更新侧边栏「最近任务」中对应条目，
   * 使图标无需刷新页面即可反映 running / completed / canceled 等状态。
   */
  watch(
    current,
    (task) => {
      if (!task) return
      const idx = taskList.value.findIndex(t => t.task_id === task.task_id)
      if (idx >= 0) {
        taskList.value[idx] = {
          ...taskList.value[idx],
          status: task.status,
          current_phase: task.current_phase,
          completed_at: task.completed_at,
        }
      }
    },
    { deep: true }
  )

  // ========== Actions ==========

  /**
   * 创建研究任务
   *
   * 参考 retryTask 的乐观更新策略：在 API 返回前即进入运行态，避免用户在创建态
   * 阻塞等待后端响应 / Worker 拾取。API 失败时回滚到创建态。
   *
   * @param {string} topic - 研究主题
   * @param {object} requirements - { task_type, depth, max_sources, language }
   * @returns {object} { task_id, status, created_at }
   */
  async function createTask(topic, requirements) {
    loading.value = true
    try {
      // 乐观进入运行态：页面立即切换到 Pipeline 进度视图，不再停留在创建表单
      const nowIso = new Date().toISOString()
      current.value = {
        task_id: null,
        topic,
        status: 'running',
        requirements,
        current_phase: null,
        progress: { completed_steps: 0, total_steps: 7, progress: 0 },
        total_sources: 0,
        total_evidence: 0,
        error_code: null,
        error_message: null,
        recoverable: false,
        created_at: nowIso,
        started_at: nowIso,
        completed_at: null,
      }
      progress.value = { completed_steps: 0, total_steps: 7, progress: 0 }
      resetRuntimeState()
      sseStatus.value = 'disconnected'

      const res = await researchApi.createTask(topic, requirements)
      const taskData = res.data.data

      // 用真实响应覆盖乐观占位
      current.value = {
        task_id: taskData.task_id,
        topic,
        status: taskData.status,
        requirements,
        current_phase: null,
        progress: { completed_steps: 0, total_steps: 7, progress: 0 },
        total_sources: 0,
        total_evidence: 0,
        error_code: null,
        error_message: null,
        recoverable: false,
        created_at: taskData.created_at,
        started_at: null,
        completed_at: null,
      }
      progress.value = { completed_steps: 0, total_steps: 7, progress: 0 }
      resetRuntimeState()
      sseStatus.value = 'disconnected'

      // 刷新侧边栏最近任务，重置到第 1 页
      try {
        await fetchList({ page: 1, page_size: 20 })
      } catch {
        // 非关键，静默处理
      }
      return taskData
    } catch (err) {
      // 创建失败：回滚到创建态，避免用户停留在假运行态
      clearCurrent()
      throw err
    } finally {
      loading.value = false
    }
  }

  /**
   * 获取任务历史列表
   * @param {object} params - { page, page_size, status, keyword, append }
   * @param {boolean} params.append - 为 true 时追加到 taskList，否则重置
   */
  async function fetchList(params = {}) {
    listLoading.value = true
    try {
      const page = params.page || 1
      const pageSizeParam = params.page_size || 20
      const res = await researchApi.getTaskList({
        page,
        page_size: pageSizeParam,
        status: params.status || undefined,
        keyword: params.keyword || undefined,
      })
      const data = res.data.data
      const items = data.items || []
      if (params.append) {
        taskList.value.push(...items)
      } else {
        taskList.value = items
      }
      total.value = data.total || 0
      currentPage.value = data.page || page
      pageSize.value = data.page_size || pageSizeParam
    } finally {
      listLoading.value = false
    }
  }

  /** 是否还有更多任务可加载 */
  const hasMore = computed(() => {
    const loadedCount = taskList.value.length
    const totalCount = Number(total.value || 0)
    // 后端返回有效 total 时直接比较
    if (totalCount > 0) return loadedCount < totalCount
    // total 缺失/异常时，根据当前页是否满载兜底：只有最后一页满员才允许继续尝试
    const lastPageLoaded = loadedCount - (currentPage.value - 1) * pageSize.value
    return loadedCount > 0 && lastPageLoaded === pageSize.value
  })

  /**
   * 加载下一页任务（用于侧边栏无限滚动）
   */
  async function fetchMore() {
    if (listLoading.value || !hasMore.value) return
    const nextPage = currentPage.value + 1
    await fetchList({ page: nextPage, page_size: pageSize.value, append: true })
  }

  /**
   * 获取任务详情并设为 current
   * @param {string} taskId - 任务 UUID
   * @returns {object} 任务详情
   */
  async function fetchDetail(taskId) {
    loading.value = true
    try {
      const isSameTask = current.value?.task_id === taskId
      const res = await researchApi.getTaskDetail(taskId)
      const data = res.data.data
      // 后端详情接口按 API.md 将错误信息嵌套在 data.error 下；保留顶层字段兼容旧返回
      const errorInfo = data.error || {}
      current.value = {
        task_id: data.task_id,
        topic: data.topic,
        status: data.status,
        current_phase: data.current_phase || null,
        requirements: data.requirements || {},
        progress: data.progress || { completed_steps: 0, total_steps: 0, progress: 0 },
        total_sources: data.total_sources || 0,
        total_evidence: data.total_evidence || 0,
        error_code: errorInfo.error_code || data.error_code || null,
        error_message: errorInfo.error_message || data.error_message || null,
        recoverable: errorInfo.recoverable ?? data.recoverable ?? false,
        created_at: data.created_at || null,
        started_at: data.started_at || null,
        completed_at: data.completed_at || null,
      }
      progress.value = data.progress || { completed_steps: 0, total_steps: 0, progress: 0 }
      // 恢复运行态状态：切页回到同一任务时保留已有实时日志，避免被快照简化覆盖
      if (!isSameTask) {
        resetRuntimeState()
      }

      const terminalStatuses = ['canceled', 'failed', 'completed', 'partially_completed']
      const isTerminal = terminalStatuses.includes(data.status)

      if (isTerminal) {
        // 终态任务通过 /state 端点获取含 steps 的快照，重建阶段视图与耗时
        try {
          const stateRes = await researchApi.getTaskState(taskId)
          const snapshot = stateRes.data.data
          if (snapshot?.steps && Array.isArray(snapshot.steps)) {
            buildLogsFromSnapshot(snapshot.steps)
            phaseStates.value = buildPhaseStatesFromSteps(snapshot.steps, snapshot.current_phase || data.current_phase)
            phaseDurations.value = buildPhaseDurations(snapshot.steps)
          }
        } catch {
          // 非关键，静默处理；兜底仍按 current_phase 显示
          phaseStates.value = buildPhaseStates(normalizePhaseKey(data.current_phase))
        }
      } else {
        if (data.steps && Array.isArray(data.steps)) {
          buildLogsFromSnapshot(data.steps)
        }
        phaseStates.value = buildPhaseStates(normalizePhaseKey(data.current_phase))
      }

      // 查看运行中任务时自动建立 SSE 连接
      if (data.status === 'running') {
        connectSSEToTask(taskId)
      }
      return data
    } finally {
      loading.value = false
    }
  }

  /**
   * 删除任务并本地移除
   * @param {string} taskId - 任务 UUID
   */
  async function deleteTask(taskId) {
    await researchApi.deleteTask(taskId)
    // 本地移除
    taskList.value = taskList.value.filter(t => t.task_id !== taskId)
    total.value = Math.max(0, total.value - 1)
    // 如果删除的是当前查看的任务，清空
    if (current.value?.task_id === taskId) {
      clearCurrent()
    }
  }

  /**
   * 取消正在运行的任务
   * @param {string} taskId - 任务 UUID
   */
  async function cancelTask(taskId) {
    await researchApi.cancelTask(taskId)
    // API 成功后立即更新本地状态并断开 SSE，随后 task.canceled 事件做幂等收尾
    if (current.value && current.value.task_id === taskId) {
      current.value.status = 'canceled'
    }
    disconnectSSE()
  }

  /**
   * 断点续跑：调用 Retry API 后立即建立 SSE 连接
   *
   * 设计要点：
   * - 不在 retry 后调用 fetchDetail，因为：
   *   1. fetchDetail 是网络请求，延迟期间 Worker 已开始发布事件，SSE 未连接则事件丢失
   *   2. fetchDetail 会用 DB 中的 pending 状态覆盖本地的 running 乐观更新
   * - SSE 连接后首条 task.status.snapshot 提供权威状态（含已完成 steps 等）
   * - taskList 由 watch(current, …) 自动同步
   *
   * @param {string} taskId - 任务 UUID
   */
  async function retryTask(taskId) {
    // 先保存旧状态，用于 API 失败时回滚
    let previousStatus = null
    let previousErrorCode = null
    let previousErrorMessage = null
    let previousRecoverable = false

    if (current.value && current.value.task_id === taskId) {
      previousStatus = current.value.status
      previousErrorCode = current.value.error_code
      previousErrorMessage = current.value.error_message
      previousRecoverable = current.value.recoverable

      // 乐观更新：点击后立即切换到运行态，避免失败态页面停留期间用户重复点击
      current.value.status = 'running'
      current.value.error_code = null
      current.value.error_message = null
      current.value.recoverable = false
      resetRuntimeState()
    }

    try {
      const res = await researchApi.retryTask(taskId)
      const data = res.data.data
      // API 返回 202 表示已分发，立即建立 SSE 连接
      // 快照会提供权威状态：steps / current_phase / progress 等
      connectSSEToTask(taskId)
      return data
    } catch (err) {
      // 续跑请求失败时回滚到之前状态，继续展示失败/取消视图
      if (current.value && current.value.task_id === taskId) {
        current.value.status = previousStatus
        current.value.error_code = previousErrorCode
        current.value.error_message = previousErrorMessage
        current.value.recoverable = previousRecoverable
      }
      throw err
    }
  }

  /**
   * 连接 SSE 流，实时接收 Pipeline 事件
   * @param {string} taskId - 任务 UUID
   */
  async function connectSSEToTask(taskId) {
    // 先断开旧连接
    disconnectSSE()

    sseStatus.value = 'connecting'

    const conn = connectSSE(`/api/research/${taskId}/stream`, {
      onEvent(eventName, data) {
        handleSSEEvent(eventName, data)
      },
      onStatusChange(status) {
        sseStatus.value = status
      },
      onError(err) {
        console.error('[SSE] 错误：', err.message)
      },
    })

    sseConnection.value = conn
  }

  /**
   * 断开当前 SSE 连接
   */
  function disconnectSSE() {
    if (sseConnection.value) {
      sseConnection.value.close()
      sseConnection.value = null
    }
    sseStatus.value = 'disconnected'
  }

  /**
   * 重置运行态实时状态
   */
  function resetRuntimeState() {
    stepLogs.value = []
    phaseStates.value = initPhaseStates()
    phaseDurations.value = {}
    lastCheckpoint.value = null
    warnings.value = []
    completedStepIds.value = new Set()
  }

  /**
   * 根据 Step 状态返回日志图标
   */
  function _stepIcon(status) {
    switch (status) {
      case 'running': return 'fa-spinner fa-spin'
      case 'completed': return 'fa-check-circle'
      case 'skipped': return 'fa-minus-circle'
      case 'failed': return 'fa-times-circle'
      default: return 'fa-info-circle'
    }
  }

  /**
   * 从状态快照的 steps 数组重建 stepLogs
   *
   * 目标：让切页/重连后的日志样式与实时 SSE 事件生成的日志尽量一致。
   * - 按 started_at 排序并聚合到各个 phase
   * - 在每个 phase 前后插入“进入阶段 / 阶段完成”日志
   * - 对已存在的 step 日志保留 SSE 中积累的丰富字段（progress、warning 等），仅更新状态
   * @param {Array} steps
   */
  function buildLogsFromSnapshot(steps) {
    // 保留现有 step 日志中的丰富字段（progress、warn 文本等）
    const existingStepLogs = new Map()
    stepLogs.value.forEach(log => {
      if (log.stepId && !existingStepLogs.has(log.stepId)) {
        existingStepLogs.set(log.stepId, log)
      }
    })

    // 按 started_at 升序排序；无 started_at 的兜底用 completed_at
    const sortedSteps = [...steps].sort((a, b) => {
      const ta = a.started_at ? new Date(a.started_at).getTime() : 0
      const tb = b.started_at ? new Date(b.started_at).getTime() : 0
      if (ta !== tb) return ta - tb
      const ca = a.completed_at ? new Date(a.completed_at).getTime() : 0
      const cb = b.completed_at ? new Date(b.completed_at).getTime() : 0
      return ca - cb
    })

    // 按 phase 分组（保持 phase 首次出现的顺序）
    const phaseGroups = []
    const phaseIndexMap = new Map()
    for (const step of sortedSteps) {
      const phase = normalizePhaseKey(step.step_type) || step.step_type
      if (!phaseIndexMap.has(phase)) {
        phaseGroups.push({ phase, steps: [] })
        phaseIndexMap.set(phase, phaseGroups.length - 1)
      }
      phaseGroups[phaseIndexMap.get(phase)].steps.push(step)
    }

    const newLogs = []
    const nowSuffix = Date.now()

    for (const { phase, steps: phaseSteps } of phaseGroups) {
      const phaseLabel = PHASE_LABELS[phase] || phase
      const firstStep = phaseSteps[0]
      const lastStep = phaseSteps[phaseSteps.length - 1]
      const allTerminal = phaseSteps.every(s =>
        ['completed', 'skipped', 'failed'].includes(s.status)
      )

      // 阶段开始日志
      newLogs.push({
        id: `snapshot-phase-start-${phase}-${nowSuffix}`,
        type: 'phase',
        icon: 'fa-arrow-right',
        level: 'info',
        message: `进入 ${phaseLabel} 阶段`,
        timestamp: firstStep.started_at || firstStep.completed_at,
      })

      // Step 日志：已有丰富日志时合并状态，否则生成简化日志
      for (const step of phaseSteps) {
        const existing = existingStepLogs.get(step.step_id)
        if (existing) {
          newLogs.push({
            ...existing,
            status: step.status,
            icon: _stepIcon(step.status),
            timestamp: step.started_at || existing.timestamp,
            startedAt: step.started_at || existing.startedAt,
            completedAt: step.completed_at || existing.completedAt,
            durationMs: step.duration_ms ?? existing.durationMs,
            progress: existing.progress || (step.progress_label ? { label: step.progress_label } : null),
          })
        } else {
          newLogs.push({
            id: `snapshot-step-${step.step_id}`,
            type: 'step',
            stepId: step.step_id,
            phase,
            stepType: step.step_type,
            status: step.status,
            label: step.label,
            message: step.label || step.step_type,
            timestamp: step.started_at || step.completed_at,
            startedAt: step.started_at,
            completedAt: step.completed_at,
            durationMs: step.duration_ms,
            errorType: step.error_code,
            errorMessage: step.error_message,
            icon: _stepIcon(step.status),
            progress: step.progress_label ? { label: step.progress_label } : null,
          })
        }
      }

      // 阶段完成日志（所有 step 都已终态且最后一步有完成时间）
      if (allTerminal && lastStep.completed_at) {
        const durationText = lastStep.duration_ms
          ? `（耗时 ${formatDurationMs(lastStep.duration_ms)}）`
          : ''
        newLogs.push({
          id: `snapshot-phase-done-${phase}-${nowSuffix}`,
          type: 'phase',
          icon: 'fa-check-circle',
          level: 'success',
          message: `${phaseLabel} 阶段完成${durationText}`,
          timestamp: lastStep.completed_at,
        })
        // Orchestrator 在阶段完成后会发送 checkpoint.saved，快照重建时同步推断该日志以保持样式一致
        newLogs.push({
          id: `snapshot-checkpoint-${phase}-${nowSuffix}`,
          type: 'checkpoint',
          icon: 'fa-save',
          level: 'warning',
          message: '已保存进度',
          timestamp: lastStep.completed_at,
        })
      }
    }

    stepLogs.value = newLogs
    completedStepIds.value = new Set(
      steps.filter(s => s.status === 'completed').map(s => s.step_id)
    )
  }

  /**
   * 从 Step 快照数组聚合每个 phase 的耗时
   * 仅累计状态为 completed 的 step 的 duration_ms
   * @param {Array} steps
   * @returns {Record<string, number>}
   */
  function buildPhaseDurations(steps) {
    const durations = {}
    for (const step of steps) {
      if (step.status !== 'completed' || step.duration_ms == null) continue
      const phase = normalizePhaseKey(step.step_type)
      if (!phase) continue
      durations[phase] = (durations[phase] || 0) + step.duration_ms
    }
    return durations
  }

  /**
   * 清空当前任务，回到创建态
   */
  function clearCurrent() {
    disconnectSSE()
    current.value = null
    progress.value = { completed_steps: 0, total_steps: 0, progress: 0 }
    resetRuntimeState()
  }

  // ========== SSE 事件处理（内部） ==========

  /**
   * 将 SSE 事件映射到 Store 状态更新
   * 对齐 FRONTEND.md §8.4 事件处理详情
   */
  function handleSSEEvent(eventName, data) {
    switch (eventName) {
      case 'task.created':
        if (current.value && current.value.task_id === data.task_id) {
          current.value.status = data.status || 'running'
          if (data.started_at) current.value.started_at = data.started_at
          appendLog({
            type: 'system',
            icon: 'fa-play',
            level: 'info',
            message: '任务已创建，开始执行',
            timestamp: data.created_at || new Date().toISOString(),
          })
        }
        break

      case 'task.status.snapshot':
        // 重连恢复 — 用快照数据恢复完整进度 UI
        if (current.value) {
          if (data.status) current.value.status = data.status
          if (data.current_phase != null) {
            const shortPhase = normalizePhaseKey(data.current_phase)
            current.value.current_phase = shortPhase
            phaseStates.value = buildPhaseStates(shortPhase)
          }
          if (data.progress) {
            progress.value = {
              completed_steps: data.progress.completed_steps || 0,
              total_steps: data.progress.total_steps || 0,
              progress: data.progress.progress || 0,
            }
          }
          if (data.stats) {
            current.value.total_sources = data.stats.total_sources || 0
            current.value.total_evidence = data.stats.total_evidence || 0
          }
          if (data.steps && Array.isArray(data.steps)) {
            buildLogsFromSnapshot(data.steps)
            // 断点续跑场景：current_phase 为 null 时从已完成 steps 重建阶段状态，
            // 避免进度条图标全部灰色无旋转
            if (data.current_phase == null) {
              phaseStates.value = buildPhaseStatesFromSteps(data.steps, data.current_phase)
            }
          }
          if (data.error) {
            current.value.error_code = data.error.error_code || null
            current.value.error_message = data.error.error_message || null
            current.value.recoverable = data.error.recoverable || false
          }
        }
        break

      case 'phase.started': {
        if (!current.value) break
        const shortPhase = normalizePhaseKey(data.phase)
        current.value.current_phase = shortPhase
        phaseStates.value = buildPhaseStates(shortPhase)
        appendLog({
          type: 'phase',
          icon: 'fa-arrow-right',
          level: 'info',
          message: `进入 ${PHASE_LABELS[shortPhase] || shortPhase} 阶段`,
          timestamp: data.timestamp,
        })
        break
      }

      case 'phase.completed': {
        if (!current.value) break
        const donePhase = normalizePhaseKey(data.phase)
        if (donePhase) {
          phaseStates.value[donePhase] = 'done'
          if (data.duration_ms != null) {
            phaseDurations.value[donePhase] = data.duration_ms
          }
        }
        appendLog({
          type: 'phase',
          icon: 'fa-check-circle',
          level: 'success',
          message: `${PHASE_LABELS[donePhase] || donePhase} 阶段完成${data.duration_ms ? `（耗时 ${formatDurationMs(data.duration_ms)}）` : ''}`,
          timestamp: data.timestamp,
        })
        break
      }

      case 'step.started':
        if (!current.value) break
        ensurePhaseRunning(data.phase)
        upsertStepLog({
          stepId: data.step_id,
          phase: normalizePhaseKey(data.phase),
          stepType: data.step_type,
          status: 'running',
          label: data.label,
          message: data.label || data.step_type,
          startedAt: data.timestamp,
          progress: null,
        })
        break

      case 'step.progress':
        if (!current.value) break
        updateStepLog(data.step_id, {
          progress: data,
        })
        break

      case 'step.completed': {
        if (!current.value) break
        const stepId = data.step_id
        if (completedStepIds.value.has(stepId)) break
        completedStepIds.value.add(stepId)
        updateStepLog(stepId, {
          status: 'completed',
          completedAt: data.timestamp,
          output: data.output,
        })
        break
      }

      case 'step.failed':
        if (!current.value) break
        updateStepLog(data.step_id, {
          status: 'failed',
          errorType: data.error_type,
          errorMessage: data.error_description,
          message: data.error_description || data.step_type,
          completedAt: data.timestamp,
        })
        break

      case 'step.skipped':
        if (!current.value) break
        updateStepLog(data.step_id, {
          status: 'skipped',
          skipReason: data.reason,
          message: data.reason || data.step_type,
          completedAt: data.timestamp,
        })
        break

      case 'task.progress':
        if (data.completed_steps != null) progress.value.completed_steps = data.completed_steps
        if (data.total_steps != null) progress.value.total_steps = data.total_steps
        if (data.progress != null) progress.value.progress = data.progress
        break

      case 'checkpoint.saved':
        if (!current.value) break
        lastCheckpoint.value = {
          phase: normalizePhaseKey(data.phase),
          stepId: data.last_completed_step_id,
          savedAt: data.saved_at,
        }
        appendLog({
          type: 'checkpoint',
          icon: 'fa-save',
          level: 'warning',
          message: '已保存进度',
          timestamp: data.saved_at,
        })
        break

      case 'task.warning':
        if (!current.value) break
        warnings.value.push({
          stepId: data.step_id,
          description: data.error_description,
          timestamp: data.timestamp,
        })
        appendLog({
          type: 'warning',
          icon: 'fa-exclamation-triangle',
          level: 'warning',
          message: `警告：${data.error_description || ''}`,
          timestamp: data.timestamp,
        })
        break

      case 'task.completed':
        if (current.value) {
          current.value.status = 'completed'
          current.value.completed_at = data.timestamp || new Date().toISOString()
          // 从 trace 摘要中提取统计
          if (data.trace) {
            current.value.total_sources = data.trace.sources ?? current.value.total_sources
            current.value.total_evidence = data.trace.evidence ?? current.value.total_evidence
          }
        }
        appendLog({
          type: 'system',
          icon: 'fa-trophy',
          level: 'success',
          message: `研究完成！共 ${current.value?.total_evidence || 0} 个参考来源`,
          timestamp: data.timestamp,
        })
        disconnectSSE()
        break

      case 'task.failed':
        if (current.value) {
          current.value.status = 'failed'
          // SSE task.failed 的 error_type 按 API.md 应为标准错误码（如 E3110）。
          // 兼容后端发送异常类名的历史情况：优先取 E 系列码，否则从描述中解析。
          const sseErrorCode = normalizeErrorCode(data.error_type, data.error_description)
          current.value.error_code = sseErrorCode || data.error_type || null
          current.value.error_message = data.error_description || null
          current.value.recoverable = data.recoverable || false
        }
        appendLog({
          type: 'system',
          icon: 'fa-times-circle',
          level: 'error',
          message: `研究失败：${data.error_description || ''}`,
          timestamp: data.timestamp,
        })
        disconnectSSE()
        break

      case 'task.canceled':
        if (current.value) {
          current.value.status = 'canceled'
        }
        appendLog({
          type: 'system',
          icon: 'fa-ban',
          level: 'muted',
          message: '研究已取消',
          timestamp: data.timestamp,
        })
        disconnectSSE()
        break

      default:
        break
    }
  }

  // ========== 日志辅助函数 ==========

  /**
   * 向 stepLogs 追加一条系统/阶段/警告日志
   */
  function appendLog(log) {
    stepLogs.value.push({
      id: `log-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      type: log.type || 'system',
      icon: log.icon || 'fa-info-circle',
      level: log.level || 'info',
      message: log.message || '',
      timestamp: log.timestamp || new Date().toISOString(),
    })
  }

  /**
   * 根据 step_id 更新 Step 日志；不存在则追加
   */
  function upsertStepLog(log) {
    const idx = stepLogs.value.findIndex(l => l.stepId === log.stepId)
    const logWithTimestamp = {
      ...log,
      timestamp: log.timestamp || new Date().toISOString(),
    }
    if (idx >= 0) {
      stepLogs.value[idx] = { ...stepLogs.value[idx], ...logWithTimestamp }
    } else {
      stepLogs.value.push({
        id: `step-${log.stepId}`,
        type: 'step',
        icon: 'fa-spinner fa-spin',
        level: 'info',
        ...logWithTimestamp,
      })
    }
  }

  /**
   * 根据 step_id 局部更新 Step 日志
   */
  function updateStepLog(stepId, patch) {
    const idx = stepLogs.value.findIndex(l => l.stepId === stepId)
    const patchWithTimestamp = {
      ...patch,
      timestamp: patch.timestamp || new Date().toISOString(),
    }
    if (idx >= 0) {
      stepLogs.value[idx] = { ...stepLogs.value[idx], ...patchWithTimestamp }
    } else {
      stepLogs.value.push({
        id: `step-${stepId}`,
        type: 'step',
        icon: 'fa-spinner fa-spin',
        level: 'info',
        stepId,
        status: 'running',
        ...patchWithTimestamp,
      })
    }
  }

  /**
   * 若某 step 到来时对应阶段未 running，则将该阶段置为 running
   */
  function ensurePhaseRunning(phase) {
    const short = normalizePhaseKey(phase)
    if (!short) return
    if (phaseStates.value[short] !== 'running') {
      phaseStates.value = buildPhaseStates(short)
    }
  }

  /**
   * SSE task.failed 的 error_type 到标准 E 系列错误码的映射。
   * 后端 SSE 发送的是 detail.error_type（如 "RerankFailed"），
   * 而详情接口返回的是 error_code（如 "E3105"），统一映射后前端状态一致。
   */
  const ERROR_TYPE_TO_CODE = {
    'PlanningFailed': 'E3101',
    'SearchFailed': 'E3102',
    'InsufficientEvidence': 'E3103',
    'SynthesisFailed': 'E3104',
    'RerankFailed': 'E3105',
    'EvidenceGraphFailed': 'E3106',
    'RenderFailed': 'E3107',
    'LLMTimeout': 'E3108',
    'LLMRateLimit': 'E3109',
    'LLMAuthFailed': 'E3110',
    'LLMUnknown': 'E3111',
    'CeleryWorkerLost': 'E3112',
    'CeleryWorkerNotPickedUp': 'E3113',
    'UnknownInternal': 'E3999',
  }

  /**
   * 规范化错误码：确保返回标准 E 系列错误码。
   * 优先级：直接 E 码 > error_type 字符串映射 > 从 description 中解析 > 自由文本匹配。
   */
  function normalizeErrorCode(raw, description) {
    if (!raw && !description) return null
    if (raw && /^E\d{4}$/.test(raw)) return raw

    // SSE error_type 字符串（如 "RerankFailed"）映射为 E 码
    if (raw && ERROR_TYPE_TO_CODE[raw]) return ERROR_TYPE_TO_CODE[raw]

    const candidate = description || raw || ''
    const m = String(candidate).match(/["']code["']\s*:\s*["'](E\d{4})["']/)
    if (m) return m[1]

    // 从自由文本中匹配独立的 E 系列码
    const free = String(candidate).match(/\bE\d{4}\b/)
    if (free) return free[0]

    return null
  }

  /**
   * 毫秒数 → 可读耗时
   */
  function formatDurationMs(ms) {
    if (ms < 1000) return `${ms}ms`
    const s = ms / 1000
    if (s < 60) return `${s.toFixed(1)}s`
    const m = Math.floor(s / 60)
    const rs = Math.round(s % 60)
    return `${m}m${rs}s`
  }

  // ========== 导出 ==========

  return {
    // 状态
    taskList,
    current,
    currentPage,
    total,
    pageSize,
    loading,
    listLoading,
    hasMore,
    sseStatus,
    progress,
    sseConnection,

    // 运行态实时状态
    stepLogs,
    phaseStates,
    phaseDurations,
    lastCheckpoint,
    warnings,
    completedStepIds,

    // 方法
    createTask,
    fetchList,
    fetchMore,
    fetchDetail,
    deleteTask,
    cancelTask,
    retryTask,
    connectSSE: connectSSEToTask,
    disconnectSSE,
    clearCurrent,
    handleSSEEvent,
    resetRuntimeState,
    buildLogsFromSnapshot,
  }
})
