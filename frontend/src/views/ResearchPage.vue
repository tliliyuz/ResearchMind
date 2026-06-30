<template>
  <div class="research-page">
    <!-- ========== 创建态 ========== -->
    <div v-if="pageState === 'create'" class="create-container">
      <!-- 欢迎区 -->
      <div class="welcome-section">
        <div class="welcome-icon">
          <i class="fas fa-microscope"></i>
        </div>
        <h2 class="create-title">开始一项新的研究</h2>
        <p class="create-subtitle">输入研究主题，选择研究类型，开始深度结构化研究</p>
      </div>

      <!-- 表单卡片 -->
      <div class="form-card">
        <!-- 研究主题 -->
        <div class="form-group">
          <label class="form-label">
            研究主题 <span class="required">*</span>
          </label>
          <el-input
            v-model="form.topic"
            type="textarea"
            :rows="4"
            :maxlength="500"
            show-word-limit
            placeholder="输入你想研究的问题、对比或分析主题..."
          />
        </div>

        <!-- 研究类型选择 -->
        <div class="form-group">
          <label class="form-label">
            研究类型 <span class="required">*</span>
          </label>
          <div class="type-cards-row">
            <TypeCard
              v-for="t in TASK_TYPES"
              :key="t.value"
              :type="t.value"
              :selected="form.task_type === t.value"
              @select="form.task_type = $event"
            />
          </div>
          <!-- 未选中提示 -->
          <p v-if="!form.task_type && showValidation" class="field-hint error">
            请选择一种研究类型
          </p>
        </div>

        <!-- 高级选项（可折叠） -->
        <div class="advanced-section">
          <button
            type="button"
            class="advanced-toggle"
            @click="showAdvanced = !showAdvanced"
          >
            <span>高级选项</span>
            <i :class="showAdvanced ? 'fas fa-chevron-up' : 'fas fa-chevron-down'"></i>
          </button>

          <div v-show="showAdvanced" class="advanced-panel">
            <!-- 信息源数量 -->
            <div class="option-row">
              <label class="option-label">
                信息源数量：{{ form.max_sources }}
              </label>
              <el-slider
                v-model="form.max_sources"
                :min="1"
                :max="50"
                :step="1"
                show-stops
                :marks="{ 1: '1', 10: '10', 25: '25', 50: '50' }"
              />
            </div>

            <!-- 报告语言 -->
            <div class="option-row">
              <label class="option-label">报告语言</label>
              <el-select v-model="form.language" class="language-select">
                <el-option label="中文" value="zh" />
                <el-option label="English" value="en" />
              </el-select>
            </div>

            <!-- 研究深度（MVP 固定 quick） -->
            <div class="option-row">
              <label class="option-label">研究深度</label>
              <el-input value="快速（quick）" disabled class="depth-input" />
              <span class="hint-text">MVP 仅支持快速模式</span>
            </div>
          </div>
        </div>

        <!-- 提交按钮 -->
        <button
          class="submit-btn"
          :disabled="!canSubmit || submitting"
          @click="handleSubmit"
        >
          <i v-if="submitting" class="fas fa-spinner fa-spin"></i>
          <i v-else class="fas fa-flask"></i>
          {{ submitting ? '正在创建...' : '开始研究' }}
        </button>
      </div>

      <!-- 快捷示例 -->
      <div class="examples-section">
        <h3 class="examples-title"><i class="fas fa-lightbulb"></i> 试试这些研究方向</h3>
        <div class="examples-row">
          <ExampleCard
            v-for="ex in EXAMPLES"
            :key="ex.label"
            :example="ex"
            @select="fillExample"
          />
        </div>
      </div>
    </div>

    <!-- ========== 运行态 ========== -->
    <div v-else-if="pageState === 'running'" class="running-state">
      <RunningHeader
        :title="taskStore.current?.topic"
        :status="taskStore.current?.status"
        :current-phase="taskStore.current?.current_phase"
        :elapsed-ms="elapsedMs"
        :cancel-loading="cancelLoading"
        @cancel="handleCancel"
      />
      <PipelineProgress
        :phases="taskStore.phaseStates"
        :progress="taskStore.progress"
        :phase-durations="taskStore.phaseDurations"
      />
      <StepLog :logs="taskStore.stepLogs" :sse-status="taskStore.sseStatus" />
      <CheckpointBanner v-if="taskStore.lastCheckpoint" :checkpoint="taskStore.lastCheckpoint" />
    </div>

    <!-- ========== 完成态 ========== -->
    <div v-else class="completed-state">
      <ReportViewer
        v-if="isSuccessStatus"
        :task="taskStore.current"
        @back="handleBackToCreate"
      />
      <FailedView
        v-else-if="taskStore.current?.status === 'failed'"
        :error-code="taskStore.current?.error_code"
        :error-message="taskStore.current?.error_message"
        :failed-phase="taskStore.current?.current_phase"
        :recoverable="taskStore.current?.recoverable"
        @back="handleBackToCreate"
        @retry="handleRetry"
      />
      <CanceledView
        v-else-if="taskStore.current?.status === 'canceled'"
        :topic="taskStore.current?.topic"
        :phases="taskStore.phaseStates"
        :phase-durations="taskStore.phaseDurations"
        @back="handleBackToCreate"
      />
      <div v-else class="state-placeholder">
        <div class="placeholder-card">
          <h2>{{ statusTitle }}</h2>
          <p class="task-topic">{{ taskStore.current?.topic }}</p>
          <button class="back-btn" @click="handleBackToCreate">
            <i class="fas fa-arrow-left"></i> 返回新建研究
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useTaskStore } from '@/stores/task'
import { useReportStore } from '@/stores/report'
import TypeCard from '@/components/task/TypeCard.vue'
import ExampleCard from '@/components/task/ExampleCard.vue'
import RunningHeader from '@/components/task/RunningHeader.vue'
import PipelineProgress from '@/components/task/PipelineProgress.vue'
import StepLog from '@/components/task/StepLog.vue'
import CheckpointBanner from '@/components/task/CheckpointBanner.vue'
import ReportViewer from '@/components/report/ReportViewer.vue'
import FailedView from '@/components/report/FailedView.vue'
import CanceledView from '@/components/report/CanceledView.vue'

