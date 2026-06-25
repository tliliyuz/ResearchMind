import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as researchApi from '@/api/research'
import { connectSSE } from '@/utils/sse'

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

  // ========== Actions ==========

  /**
   * 创建研究任务
   * @param {string} topic - 研究主题
   * @param {object} requirements - { task_type, depth, max_sources, language }
   * @returns {object} { task_id, status, created_at }
   */
  async function createTask(topic, requirements) {
    loading.value = true
    try {
      const res = await researchApi.createTask(topic, requirements)
      const taskData = res.data.data
      // 设置当前任务（初始状态）
      current.value = {
        task_id: taskData.task_id,
        topic,
        status: taskData.status,
        requirements,
        current_phase: null,
        progress: { completed_steps: 0, total_steps: 0, progress: 0 },
        total_sources: 0,
        total_evidence: 0,
        error_code: null,
        error_message: null,
        recoverable: false,
        created_at: taskData.created_at,
        started_at: null,
        completed_at: null,
      }
      sseStatus.value = 'disconnected'
      return taskData
    } finally {
      loading.value = false
    }
  }

  /**
   * 获取任务历史列表
   * @param {object} params - { page, page_size, status, keyword }
   */
  async function fetchList(params = {}) {
    listLoading.value = true
    try {
      const res = await researchApi.getTaskList({
        page: params.page || 1,
        page_size: params.page_size || 20,
        status: params.status || undefined,
        keyword: params.keyword || undefined,
      })
      const data = res.data.data
      taskList.value = data.items || []
      total.value = data.total || 0
      currentPage.value = data.page || 1
      pageSize.value = data.page_size || 20
    } finally {
      listLoading.value = false
    }
  }

  /**
   * 获取任务详情并设为 current
   * @param {string} taskId - 任务 UUID
   * @returns {object} 任务详情
   */
  async function fetchDetail(taskId) {
    loading.value = true
    try {
      const res = await researchApi.getTaskDetail(taskId)
      const data = res.data.data
      current.value = {
        task_id: data.task_id,
        topic: data.topic,
        status: data.status,
        current_phase: data.current_phase || null,
        requirements: data.requirements || {},
        progress: data.progress || { completed_steps: 0, total_steps: 0, progress: 0 },
        total_sources: data.total_sources || 0,
        total_evidence: data.total_evidence || 0,
        error_code: data.error_code || null,
        error_message: data.error_message || null,
        recoverable: data.recoverable || false,
        created_at: data.created_at || null,
        started_at: data.started_at || null,
        completed_at: data.completed_at || null,
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
    // 不立即断开 SSE 或设置状态 —— 等待 task.canceled SSE 事件
    // SSE 事件处理器（handleSSEEvent）会在收到事件后更新状态并断开连接
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
   * 清空当前任务，回到创建态
   */
  function clearCurrent() {
    disconnectSSE()
    current.value = null
    progress.value = { completed_steps: 0, total_steps: 0, progress: 0 }
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
        }
        break

      case 'task.status.snapshot':
        // 重连恢复 — 用快照数据恢复完整进度 UI
        if (current.value) {
          if (data.status) current.value.status = data.status
          if (data.current_phase != null) current.value.current_phase = data.current_phase
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
        }
        break

      case 'phase.started':
        if (current.value) {
          current.value.current_phase = data.phase || null
        }
        break

      case 'phase.completed':
        // 阶段完成（Phase 3 进度条使用）
        break

      case 'step.started':
      case 'step.progress':
        // 步骤事件（Phase 3 StepLog 使用）
        break

      case 'step.completed':
        // 单步完成，递增进度
        progress.value.completed_steps = Math.max(
          progress.value.completed_steps,
          (progress.value.completed_steps || 0) + 1
        )
        break

      case 'step.failed':
      case 'step.skipped':
        // 步骤失败/跳过（Phase 3 日志使用）
        break

      case 'task.progress':
        if (data.completed_steps != null) progress.value.completed_steps = data.completed_steps
        if (data.total_steps != null) progress.value.total_steps = data.total_steps
        if (data.progress != null) progress.value.progress = data.progress
        break

      case 'checkpoint.saved':
        // 已保存进度（Phase 4 Retry 使用）
        break

      case 'task.warning':
        // 警告（Phase 3 日志使用）
        break

      case 'task.completed':
        if (current.value) {
          current.value.status = 'completed'
          // 从 trace 摘要中提取统计
          if (data.trace) {
            current.value.total_sources = data.trace.sources || current.value.total_sources
            current.value.total_evidence = data.trace.evidence || current.value.total_evidence
          }
        }
        disconnectSSE()
        break

      case 'task.failed':
        if (current.value) {
          current.value.status = 'failed'
          current.value.error_code = data.error_type || null
          current.value.error_message = data.error_description || null
          current.value.recoverable = data.recoverable || false
        }
        disconnectSSE()
        break

      case 'task.canceled':
        if (current.value) {
          current.value.status = 'canceled'
        }
        disconnectSSE()
        break

      default:
        break
    }
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
    sseStatus,
    progress,
    sseConnection,

    // 方法
    createTask,
    fetchList,
    fetchDetail,
    deleteTask,
    cancelTask,
    connectSSE: connectSSEToTask,
    disconnectSSE,
    clearCurrent,
    handleSSEEvent,
  }
})
