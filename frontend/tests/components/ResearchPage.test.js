/**
 * ResearchPage 创建态组件测试 — 覆盖 src/views/ResearchPage.vue
 *
 * 对齐 ROADMAP.md §3.9：
 *   - 表单渲染（topic textarea + task_type 卡片 + 提交按钮）
 *   - topic 字数校验（>500 字符拒绝）
 *   - task_type 卡片选中高亮
 *   - 高级选项折叠/展开
 *   - 提交 loading
 *   - 快捷示例卡片点击填入
 *   - 提交成功切换到运行态
 *
 * 注意：ElementPlus 在 test setup 中被 mock（install no-op），
 * el-* 组件渲染为自定义 HTML 元素（非注册 Vue 组件），
 * findComponent({name:'ElInput'}) 无法找到，需使用 DOM 选择器。
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import ResearchPage from '@/views/ResearchPage.vue'
import { useTaskStore } from '@/stores/task'

vi.mock('@/api/research', () => ({
  createTask: vi.fn(),
  getTaskList: vi.fn(),
  getTaskDetail: vi.fn(),
  deleteTask: vi.fn(),
  cancelTask: vi.fn(),
  getTaskState: vi.fn(),
  getReport: vi.fn(),
}))

vi.mock('@/utils/sse', () => ({
  connectSSE: vi.fn(() => ({ close: vi.fn() })),
}))

import * as researchApi from '@/api/research'
import { connectSSE } from '@/utils/sse'
import { ElMessage } from 'element-plus'

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/research', name: 'Research', component: ResearchPage },
    ],
  })
}

async function mountResearch({ pinia = createPinia() } = {}) {
  const r = makeRouter()
  await r.push('/research')
  await r.isReady()
  const wrapper = mount(ResearchPage, {
    global: {
      plugins: [r, pinia, ElementPlus],
      stubs: { transition: false },
    },
  })
  return { wrapper, r }
}

function mockApiResponse(data) {
  return { data: { data } }
}

describe('ResearchPage — 创建态', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  // ===== 表单渲染 =====

  it('渲染研究主题 el-input（textarea 模式）', async () => {
    const { wrapper } = await mountResearch()
    expect(wrapper.find('.create-title').text()).toBe('开始一项新的研究')
    expect(wrapper.find('.form-card').exists()).toBe(true)
    // el-input 以自定义元素 <el-input> 渲染（ElementPlus mocked）
    expect(wrapper.find('el-input').exists()).toBe(true)
  })

  it('渲染三张 TypeCard 研究类型卡片', async () => {
    const { wrapper } = await mountResearch()
    const cards = wrapper.findAllComponents({ name: 'TypeCard' })
    expect(cards).toHaveLength(3)
  })

  it('渲染提交按钮_初始 disabled（未填 topic + task_type）', async () => {
    const { wrapper } = await mountResearch()
    const btn = wrapper.find('.submit-btn')
    expect(btn.exists()).toBe(true)
    expect(btn.attributes('disabled')).toBeDefined()
  })

  it('渲染三个快捷示例卡片', async () => {
    const { wrapper } = await mountResearch()
    const examples = wrapper.findAllComponents({ name: 'ExampleCard' })
    expect(examples).toHaveLength(3)
  })

  // ===== 高级选项折叠/展开 =====

  it('高级选项默认折叠（showAdvanced=false）', async () => {
    const { wrapper } = await mountResearch()
    expect(wrapper.vm.showAdvanced).toBe(false)
  })

  it('点击高级选项_展开面板（showAdvanced=true）', async () => {
    const { wrapper } = await mountResearch()
    await wrapper.find('.advanced-toggle').trigger('click')
    expect(wrapper.vm.showAdvanced).toBe(true)
  })

  it('高级选项展开后可再折叠（showAdvanced=false）', async () => {
    const { wrapper } = await mountResearch()
    const toggle = wrapper.find('.advanced-toggle')
    await toggle.trigger('click')
    expect(wrapper.vm.showAdvanced).toBe(true)
    await toggle.trigger('click')
    expect(wrapper.vm.showAdvanced).toBe(false)
  })

  // ===== 快捷示例点击填入 =====

  it('点击快捷示例卡片_自动填入 topic + task_type', async () => {
    const { wrapper } = await mountResearch()
    const examples = wrapper.findAllComponents({ name: 'ExampleCard' })

    await examples[0].vm.$emit('select', {
      topic: '2025年主流向量数据库对比：Milvus vs Qdrant vs Weaviate',
      task_type: 'comparison',
      label: '技术选型',
    })
    await flushPromises()

    expect(wrapper.vm.form.topic).toBe('2025年主流向量数据库对比：Milvus vs Qdrant vs Weaviate')
    expect(wrapper.vm.form.task_type).toBe('comparison')
  })

  // ===== 表单校验 =====

  it('topic 为空 + 已选 task_type_按钮 disabled', async () => {
    const { wrapper } = await mountResearch()
    wrapper.vm.form.task_type = 'comparison'
    wrapper.vm.form.topic = ''
    await flushPromises()
    expect(wrapper.find('.submit-btn').attributes('disabled')).toBeDefined()
  })

  it('topic 已填 + 未选 task_type_按钮 disabled', async () => {
    const { wrapper } = await mountResearch()
    wrapper.vm.form.topic = '有效的研究主题'
    wrapper.vm.form.task_type = null
    await flushPromises()
    expect(wrapper.find('.submit-btn').attributes('disabled')).toBeDefined()
  })

  it('topic 已填 + task_type 已选_按钮 enabled', async () => {
    const { wrapper } = await mountResearch()
    wrapper.vm.form.topic = '有效的研究主题'
    wrapper.vm.form.task_type = 'comparison'
    await flushPromises()
    expect(wrapper.find('.submit-btn').attributes('disabled')).toBeUndefined()
  })

  // ===== 提交 loading =====

  it('点击提交后立即进入运行态_不再阻塞在创建态', async () => {
    researchApi.createTask.mockImplementation(
      () => new Promise(() => {})
    )

    const { wrapper } = await mountResearch()
    wrapper.vm.form.topic = '有效的研究主题'
    wrapper.vm.form.task_type = 'explainer'
    await flushPromises()

    await wrapper.find('.submit-btn').trigger('click')
    await flushPromises()

    expect(wrapper.find('.running-state').exists()).toBe(true)
    expect(wrapper.find('.create-container').exists()).toBe(false)
    expect(wrapper.vm.submitting).toBe(true)
    expect(wrapper.findComponent({ name: 'RunningHeader' }).exists()).toBe(true)
  })

  // ===== 提交成功 → 切换到运行态 =====

  it('提交成功_切换到运行态_自动连接 SSE', async () => {
    researchApi.createTask.mockResolvedValue(
      mockApiResponse({ task_id: 'task-new', status: 'pending', created_at: '2026-06-24T10:00:00Z' })
    )
    connectSSE.mockReturnValue({ close: vi.fn() })

    const { wrapper } = await mountResearch()
    wrapper.vm.form.topic = '向量数据库性能对比'
    wrapper.vm.form.task_type = 'comparison'
    await flushPromises()

    await wrapper.find('.submit-btn').trigger('click')
    await flushPromises()

    expect(researchApi.createTask).toHaveBeenCalledWith('向量数据库性能对比', {
      task_type: 'comparison',
      depth: 'quick',
      max_sources: 10,
      language: 'zh',
    })

    expect(connectSSE).toHaveBeenCalledWith('/api/research/task-new/stream', expect.any(Object))

    const store = useTaskStore()
    expect(store.current).not.toBeNull()
    expect(store.current.status).toBe('pending')
  })

  // ===== task_type 卡片选中高亮 =====

  it('TypeCard 选中状态通过 selected prop 传递', async () => {
    const { wrapper } = await mountResearch()
    const typeCards = wrapper.findAllComponents({ name: 'TypeCard' })

    await typeCards[0].vm.$emit('select', 'comparison')
    await flushPromises()
    expect(typeCards[0].props('selected')).toBe(true)

    await typeCards[1].vm.$emit('select', 'explainer')
    await flushPromises()
    expect(typeCards[0].props('selected')).toBe(false)
    expect(typeCards[1].props('selected')).toBe(true)
  })

  // ===== 提交异常处理 =====

  it('提交失败 _回滚到创建态并显示错误信息', async () => {
    researchApi.createTask.mockRejectedValue({
      response: { status: 422, data: { detail: { topic: '主题不可为空' } } },
    })
    ElMessage.error.mockImplementation(() => {})

    const { wrapper } = await mountResearch()
    wrapper.vm.form.topic = '测试'
    wrapper.vm.form.task_type = 'comparison'
    await flushPromises()

    await wrapper.find('.submit-btn').trigger('click')
    await flushPromises()

    expect(ElMessage.error).toHaveBeenCalled()
    expect(wrapper.find('.create-container').exists()).toBe(true)
    expect(wrapper.find('.running-state').exists()).toBe(false)
  })
})

describe('ResearchPage — 状态切换', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('运行态且 SSE 未连接时 mount 自动恢复 SSE', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useTaskStore()
    store.current = {
      task_id: 'task-running',
      topic: '运行中主题',
      status: 'running',
      current_phase: 'search',
      created_at: '2026-06-24T10:00:00Z',
      started_at: '2026-06-24T10:00:01Z',
    }
    store.sseStatus = 'disconnected'

    const { wrapper } = await mountResearch({ pinia })
    await flushPromises()

    expect(connectSSE).toHaveBeenCalledWith('/api/research/task-running/stream', expect.any(Object))
  })

  it('运行态_渲染 RunningHeader/PipelineProgress/StepLog', async () => {
    const { wrapper } = await mountResearch()
    const store = useTaskStore()
    store.current = {
      task_id: 'task-running',
      topic: '运行中主题',
      status: 'running',
      current_phase: 'search',
      progress: { completed_steps: 3, total_steps: 10, progress: 0.3 },
      created_at: '2026-06-24T10:00:00Z',
      started_at: '2026-06-24T10:00:01Z',
    }
    store.phaseStates = {
      planning: 'done',
      search: 'running',
      fetch: 'pending',
      rerank: 'pending',
      synthesis: 'pending',
      evidence_graph: 'pending',
      render: 'pending',
    }
    store.stepLogs = [{ id: 'l1', type: 'system', icon: 'fa-play', level: 'info', message: '任务已创建' }]
    await flushPromises()

    expect(wrapper.findComponent({ name: 'RunningHeader' }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'PipelineProgress' }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'StepLog' }).exists()).toBe(true)
    expect(wrapper.find('.running-state').exists()).toBe(true)
  })

  it('完成态_渲染 ReportViewer', async () => {
    researchApi.getReport.mockResolvedValue({
      data: {
        data: {
          report: { title: '报告标题', sections: [] },
          evidence_graph: { items: [] },
          trace: {},
        },
      },
    })

    const { wrapper } = await mountResearch()
    const store = useTaskStore()
    store.current = {
      task_id: 'task-completed',
      topic: '完成主题',
      status: 'completed',
      total_sources: 5,
      total_evidence: 3,
      completed_at: '2026-06-24T10:05:00Z',
    }
    await flushPromises()

    expect(wrapper.findComponent({ name: 'ReportViewer' }).exists()).toBe(true)
    expect(researchApi.getReport).toHaveBeenCalledWith('task-completed')
  })

  it('失败态_渲染 FailedView', async () => {
    const { wrapper } = await mountResearch()
    const store = useTaskStore()
    store.current = {
      task_id: 'task-failed',
      topic: '失败主题',
      status: 'failed',
      error_code: 'E3104',
      error_message: 'Synthesis 失败',
      current_phase: 'synthesis',
      recoverable: true,
    }
    await flushPromises()

    expect(wrapper.findComponent({ name: 'FailedView' }).exists()).toBe(true)
  })

  it('取消态_渲染 CanceledView', async () => {
    const { wrapper } = await mountResearch()
    const store = useTaskStore()
    store.current = {
      task_id: 'task-canceled',
      topic: '取消主题',
      status: 'canceled',
    }
    store.phaseStates = {
      planning: 'done',
      search: 'done',
      fetch: 'pending',
      rerank: 'pending',
      synthesis: 'pending',
      evidence_graph: 'pending',
      render: 'pending',
    }
    await flushPromises()

    expect(wrapper.findComponent({ name: 'CanceledView' }).exists()).toBe(true)
  })
})