const taskStore = useTaskStore()
const reportStore = useReportStore()

// ===== 表单数据 =====
const form = reactive({
  topic: '',
  task_type: null,
  max_sources: 10,
  language: 'zh',
})

const showAdvanced = ref(false)
const submitting = ref(false)
const showValidation = ref(false)
const cancelLoading = ref(false)

// ===== 已用时时钟 =====
const elapsedMs = ref(0)
let elapsedTimer = null

function startElapsedTimer() {
  stopElapsedTimer()
  elapsedTimer = setInterval(() => {
    const base = taskStore.current?.started_at || taskStore.current?.created_at
    if (base) {
      elapsedMs.value = Date.now() - new Date(base).getTime()
    } else {
      elapsedMs.value = 0
    }
  }, 1000)
}

function stopElapsedTimer() {
  if (elapsedTimer) {
    clearInterval(elapsedTimer)
    elapsedTimer = null
  }
}

// ===== 研究类型元数据 =====
const TASK_TYPES = [
  { value: 'comparison' },
  { value: 'explainer' },
  { value: 'analysis' },
]

// ===== 快捷示例 =====
const EXAMPLES = [
  {
    topic: '2025年主流向量数据库对比：Milvus vs Qdrant vs Weaviate',
    task_type: 'comparison',
    label: '技术选型',
  },
  {
    topic: 'Transformer 注意力机制的最新改进方向',
    task_type: 'explainer',
    label: '学习前沿',
  },
  {
    topic: '量子计算对现有密码学体系的影响及应对方案',
    task_type: 'analysis',
    label: '趋势分析',
  },
]

// ===== 页面状态 =====
const pageState = computed(() => {
  if (!taskStore.current) return 'create'
  const status = taskStore.current.status
  if (status === 'pending' || status === 'running') return 'running'
  return 'completed'
})

const isSuccessStatus = computed(() => {
  const status = taskStore.current?.status
  return status === 'completed' || status === 'partially_completed'
})

// ===== 监听状态切换 =====
watch(pageState, (state, prevState) => {
  if (state === 'running') {
    startElapsedTimer()
  } else {
    stopElapsedTimer()
  }
  if (state === 'completed' && isSuccessStatus.value && taskStore.current?.task_id) {
    reportStore.fetch(taskStore.current.task_id)
  }
  if (state === 'create') {
    reportStore.clear()
  }
}, { immediate: true })

// ===== 表单校验 =====
const canSubmit = computed(() => {
  return (
    form.topic.trim().length > 0 &&
    form.topic.trim().length <= 500 &&
    form.task_type !== null
  )
})

// ===== 提交 =====
async function handleSubmit() {
  showValidation.value = true

  if (!canSubmit.value) {
    if (!form.topic.trim()) {
      ElMessage.warning('请输入研究主题')
    } else if (!form.task_type) {
      ElMessage.warning('请选择研究类型')
    }
    return
  }

  submitting.value = true
  try {
    const requirements = {
      task_type: form.task_type,
      depth: 'quick',
      max_sources: form.max_sources,
      language: form.language,
    }
    const taskData = await taskStore.createTask(form.topic.trim(), requirements)
    ElMessage.success('研究任务已创建，正在执行...')

    // 自动连接 SSE
    await taskStore.connectSSE(taskData.task_id)
  } catch (err) {
    handleCreateError(err)
  } finally {
    submitting.value = false
  }
}

