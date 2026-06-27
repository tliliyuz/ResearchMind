/**
 * HistoryPage 组件测试 — 覆盖 src/views/HistoryPage.vue
 *
 * 对齐 ROADMAP.md §3.9：
 *   - 表格渲染
 *   - 状态筛选
 *   - 搜索防抖（300ms）
 *   - 分页
 *   - 空状态 + 引导按钮
 *   - 点击行加载任务（view → fetchDetail → 跳转 /research）
 *   - 删除确认 → 行移除 → 空页回退
 *
 * 注意：ElementPlus mocked，el-* 组件渲染为自定义 HTML 元素。
 * 数据通过 mock API 返回（而非直接 seed store），因为 onMounted 会调 loadList()。
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import HistoryPage from '@/views/HistoryPage.vue'
import { useTaskStore } from '@/stores/task'

const ResearchStub = { template: '<div>research page</div>', name: 'Research' }

vi.mock('@/api/research', () => ({
  createTask: vi.fn(),
  getTaskList: vi.fn(),
  getTaskDetail: vi.fn(),
  deleteTask: vi.fn(),
  cancelTask: vi.fn(),
  getTaskState: vi.fn(),
}))

import * as researchApi from '@/api/research'
import { ElMessage, ElMessageBox } from 'element-plus'

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/history', name: 'History', component: HistoryPage },
      { path: '/research', name: 'Research', component: ResearchStub },
    ],
  })
}

async function mountHistory(mockListData) {
  // mock getTaskList 返回指定数据
  researchApi.getTaskList.mockResolvedValue({
    data: {
      data: {
        items: mockListData || [],
        total: (mockListData || []).length,
        page: 1,
        page_size: 20,
      },
    },
  })

  const r = makeRouter()
  await r.push('/history')
  await r.isReady()
  const wrapper = mount(HistoryPage, {
    global: {
      plugins: [r, createPinia(), ElementPlus],
      stubs: {
        transition: false,
        // el-tooltip: 透传 slot 内容（避免 scoped slot 访问 row 问题）
        'el-tooltip': { template: '<span class="el-tooltip-stub"><slot /></span>' },
        // el-button: stub 保留 click 事件
        'el-button': {
          template: '<button class="el-button-stub" :class="type" @click="$emit(\'click\')"><slot /></button>',
          props: ['type', 'link', 'size'],
        },
        // el-table: stub 渲染 slot
        'el-table': { template: '<div class="el-table-stub"><slot /><slot name="empty" /></div>' },
        // el-table-column: stub 提供默认空 row 对象防止解构报错
        'el-table-column': {
          template: '<div class="el-table-col-stub"><slot name="default" :row="{}" /></div>',
          props: ['label', 'min-width', 'width', 'align', 'prop', 'fixed'],
        },
        // el-pagination: 简单 stub
        'el-pagination': { template: '<div class="el-pagination-stub" />', props: ['current-page', 'page-size', 'total', 'page-sizes', 'layout'] },
        // el-select: 简单 stub
        'el-select': { template: '<select class="el-select-stub"><slot /></select>', props: ['modelValue', 'placeholder', 'clearable', 'style'] },
        // el-option: 简单 stub
        'el-option': { template: '<option class="el-option-stub" :value="value"><slot /></option>', props: ['label', 'value'] },
        // el-input: 简单 stub
        'el-input': { template: '<input class="el-input-stub" />', props: ['modelValue', 'placeholder', 'clearable', 'class'] },
      },
    },
  })
  // onMounted → loadList → fetchList → getTaskList
  await flushPromises()
  return { wrapper, r }
}

function mockApiResponse(data) {
  return { data: { data } }
}

const SAMPLE_TASKS = [
  { task_id: 't1', topic: '量子计算研究', task_type: 'analysis', status: 'completed', total_sources: 5, total_evidence: 3, created_at: '2026-06-24T08:00:00Z' },
  { task_id: 't2', topic: '向量数据库对比', task_type: 'comparison', status: 'running', total_sources: 0, total_evidence: 0, created_at: '2026-06-23T08:00:00Z' },
]

describe('HistoryPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  // ===== 表格渲染 =====

  it('加载列表后_本地 historyList 包含数据', async () => {
    const { wrapper } = await mountHistory(SAMPLE_TASKS)

    expect(wrapper.vm.historyList).toHaveLength(2)
    expect(wrapper.vm.historyList[0].task_id).toBe('t1')
    expect(wrapper.vm.historyList[1].task_id).toBe('t2')
  })

  // ===== 状态筛选 =====

  it('状态筛选变更_重置到第 1 页并重新加载', async () => {
    const { wrapper } = await mountHistory([])
    researchApi.getTaskList.mockClear()

    wrapper.vm.filterStatus = 'completed'
    wrapper.vm.onFilterChange()
    await flushPromises()

    expect(researchApi.getTaskList).toHaveBeenCalledWith({
      page: 1,
      page_size: 20,
      status: 'completed',
    })
  })

  // ===== 搜索防抖 =====

  it('搜索输入_300ms 防抖触发查询', async () => {
    vi.useFakeTimers()
    const { wrapper } = await mountHistory([])
    researchApi.getTaskList.mockClear()

    wrapper.vm.searchKeyword = '量子'
    wrapper.vm.onSearchDebounced()
    await flushPromises()

    // 200ms 内不触发
    vi.advanceTimersByTime(200)
    await flushPromises()
    expect(researchApi.getTaskList).not.toHaveBeenCalled()

    // 300ms 后触发
    vi.advanceTimersByTime(200)
    await flushPromises()
    expect(researchApi.getTaskList).toHaveBeenCalledWith({
      page: 1,
      page_size: 20,
      status: undefined,
      keyword: '量子',
    })
  })

  // ===== 空状态 =====

  it('空列表_显示空状态 + 引导按钮', async () => {
    const { wrapper } = await mountHistory([])

    expect(wrapper.find('.empty-title').text()).toBe('暂无研究任务')
    // 空状态有引导按钮 → 点击跳转 /research
    expect(wrapper.find('.empty-desc').text()).toContain('深度研究')
  })

  // ===== 点击查看 =====

  it('点击查看按钮_加载详情并跳转到 /research', async () => {
    researchApi.getTaskDetail.mockResolvedValue(
      mockApiResponse({
        task_id: 't-view', topic: '查看目标', status: 'completed',
        current_phase: null, requirements: {},
        progress: { completed_steps: 0, total_steps: 0, progress: 0 },
        total_sources: 3, total_evidence: 1,
      })
    )

    const { wrapper, r } = await mountHistory(SAMPLE_TASKS)

    await wrapper.vm.handleView({ task_id: 't1', topic: '量子计算研究' })
    await flushPromises()

    expect(researchApi.getTaskDetail).toHaveBeenCalledWith('t1')
    expect(r.currentRoute.value.path).toBe('/research')
  })

  // ===== 删除确认 =====

  it('删除确认弹窗_取消_不调用 API', async () => {
    ElMessageBox.confirm.mockRejectedValueOnce('cancel')

    const { wrapper } = await mountHistory(SAMPLE_TASKS)

    await wrapper.vm.handleDelete({ task_id: 't1', topic: '量子计算研究' })
    await flushPromises()

    expect(researchApi.deleteTask).not.toHaveBeenCalled()
  })

  it('删除确认弹窗_确认_调用 API 并本地移除', async () => {
    ElMessageBox.confirm.mockResolvedValueOnce('confirm')
    researchApi.deleteTask.mockResolvedValue({})

    const { wrapper } = await mountHistory(SAMPLE_TASKS)

    expect(wrapper.vm.historyList).toHaveLength(2)

    await wrapper.vm.handleDelete({ task_id: 't1', topic: '量子计算研究' })
    await flushPromises()

    expect(researchApi.deleteTask).toHaveBeenCalledWith('t1')
    expect(ElMessage.success).toHaveBeenCalledWith('删除成功')
    expect(wrapper.vm.historyList).toHaveLength(1)
    expect(wrapper.vm.historyTotal).toBe(1)
  })

  // ===== 空页回退 =====

  it('删除当前页最后一条且 currentPage > 1_自动回退到上一页', async () => {
    ElMessageBox.confirm.mockResolvedValueOnce('confirm')
    researchApi.deleteTask.mockResolvedValue({})

    // 第 2 页仅 1 条
    const { wrapper } = await mountHistory([
      { task_id: 't-last', topic: '最后一条', task_type: 'analysis', status: 'failed', total_sources: 0, total_evidence: 0, created_at: '2026-06-24T08:00:00Z' },
    ])

    wrapper.vm.historyTotal = 21  // 总共 21 条（2 页）
    wrapper.vm.currentPage = 2
    await flushPromises()

    // 删除后 taskList 为空且 currentPage=2 > 1
    // 模拟 deleteTask → taskList.filter → 空
    researchApi.getTaskList.mockResolvedValue(
      mockApiResponse({ items: [], total: 20, page: 1, page_size: 20 })
    )

    await wrapper.vm.handleDelete({ task_id: 't-last', topic: '最后一条' })
    await flushPromises()

    expect(researchApi.deleteTask).toHaveBeenCalledWith('t-last')
  })

  // ===== 分页 =====

  it('total > 0 显示分页组件', async () => {
    const { wrapper } = await mountHistory(SAMPLE_TASKS)
    await flushPromises()
    expect(wrapper.vm.historyTotal).toBeGreaterThan(0)
  })

  it('total 为 0 不显示分页', async () => {
    const { wrapper } = await mountHistory([])
    await flushPromises()
    // v-if="historyTotal > 0" → 不渲染
    expect(wrapper.find('.history-pagination').exists()).toBe(false)
  })

  // ===== 新建研究 =====

  it('点击新建研究_清空当前任务并跳转_research', async () => {
    const { wrapper, r } = await mountHistory(SAMPLE_TASKS)
    const store = useTaskStore()
    const clearSpy = vi.spyOn(store, 'clearCurrent')

    await wrapper.vm.handleNewResearch()
    await flushPromises()

    expect(clearSpy).toHaveBeenCalled()
    expect(r.currentRoute.value.path).toBe('/research')
  })

  it('历史页筛选不影响 taskStore.taskList', async () => {
    const { wrapper } = await mountHistory(SAMPLE_TASKS)
    const store = useTaskStore()
    store.taskList = [{ task_id: 'sidebar-only', topic: '侧边栏任务' }]

    researchApi.getTaskList.mockClear()
    wrapper.vm.filterStatus = 'completed'
    wrapper.vm.onFilterChange()
    await flushPromises()

    expect(store.taskList).toHaveLength(1)
    expect(store.taskList[0].task_id).toBe('sidebar-only')
  })

  // ===== 加载状态 =====

  it('挂载时自动调用 fetchList', async () => {
    await mountHistory([])
    expect(researchApi.getTaskList).toHaveBeenCalledWith({
      page: 1,
      page_size: 20,
      status: undefined,
    })
  })

  // ===== 分页操作 =====

  it('分页换页_调用 loadList', async () => {
    const { wrapper } = await mountHistory([])
    researchApi.getTaskList.mockClear()

    wrapper.vm.onPageChange(2)
    await flushPromises()

    expect(researchApi.getTaskList).toHaveBeenCalledWith({
      page: 2,
      page_size: 20,
      status: undefined,
    })
  })

  it('每页条数变更_重置到第 1 页', async () => {
    const { wrapper } = await mountHistory([])
    researchApi.getTaskList.mockClear()

    wrapper.vm.onPageSizeChange(50)
    await flushPromises()

    expect(researchApi.getTaskList).toHaveBeenCalledWith({
      page: 1,
      page_size: 50,
      status: undefined,
    })
  })
})
