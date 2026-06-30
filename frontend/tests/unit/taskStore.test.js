/**
 * TaskStore 单元测试 — 覆盖 src/stores/task.js
 *
 * 对齐 ROADMAP.md §3.9：
 *   - create() → current 更新 → SSE 自动连接
 *   - fetchList() 分页
 *   - cancel() → SSE 断开
 *   - sseStatus 5 态流转
 *   - deleteTask() 本地移除 + 空页回退
 *   - fetchDetail() 设置 current
 *   - handleSSEEvent 各事件类型处理
 *
 * Mock 策略：在 API 边界截断（@/api/research + @/utils/sse），
 * Store 核心逻辑真实运行。
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { useTaskStore } from '@/stores/task'
import * as researchApi from '@/api/research'

// Mock API 模块
vi.mock('@/api/research', () => ({
  createTask: vi.fn(),
  getTaskList: vi.fn(),
  getTaskDetail: vi.fn(),
  deleteTask: vi.fn(),
  cancelTask: vi.fn(),
  retryTask: vi.fn(),
  getTaskState: vi.fn(),
}))

// Mock SSE 模块
vi.mock('@/utils/sse', () => ({
  connectSSE: vi.fn(() => ({ close: vi.fn() })),
}))

import { connectSSE } from '@/utils/sse'

// ===== 辅助函数 =====

function mockApiResponse(data) {
  return { data: { data } }
}

describe('TaskStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  // ===== createTask =====

  describe('createTask', () => {
    it('创建成功_current 包含 task_id 和 topic', async () => {
      researchApi.createTask.mockResolvedValue(
        mockApiResponse({ task_id: 'task-001', status: 'pending', created_at: '2026-06-24T10:00:00Z' })
      )

      const store = useTaskStore()
      const result = await store.createTask('量子计算的影响', {
        task_type: 'analysis',
        depth: 'quick',
        max_sources: 10,
        language: 'zh',
      })

      expect(result.task_id).toBe('task-001')
      expect(store.current.task_id).toBe('task-001')
      expect(store.current.topic).toBe('量子计算的影响')
      expect(store.current.status).toBe('pending')
      expect(store.current.requirements.task_type).toBe('analysis')
    })

    it('创建后 sseStatus 重置为 disconnected', async () => {
      researchApi.createTask.mockResolvedValue(
        mockApiResponse({ task_id: 'task-002', status: 'pending', created_at: '2026-06-24T10:00:00Z' })
      )

      const store = useTaskStore()
      store.sseStatus = 'connected'
      await store.createTask('测试主题', {
        task_type: 'explainer',
        depth: 'quick',
        max_sources: 5,
        language: 'en',
      })

      expect(store.sseStatus).toBe('disconnected')
    })

    it('创建失败_API 异常抛出_loading 恢复并回滚到创建态', async () => {
      researchApi.createTask.mockRejectedValue(new Error('网络错误'))

      const store = useTaskStore()
      await expect(
        store.createTask('测试', { task_type: 'comparison', depth: 'quick', max_sources: 10, language: 'zh' })
      ).rejects.toThrow('网络错误')

      expect(store.loading).toBe(false)
      expect(store.current).toBeNull()
    })

    it('创建 API 未返回前_已乐观进入运行态', async () => {
      const apiDeferred = {}
      apiDeferred.promise = new Promise((resolve) => {
        apiDeferred.resolve = resolve
      })
      researchApi.createTask.mockReturnValue(apiDeferred.promise)

      const store = useTaskStore()
      const callPromise = store.createTask('量子计算的影响', {
        task_type: 'analysis',
        depth: 'quick',
        max_sources: 10,
        language: 'zh',
      })

      expect(store.current).not.toBeNull()
      expect(store.current.status).toBe('running')
      expect(store.current.task_id).toBeNull()
      expect(store.progress.total_steps).toBe(7)

      apiDeferred.resolve(mockApiResponse({ task_id: 'task-004', status: 'pending', created_at: '2026-06-24T10:00:00Z' }))
      await callPromise

      expect(store.current.task_id).toBe('task-004')
      expect(store.current.status).toBe('pending')
    })

    it('创建成功_刷新侧边栏最近任务', async () => {
      researchApi.createTask.mockResolvedValue(
        mockApiResponse({ task_id: 'task-003', status: 'pending', created_at: '2026-06-24T10:00:00Z' })
      )
      researchApi.getTaskList.mockResolvedValue(
        mockApiResponse({
          items: [{ task_id: 'task-003', topic: '量子计算的影响', status: 'pending' }],
          total: 1,
          page: 1,
          page_size: 20,
        })
      )

      const store = useTaskStore()
      await store.createTask('量子计算的影响', {
        task_type: 'analysis',
        depth: 'quick',
        max_sources: 10,
        language: 'zh',
      })

      expect(researchApi.getTaskList).toHaveBeenCalledWith({ page: 1, page_size: 20 })
      expect(store.taskList).toHaveLength(1)
    })
  })

  // ===== fetchList =====

  describe('fetchList', () => {
    it('获取列表成功_taskList 和 total 正确赋值', async () => {
      researchApi.getTaskList.mockResolvedValue(
        mockApiResponse({
          items: [
            { task_id: 't1', topic: '主题A', status: 'completed' },
            { task_id: 't2', topic: '主题B', status: 'running' },
          ],
          total: 2,
          page: 1,
          page_size: 20,
        })
      )

      const store = useTaskStore()
      await store.fetchList({ page: 1, page_size: 20 })

      expect(store.taskList).toHaveLength(2)
      expect(store.taskList[0].task_id).toBe('t1')
      expect(store.total).toBe(2)
      expect(store.currentPage).toBe(1)
    })

    it('空列表_taskList 为空数组_total 为 0', async () => {
      researchApi.getTaskList.mockResolvedValue(
        mockApiResponse({ items: [], total: 0, page: 1, page_size: 20 })
      )

      const store = useTaskStore()
      await store.fetchList()

      expect(store.taskList).toEqual([])
      expect(store.total).toBe(0)
    })

    it('status 筛选参数正确传递', async () => {
      researchApi.getTaskList.mockResolvedValue(
        mockApiResponse({ items: [], total: 0, page: 1, page_size: 20 })
      )

      const store = useTaskStore()
      await store.fetchList({ status: 'completed' })

      expect(researchApi.getTaskList).toHaveBeenCalledWith({
        page: 1,
        page_size: 20,
        status: 'completed',
      })
    })

    it('第二页数据正确加载', async () => {
      researchApi.getTaskList.mockResolvedValue(
        mockApiResponse({
          items: [{ task_id: 't3', topic: '第三页主题', status: 'failed' }],
          total: 45,
          page: 3,
          page_size: 20,
        })
      )

      const store = useTaskStore()
      await store.fetchList({ page: 3, page_size: 20 })

      expect(store.currentPage).toBe(3)
      expect(store.total).toBe(45)
    })

    it('append=true_追加到已有列表', async () => {
      const store = useTaskStore()
      store.taskList = [{ task_id: 't1', topic: '主题A', status: 'completed' }]
      store.total = 3
      store.currentPage = 1
      store.pageSize = 20

      researchApi.getTaskList.mockResolvedValue(
        mockApiResponse({
          items: [{ task_id: 't2', topic: '主题B', status: 'running' }],
          total: 3,
          page: 2,
          page_size: 20,
        })
      )

      await store.fetchList({ page: 2, page_size: 20, append: true })

      expect(store.taskList).toHaveLength(2)
      expect(store.taskList[0].task_id).toBe('t1')
      expect(store.taskList[1].task_id).toBe('t2')
      expect(store.currentPage).toBe(2)
    })
  })

  // ===== fetchMore =====

  describe('fetchMore', () => {
    it('hasMore为true_加载下一页并追加', async () => {
      const store = useTaskStore()
      store.taskList = [{ task_id: 't1', topic: '主题A', status: 'completed' }]
      store.total = 3
      store.currentPage = 1
      store.pageSize = 20

      researchApi.getTaskList.mockResolvedValue(
        mockApiResponse({
          items: [
            { task_id: 't2', topic: '主题B', status: 'running' },
            { task_id: 't3', topic: '主题C', status: 'pending' },
          ],
          total: 3,
          page: 2,
          page_size: 20,
        })
      )

      await store.fetchMore()

      expect(researchApi.getTaskList).toHaveBeenCalledWith({ page: 2, page_size: 20 })
      expect(store.taskList).toHaveLength(3)
      expect(store.hasMore).toBe(false)
    })

    it('hasMore为false_不发起请求', async () => {
      const store = useTaskStore()
      store.taskList = [{ task_id: 't1', topic: '主题A', status: 'completed' }]
      store.total = 1
      store.currentPage = 1
      store.pageSize = 20

      await store.fetchMore()

      expect(researchApi.getTaskList).not.toHaveBeenCalled()
    })

    it('加载中_不重复请求', async () => {
      const store = useTaskStore()
      store.taskList = [{ task_id: 't1', topic: '主题A', status: 'completed' }]
      store.total = 3
      store.currentPage = 1
      store.pageSize = 20
      store.listLoading = true

      await store.fetchMore()

      expect(researchApi.getTaskList).not.toHaveBeenCalled()
    })

    it('total异常但当前页满载_仍可尝试加载下一页', async () => {
      const store = useTaskStore()
      store.taskList = Array.from({ length: 20 }, (_, i) => ({
        task_id: `t${i + 1}`,
        topic: `主题${i + 1}`,
        status: 'completed',
      }))
      store.total = 0
      store.currentPage = 1
      store.pageSize = 20

      researchApi.getTaskList.mockResolvedValue(
        mockApiResponse({
          items: [{ task_id: 't21', topic: '主题21', status: 'pending' }],
          total: 0,
          page: 2,
          page_size: 20,
        })
      )

      await store.fetchMore()

      expect(researchApi.getTaskList).toHaveBeenCalledWith({ page: 2, page_size: 20 })
      expect(store.taskList).toHaveLength(21)
    })

    it('total等于已加载数量时_hasMore为false不再加载', async () => {
      const store = useTaskStore()
      store.taskList = Array.from({ length: 20 }, (_, i) => ({
        task_id: `t${i + 1}`,
        topic: `主题${i + 1}`,
        status: 'completed',
      }))
      store.total = 20
      store.currentPage = 1
      store.pageSize = 20

      await store.fetchMore()

      expect(researchApi.getTaskList).not.toHaveBeenCalled()
      expect(store.hasMore).toBe(false)
    })

    it('total异常时加载到不满页后_hasMore变为false', async () => {
      const store = useTaskStore()
      store.taskList = Array.from({ length: 20 }, (_, i) => ({
        task_id: `t${i + 1}`,
        topic: `主题${i + 1}`,
        status: 'completed',
      }))
      store.total = 0
      store.currentPage = 1
      store.pageSize = 20

      researchApi.getTaskList.mockResolvedValue(
        mockApiResponse({
          items: [],
          total: 0,
          page: 2,
          page_size: 20,
        })
      )

      await store.fetchMore()

      expect(researchApi.getTaskList).toHaveBeenCalledWith({ page: 2, page_size: 20 })
      expect(store.hasMore).toBe(false)
    })
  })

  // ===== fetchDetail =====

  describe('fetchDetail', () => {
    it('获取详情成功_current 包含完整字段', async () => {
      researchApi.getTaskDetail.mockResolvedValue(
        mockApiResponse({
          task_id: 'task-detail-1',
          topic: '深度学习研究',
          status: 'running',
          current_phase: 'search',
          requirements: { task_type: 'explainer', depth: 'quick', max_sources: 10, language: 'zh' },
          progress: { completed_steps: 3, total_steps: 10, progress: 30 },
          total_sources: 5,
          total_evidence: 2,
          created_at: '2026-06-24T08:00:00Z',
          started_at: '2026-06-24T08:00:05Z',
          completed_at: null,
        })
      )

      const store = useTaskStore()
      const data = await store.fetchDetail('task-detail-1')

      expect(store.current.task_id).toBe('task-detail-1')
      expect(store.current.current_phase).toBe('search')
      expect(store.current.progress.progress).toBe(30)
      expect(data.status).toBe('running')
    })

    it('失败任务按 API.md 嵌套 error 对象读取错误信息', async () => {
      researchApi.getTaskDetail.mockResolvedValue(
        mockApiResponse({
          task_id: 'task-failed-1',
          topic: '失败的研究',
          status: 'failed',
          current_phase: 'planning',
          progress: { completed_steps: 1, total_steps: 10, progress: 10 },
          error: {
            error_code: 'E3101',
            error_message: 'Planning 阶段重试耗尽',
            recoverable: false,
          },
          created_at: '2026-06-24T08:00:00Z',
          started_at: '2026-06-24T08:00:05Z',
          completed_at: '2026-06-24T08:00:15Z',
        })
      )

      const store = useTaskStore()
      await store.fetchDetail('task-failed-1')

      expect(store.current.status).toBe('failed')
      expect(store.current.error_code).toBe('E3101')
      expect(store.current.error_message).toBe('Planning 阶段重试耗尽')
      expect(store.current.recoverable).toBe(false)
    })

    it('失败任务兼容顶层错误字段', async () => {
      researchApi.getTaskDetail.mockResolvedValue(
        mockApiResponse({
          task_id: 'task-failed-2',
          topic: '旧格式失败任务',
          status: 'failed',
          error_code: 'E3102',
          error_message: 'Tavily API 不可用',
          recoverable: true,
          created_at: '2026-06-24T08:00:00Z',
        })
      )

      const store = useTaskStore()
      await store.fetchDetail('task-failed-2')

      expect(store.current.error_code).toBe('E3102')
      expect(store.current.error_message).toBe('Tavily API 不可用')
      expect(store.current.recoverable).toBe(true)
    })

    it('不存在的任务_API 异常抛出', async () => {
      const error = {
        response: { status: 404, data: { code: 'E2001' } },
      }
      researchApi.getTaskDetail.mockRejectedValue(error)

      const store = useTaskStore()
      await expect(store.fetchDetail('non-existent')).rejects.toBe(error)
    })

    it('同一任务重新获取时保留已有 stepLogs', async () => {
      researchApi.getTaskDetail.mockResolvedValue(
        mockApiResponse({
          task_id: 'task-same',
          topic: '同一任务',
          status: 'running',
          current_phase: 'search',
          progress: { completed_steps: 1, total_steps: 10, progress: 10 },
          created_at: '2026-06-24T08:00:00Z',
          started_at: '2026-06-24T08:00:05Z',
        })
      )

      const store = useTaskStore()
      store.current = {
        task_id: 'task-same',
        topic: '同一任务',
        status: 'running',
        current_phase: 'planning',
      }
      store.stepLogs = [{ id: 'live-log-1', type: 'phase', message: '进入 任务规划 阶段' }]

      await store.fetchDetail('task-same')

      expect(store.current.task_id).toBe('task-same')
      expect(store.stepLogs).toHaveLength(1)
      expect(store.stepLogs[0].id).toBe('live-log-1')
    })

    it('切换不同任务时重置 stepLogs', async () => {
      researchApi.getTaskDetail.mockResolvedValue(
        mockApiResponse({
          task_id: 'task-new',
          topic: '新任务',
          status: 'running',
          current_phase: 'search',
          progress: { completed_steps: 1, total_steps: 10, progress: 10 },
          created_at: '2026-06-24T08:00:00Z',
          started_at: '2026-06-24T08:00:05Z',
        })
      )

      const store = useTaskStore()
      store.current = {
        task_id: 'task-old',
        topic: '旧任务',
        status: 'running',
      }
      store.stepLogs = [{ id: 'old-log', type: 'phase', message: '旧日志' }]

      await store.fetchDetail('task-new')

      expect(store.current.task_id).toBe('task-new')
      expect(store.stepLogs).toEqual([])
    })

    it('终态 canceled 任务通过 state 端点重建 phaseStates 与 phaseDurations', async () => {
      researchApi.getTaskDetail.mockResolvedValue(
        mockApiResponse({
          task_id: 'task-canceled-1',
          topic: '已取消的研究',
          status: 'canceled',
          current_phase: 'fetch',
          progress: { completed_steps: 2, total_steps: 7, progress: 0.29 },
          created_at: '2026-06-24T08:00:00Z',
          started_at: '2026-06-24T08:00:05Z',
        })
      )
      researchApi.getTaskState.mockResolvedValue(
        mockApiResponse({
          task_id: 'task-canceled-1',
          status: 'canceled',
          current_phase: 'fetch',
          steps: [
            { step_id: 's1', step_type: 'planning', status: 'completed', started_at: '2026-06-24T08:00:05Z', completed_at: '2026-06-24T08:00:10Z', duration_ms: 5000, label: '任务规划' },
            { step_id: 's2', step_type: 'search', status: 'completed', started_at: '2026-06-24T08:00:10Z', completed_at: '2026-06-24T08:00:28Z', duration_ms: 17900, label: '搜索' },
            { step_id: 's3', step_type: 'fetch', status: 'running', started_at: '2026-06-24T08:00:28Z', label: '抓取' },
          ],
        })
      )

      const store = useTaskStore()
      await store.fetchDetail('task-canceled-1')

      expect(researchApi.getTaskState).toHaveBeenCalledWith('task-canceled-1')
      expect(store.phaseStates.planning).toBe('done')
      expect(store.phaseStates.search).toBe('done')
      expect(store.phaseStates.fetch).toBe('running')
      expect(store.phaseStates.rerank).toBe('pending')
      expect(store.phaseDurations.planning).toBe(5000)
      expect(store.phaseDurations.search).toBe(17900)
      expect(store.stepLogs.length).toBe(10)  // planning(4) + search(4) + fetch(2) = 10
    })

    it('终态 completed 任务通过 state 端点标记所有阶段为 done', async () => {
      researchApi.getTaskDetail.mockResolvedValue(
        mockApiResponse({
          task_id: 'task-completed-1',
          topic: '完成的研究',
          status: 'completed',
          current_phase: null,
          progress: { completed_steps: 7, total_steps: 7, progress: 1 },
          created_at: '2026-06-24T08:00:00Z',
          started_at: '2026-06-24T08:00:05Z',
          completed_at: '2026-06-24T08:02:30Z',
        })
      )
      researchApi.getTaskState.mockResolvedValue(
        mockApiResponse({
          task_id: 'task-completed-1',
          status: 'completed',
          current_phase: null,
          steps: [
            { step_id: 's1', step_type: 'planning', status: 'completed', duration_ms: 1000 },
            { step_id: 's2', step_type: 'search', status: 'completed', duration_ms: 2000 },
            { step_id: 's3', step_type: 'fetch', status: 'completed', duration_ms: 3000 },
            { step_id: 's4', step_type: 'rerank', status: 'completed', duration_ms: 4000 },
            { step_id: 's5', step_type: 'synthesis', status: 'completed', duration_ms: 5000 },
            { step_id: 's6', step_type: 'evidence_graph', status: 'completed', duration_ms: 6000 },
            { step_id: 's7', step_type: 'render', status: 'completed', duration_ms: 7000 },
          ],
        })
      )

      const store = useTaskStore()
      await store.fetchDetail('task-completed-1')

      expect(store.phaseStates.planning).toBe('done')
      expect(store.phaseStates.search).toBe('done')
      expect(store.phaseStates.fetch).toBe('done')
      expect(store.phaseStates.rerank).toBe('done')
      expect(store.phaseStates.synthesis).toBe('done')
      expect(store.phaseStates.evidence_graph).toBe('done')
      expect(store.phaseStates.render).toBe('done')
    })

    it('running 任务不调用 state 端点_直接连接 SSE', async () => {
      researchApi.getTaskDetail.mockResolvedValue(
        mockApiResponse({
          task_id: 'task-running-1',
          topic: '运行中研究',
          status: 'running',
          current_phase: 'search',
          progress: { completed_steps: 2, total_steps: 7, progress: 0.29 },
          created_at: '2026-06-24T08:00:00Z',
          started_at: '2026-06-24T08:00:05Z',
        })
      )

      const store = useTaskStore()
      await store.fetchDetail('task-running-1')

      expect(researchApi.getTaskState).not.toHaveBeenCalled()
      expect(store.sseConnection).not.toBeNull()
    })

    it('fetchDetail 加载任务后同步更新 taskList 中对应条目', async () => {
      researchApi.getTaskDetail.mockResolvedValue(
        mockApiResponse({
          task_id: 't1',
          topic: '主题A',
          status: 'completed',
          current_phase: null,
          progress: { completed_steps: 7, total_steps: 7, progress: 1 },
          created_at: '2026-06-24T08:00:00Z',
          started_at: '2026-06-24T08:00:05Z',
          completed_at: '2026-06-24T08:02:30Z',
        })
      )
      researchApi.getTaskState.mockResolvedValue(
        mockApiResponse({
          task_id: 't1',
          status: 'completed',
          current_phase: null,
          steps: [],
        })
      )

      const store = useTaskStore()
      store.taskList = [{ task_id: 't1', topic: '主题A', status: 'running', current_phase: 'search' }]

      await store.fetchDetail('t1')
      await nextTick()

      expect(store.taskList[0].status).toBe('completed')
      expect(store.taskList[0].completed_at).toBe('2026-06-24T08:02:30Z')
    })
  })

  // ===== deleteTask =====

  describe('deleteTask', () => {
    it('删除成功_本地 taskList 移除_target total 减 1', async () => {
      researchApi.deleteTask.mockResolvedValue({})

      const store = useTaskStore()
      store.taskList = [
        { task_id: 't1', topic: 'A' },
        { task_id: 't2', topic: 'B' },
        { task_id: 't3', topic: 'C' },
      ]
      store.total = 3

      await store.deleteTask('t2')

      expect(store.taskList).toHaveLength(2)
      expect(store.taskList.map((t) => t.task_id)).toEqual(['t1', 't3'])
      expect(store.total).toBe(2)
    })

    it('删除的是当前查看的任务_清空 current', async () => {
      researchApi.deleteTask.mockResolvedValue({})

      const store = useTaskStore()
      store.current = { task_id: 't1', topic: 'A', status: 'completed' }
      store.taskList = [{ task_id: 't1', topic: 'A' }]
      store.total = 1

      await store.deleteTask('t1')

      expect(store.current).toBeNull()
    })

    it('删除的不是当前任务_current 保持不变', async () => {
      researchApi.deleteTask.mockResolvedValue({})

      const store = useTaskStore()
      store.current = { task_id: 't1', topic: 'A', status: 'completed' }
      store.taskList = [
        { task_id: 't1', topic: 'A' },
        { task_id: 't2', topic: 'B' },
      ]
      store.total = 2

      await store.deleteTask('t2')

      expect(store.current).not.toBeNull()
      expect(store.current.task_id).toBe('t1')
    })
  })

  // ===== cancelTask =====

  describe('cancelTask', () => {
    it('取消成功_断开 SSE_更新 current.status 为 canceled', async () => {
      researchApi.cancelTask.mockResolvedValue({})

      const store = useTaskStore()
      store.current = { task_id: 't1', topic: 'A', status: 'running' }
      store.sseStatus = 'connected'
      store.sseConnection = { close: vi.fn() }

      await store.cancelTask('t1')

      expect(store.sseStatus).toBe('disconnected')
      expect(store.current.status).toBe('canceled')
      expect(researchApi.cancelTask).toHaveBeenCalledWith('t1')
    })

    it('取消成功后同步更新 taskList 中该任务状态', async () => {
      researchApi.cancelTask.mockResolvedValue({})

      const store = useTaskStore()
      store.current = { task_id: 't1', topic: 'A', status: 'running' }
      store.taskList = [{ task_id: 't1', topic: 'A', status: 'running' }]
      store.sseConnection = { close: vi.fn() }

      await store.cancelTask('t1')
      await nextTick()

      expect(store.taskList[0].status).toBe('canceled')
    })

    it('取消非当前任务_不更新 current', async () => {
      researchApi.cancelTask.mockResolvedValue({})

      const store = useTaskStore()
      store.current = { task_id: 't1', topic: 'A', status: 'running' }

      await store.cancelTask('t2')

      expect(store.current.status).toBe('running')
    })
  })

  // ===== retryTask =====

  describe('retryTask', () => {
    it('API 调用前立即乐观更新 current 为 running', async () => {
      const apiDeferred = {}
      apiDeferred.promise = new Promise((resolve, reject) => {
        apiDeferred.resolve = resolve
        apiDeferred.reject = reject
      })
      researchApi.retryTask.mockReturnValue(apiDeferred.promise)

      const store = useTaskStore()
      store.current = {
        task_id: 'task-retry-1',
        topic: '失败的研究',
        status: 'failed',
        error_code: 'E3104',
        error_message: 'Synthesis 失败',
        recoverable: true,
      }

      const callPromise = store.retryTask('task-retry-1')

      // API 尚未返回，状态已立即切换到 running
      expect(store.current.status).toBe('running')
      expect(store.current.error_code).toBeNull()
      expect(store.current.error_message).toBeNull()
      expect(store.current.recoverable).toBe(false)

      apiDeferred.resolve(mockApiResponse({ task_id: 'task-retry-1', status: 'running' }))
      await callPromise
    })

    it('API 成功后建立 SSE 连接', async () => {
      researchApi.retryTask.mockResolvedValue(
        mockApiResponse({ task_id: 'task-retry-2', status: 'running' })
      )

      const store = useTaskStore()
      store.current = {
        task_id: 'task-retry-2',
        topic: '可恢复的研究',
        status: 'failed',
        error_code: 'E3101',
        error_message: 'Planning 失败',
        recoverable: true,
      }

      await store.retryTask('task-retry-2')

      expect(connectSSE).toHaveBeenCalledWith('/api/research/task-retry-2/stream', expect.any(Object))
      expect(store.sseConnection).not.toBeNull()
    })

    it('API 失败时回滚到原状态并继续展示失败视图', async () => {
      const apiError = {
        response: { status: 409, data: { detail: { error_description: '当前状态不支持断点续跑' } } },
      }
      researchApi.retryTask.mockRejectedValue(apiError)

      const store = useTaskStore()
      store.current = {
        task_id: 'task-retry-3',
        topic: '冲突的研究',
        status: 'failed',
        error_code: 'E3102',
        error_message: 'Search 失败',
        recoverable: true,
      }

      await expect(store.retryTask('task-retry-3')).rejects.toBe(apiError)

      expect(store.current.status).toBe('failed')
      expect(store.current.error_code).toBe('E3102')
      expect(store.current.error_message).toBe('Search 失败')
      expect(store.current.recoverable).toBe(true)
    })

    it('current 为空时不影响调用', async () => {
      researchApi.retryTask.mockResolvedValue(
        mockApiResponse({ task_id: 'task-retry-4', status: 'running' })
      )

      const store = useTaskStore()
      store.current = null

      const result = await store.retryTask('task-retry-4')

      expect(result.status).toBe('running')
      expect(connectSSE).toHaveBeenCalled()
    })
  })

  // ===== connectSSE / disconnectSSE =====

  describe('connectSSE / disconnectSSE — SSE 连接管理', () => {
    it('connectSSE 设置 sseStatus 为 connecting_然后 connected', async () => {
      connectSSE.mockImplementation((url, opts) => {
        opts.onStatusChange('connecting')
        opts.onStatusChange('connected')
        return { close: vi.fn() }
      })

      const store = useTaskStore()
      await store.connectSSE('task-001')

      expect(store.sseStatus).toBe('connected')
      expect(connectSSE).toHaveBeenCalled()
      expect(store.sseConnection).not.toBeNull()
    })

    it('disconnectSSE 关闭连接_设置 disconnected', () => {
      const closeFn = vi.fn()
      const store = useTaskStore()
      store.sseConnection = { close: closeFn }
      store.sseStatus = 'connected'

      store.disconnectSSE()

      expect(closeFn).toHaveBeenCalled()
      expect(store.sseStatus).toBe('disconnected')
      expect(store.sseConnection).toBeNull()
    })

    it('重复 disconnectSSE 不报错', () => {
      const store = useTaskStore()
      store.disconnectSSE()
      store.disconnectSSE()
      expect(store.sseStatus).toBe('disconnected')
    })

    it('clearCurrent 断开 SSE 并清空 current', () => {
      const store = useTaskStore()
      store.current = { task_id: 't1', topic: 'A', status: 'completed' }
      store.sseConnection = { close: vi.fn() }
      store.sseStatus = 'connected'

      store.clearCurrent()

      expect(store.current).toBeNull()
      expect(store.sseStatus).toBe('disconnected')
      expect(store.progress.progress).toBe(0)
    })
  })

  // ===== handleSSEEvent =====

  describe('handleSSEEvent — SSE 事件处理', () => {
    function makeStore() {
      const store = useTaskStore()
      store.current = { task_id: 'task-001', topic: '测试', status: 'running' }
      return store
    }

    it('task.created 更新 current.status 为 running', () => {
      const store = makeStore()
      store.handleSSEEvent('task.created', { task_id: 'task-001', status: 'running' })
      expect(store.current.status).toBe('running')
    })

    it('task.created 不同 task_id_不更新', () => {
      const store = makeStore()
      store.current.status = 'pending'
      store.handleSSEEvent('task.created', { task_id: 'other-task', status: 'running' })
      expect(store.current.status).toBe('pending')
    })

    it('task.created 同步更新 taskList 中对应任务状态', async () => {
      const store = makeStore()
      store.current.status = 'pending'
      store.taskList = [{ task_id: 'task-001', topic: '测试', status: 'pending' }]

      store.handleSSEEvent('task.created', { task_id: 'task-001', status: 'running' })
      await nextTick()

      expect(store.taskList[0].status).toBe('running')
    })

    it('task.status.snapshot 恢复完整进度', () => {
      const store = makeStore()
      store.handleSSEEvent('task.status.snapshot', {
        status: 'running',
        current_phase: 'search',
        progress: { completed_steps: 5, total_steps: 20, progress: 25 },
        stats: { total_sources: 8, total_evidence: 3 },
      })

      expect(store.current.current_phase).toBe('search')
      expect(store.progress.completed_steps).toBe(5)
      expect(store.progress.total_steps).toBe(20)
      expect(store.current.total_sources).toBe(8)
      expect(store.current.total_evidence).toBe(3)
    })

    it('phase.started 更新 current.current_phase', () => {
      const store = makeStore()
      store.handleSSEEvent('phase.started', { phase: 'planning' })
      expect(store.current.current_phase).toBe('planning')
    })

    it('task.progress 更新进度', () => {
      const store = makeStore()
      store.handleSSEEvent('task.progress', { completed_steps: 3, total_steps: 10, progress: 30 })
      expect(store.progress.completed_steps).toBe(3)
      expect(store.progress.progress).toBe(30)
    })

    it('task.completed 设置状态并断开 SSE', () => {
      const store = makeStore()
      store.handleSSEEvent('task.completed', {
        trace: { sources: 12, evidence: 5 },
      })
      expect(store.current.status).toBe('completed')
      expect(store.sseStatus).toBe('disconnected')
    })

    it('task.completed 同步更新 taskList 中对应任务状态', async () => {
      const store = makeStore()
      store.taskList = [{ task_id: 'task-001', topic: '测试', status: 'running' }]

      store.handleSSEEvent('task.completed', { trace: { sources: 1, evidence: 1 } })
      await nextTick()

      expect(store.taskList[0].status).toBe('completed')
    })

    it('task.failed 设置错误信息并断开 SSE', () => {
      const store = makeStore()
      store.handleSSEEvent('task.failed', {
        error_type: 'E3101',
        error_description: 'Planning 失败：无法拆解主题',
        recoverable: true,
      })
      expect(store.current.status).toBe('failed')
      expect(store.current.error_code).toBe('E3101')
      expect(store.current.error_message).toContain('Planning 失败')
      expect(store.current.recoverable).toBe(true)
      expect(store.sseStatus).toBe('disconnected')
    })

    it('task.failed error_type 为异常类名时_尝试从描述提取标准错误码', () => {
      const store = makeStore()
      store.handleSSEEvent('task.failed', {
        error_type: 'LLMAuthFailedException',
        error_description: "500: {'code': 'E3110', 'message': 'LLM 认证失败'}",
        recoverable: false,
      })
      expect(store.current.status).toBe('failed')
      expect(store.current.error_code).toBe('E3110')
      expect(store.current.error_message).toContain('LLM 认证失败')
      expect(store.current.recoverable).toBe(false)
    })

    it('task.canceled 设置状态并断开 SSE', () => {
      const store = makeStore()
      store.handleSSEEvent('task.canceled', {})
      expect(store.current.status).toBe('canceled')
      expect(store.sseStatus).toBe('disconnected')
    })

    it('未知事件类型_不影响 current', () => {
      const store = makeStore()
      store.handleSSEEvent('unknown.event', { data: 'test' })
      expect(store.current.status).toBe('running')
    })
  })
})