function handleCreateError(err) {
  const status = err.response?.status
  const data = err.response?.data

  switch (status) {
    case 400:
      ElMessage.error(data?.message || '请求参数有误')
      break
    case 422: {
      const detail = data?.detail
      if (detail && typeof detail === 'object') {
        const msgs = []
        if (detail.topic) msgs.push(`主题：${detail.topic}`)
        if (detail.requirements) msgs.push(`需求配置：${JSON.stringify(detail.requirements)}`)
        ElMessage.error(msgs.join('；') || '参数校验失败')
      } else {
        ElMessage.error(data?.message || '参数校验失败')
      }
      break
    }
    case 429:
      ElMessage.warning('操作过于频繁，请稍后重试')
      break
    case 403:
      ElMessage.error('无权限执行此操作')
      break
    default:
      ElMessage.error(data?.message || '创建失败，请稍后重试')
  }
}

// ===== 快捷填入 =====
function fillExample(example) {
  form.topic = example.topic
  form.task_type = example.task_type
  showValidation.value = false
}

// ===== 取消 =====
async function handleCancel() {
  // 乐观运行态但 task_id 尚未返回时，取消操作无意义
  if (!taskStore.current?.task_id) return

  try {
    await ElMessageBox.confirm(
      '确定要取消当前研究吗？已完成的部分将保留。',
      '确认取消',
      {
        confirmButtonText: '取消研究',
        cancelButtonText: '返回',
        type: 'warning',
      }
    )
  } catch {
    return
  }

  cancelLoading.value = true
  try {
    await taskStore.cancelTask(taskStore.current.task_id)
    ElMessage.success('研究已取消')
  } catch (err) {
    const status = err.response?.status
    if (status === 409) {
      const detail = err.response?.data?.detail
      ElMessage.error(detail?.error_description || '当前状态不支持取消操作')
    } else {
      ElMessage.error(err.response?.data?.message || '取消失败')
    }
  } finally {
    cancelLoading.value = false
  }
}

// ===== 返回创建 =====
function handleBackToCreate() {
  taskStore.clearCurrent()
  reportStore.clear()
  // 重置表单
  form.topic = ''
  form.task_type = null
  form.max_sources = 10
  form.language = 'zh'
  showValidation.value = false
}

// ===== 断点续跑 =====
async function handleRetry() {
  const taskId = taskStore.current?.task_id
  if (!taskId) return
  try {
    await taskStore.retryTask(taskId)
    ElMessage.success('已从断点恢复执行')
  } catch (err) {
    const status = err.response?.status
    if (status === 409) {
      const detail = err.response?.data?.detail
      ElMessage.error(detail?.error_description || '当前状态不支持断点续跑')
    } else {
      ElMessage.error(err.response?.data?.message || '断点续跑失败，请稍后重试')
    }
  }
}

const statusTitle = computed(() => {
  const map = {
    completed: '研究完成',
    partially_completed: '部分完成',
    failed: '研究失败',
    canceled: '研究已取消',
  }
  return map[taskStore.current?.status] || '任务结束'
})

// ===== 生命周期 =====
onMounted(() => {
  // 返回运行态/待处理任务时自动恢复 SSE 连接，避免日志丢失
	  // pending 也需重连：retry 后 Worker 拾取前的窗口期
  const s = taskStore.current?.status
  if ((s === 'running' || s === 'pending') && taskStore.sseStatus === 'disconnected') {
    taskStore.connectSSE(taskStore.current.task_id)
  }
})

onBeforeUnmount(() => {
  // 离开页面时断开 SSE（不 clearCurrent，保留状态供返回查看）
  taskStore.disconnectSSE()
  stopElapsedTimer()
})
</script>

<style scoped>
.research-page {
  height: 100%;
}

/* ===== 创建态容器 ===== */
.create-container {
  max-width: var(--rm-content-max-width);
  margin: 0 auto;
  padding-bottom: var(--rm-space-12);
}

/* ===== 欢迎区 ===== */
.welcome-section {
  text-align: center;
  margin-bottom: var(--rm-space-8);
  padding-top: var(--rm-space-4);
}

.welcome-icon {
  width: var(--rm-welcome-icon-size);
  height: var(--rm-welcome-icon-size);
  background: var(--rm-primary-light);
  border-radius: var(--rm-radius-xl);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--rm-primary);
  font-size: var(--rm-text-2xl);
  margin-bottom: var(--rm-space-4);
}

.create-title {
  font-size: var(--rm-text-2xl);
  font-weight: var(--rm-weight-bold);
  color: var(--rm-text-primary);
  margin: 0 0 var(--rm-space-2) 0;
  letter-spacing: -0.025em;
}

.create-subtitle {
  font-size: var(--rm-text-body);
  color: var(--rm-text-secondary);
  margin: 0;
}

/* ===== 表单卡片 ===== */
.form-card {
  background: var(--rm-bg-card);
  border: 1px solid var(--rm-border);
  border-radius: var(--rm-radius-xl);
  padding: var(--rm-space-6);
  box-shadow: var(--rm-shadow-sm);
}

.form-group {
  margin-bottom: var(--rm-space-5);
}

.form-label {
  display: block;
  font-size: var(--rm-text-sm);
  font-weight: var(--rm-weight-semibold);
  color: var(--rm-text-primary);
  margin-bottom: var(--rm-space-2);
}

.required {
  color: var(--rm-danger);
}

.field-hint.error {
  color: var(--rm-danger);
  font-size: var(--rm-text-xs);
  margin: var(--rm-space-1) 0 0 0;
}

/* ===== 研究类型卡片行 ===== */
.type-cards-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--rm-space-3);
}

/* ===== 高级选项 ===== */
.advanced-section {
  margin-bottom: var(--rm-space-5);
}

.advanced-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  color: var(--rm-text-secondary);
  font-size: var(--rm-text-xs);
  font-weight: var(--rm-weight-semibold);
  padding: var(--rm-space-1) 0;
  cursor: pointer;
  border: none;
  background: transparent;
  font-family: inherit;
}

.advanced-toggle:hover {
  color: var(--rm-text-primary);
}

.advanced-panel {
  background: var(--rm-bg-page);
  border: 1px solid var(--rm-border-light);
  border-radius: var(--rm-radius-lg);
  padding: var(--rm-space-4);
  margin-top: var(--rm-space-2);
}

.option-row {
  margin-bottom: var(--rm-space-4);
}

.option-row:last-child {
  margin-bottom: 0;
}

.option-label {
  display: block;
  font-size: var(--rm-text-sm);
  font-weight: var(--rm-weight-medium);
  color: var(--rm-text-primary);
  margin-bottom: var(--rm-space-2);
}

.hint-text {
  font-size: var(--rm-text-xs);
  color: var(--rm-text-tertiary);
  margin-left: var(--rm-space-2);
}

/* ===== 提交按钮 ===== */
.submit-btn {
  width: 100%;
  height: 48px;
  background: var(--rm-primary);
  color: white;
  border: none;
  border-radius: var(--rm-radius-lg);
  font-size: var(--rm-text-sm);
  font-weight: var(--rm-weight-semibold);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--rm-space-2);
  transition: all var(--rm-transition-normal);
  box-shadow: var(--rm-shadow-md);
  font-family: inherit;
}

.submit-btn:hover:not(:disabled) {
  background: var(--rm-primary-hover);
}

.submit-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ===== 快捷示例 ===== */
.examples-section {
  margin-top: var(--rm-space-6);
}

.examples-title {
  font-size: var(--rm-text-sm);
  font-weight: var(--rm-weight-semibold);
  color: var(--rm-text-secondary);
  margin: 0 0 var(--rm-space-3) 0;
  text-align: center;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--rm-space-1_5);
  width: 100%;
}

.language-select,
.depth-input {
  width: 200px;
}

.examples-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--rm-space-3);
}

/* ===== 运行态 ===== */
.running-state {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--rm-bg-page);
  overflow-y: auto;
}

/* ===== 完成态 ===== */
.completed-state {
  height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.completed-state > .report-viewer,
.completed-state > .state-placeholder {
  align-self: stretch;
  flex: 1;
  width: 100%;
}

/* ===== 兜底占位 ===== */
.state-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.placeholder-card {
  text-align: center;
  padding: var(--rm-space-10);
  background: var(--rm-bg-card);
  border: 1px solid var(--rm-border);
  border-radius: var(--rm-radius-xl);
  max-width: 480px;
  width: 100%;
  box-shadow: var(--rm-shadow-sm);
}

.placeholder-card h2 {
  font-size: var(--rm-text-xl);
  font-weight: var(--rm-weight-bold);
  color: var(--rm-text-primary);
  margin: 0 0 var(--rm-space-2) 0;
}

.task-topic {
  font-size: var(--rm-text-body);
  color: var(--rm-text-secondary);
  margin: 0 0 var(--rm-space-4) 0;
}

.back-btn {
  height: 38px;
  padding: 0 20px;
  background: var(--rm-primary-light);
  color: var(--rm-primary);
  border: none;
  border-radius: var(--rm-radius-sm);
  font-size: var(--rm-text-sm);
  font-weight: var(--rm-weight-medium);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: var(--rm-space-1_5);
  transition: all var(--rm-transition-fast);
  font-family: inherit;
}

.back-btn:hover {
  background: var(--rm-primary-hover-light);
}

/* ===== 响应式：小屏三列变单列 ===== */
@media (max-width: 768px) {
  .type-cards-row,
  .examples-row {
    grid-template-columns: 1fr;
  }
}
</style>
