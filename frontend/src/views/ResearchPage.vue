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
              <el-select v-model="form.language" style="width: 200px">
                <el-option label="中文" value="zh" />
                <el-option label="English" value="en" />
              </el-select>
            </div>

            <!-- 研究深度（MVP 固定 quick） -->
            <div class="option-row">
              <label class="option-label">研究深度</label>
              <el-input value="快速（quick）" disabled style="width: 200px" />
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
        <h3 class="examples-title">💡 试试这些研究方向</h3>
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

    <!-- ========== 运行态（Phase 3 占位） ========== -->
    <div v-else-if="pageState === 'running'" class="state-placeholder">
      <div class="placeholder-card">
        <div class="running-spinner">
          <i class="fas fa-spinner fa-spin"></i>
        </div>
        <h2>研究正在执行中</h2>
        <p class="task-topic">{{ taskStore.current?.topic }}</p>

        <div class="running-info" v-if="taskStore.current?.current_phase">
          <span class="info-label">当前阶段：</span>
          <span class="info-value">{{ phaseLabel(taskStore.current.current_phase) }}</span>
        </div>

        <div class="running-info">
          <span class="info-label">进度：</span>
          <span class="info-value">
            {{ taskStore.progress.completed_steps }} / {{ taskStore.progress.total_steps }} 步骤
          </span>
        </div>

        <div class="running-info">
          <span class="info-label">SSE 连接：</span>
          <span class="info-value" :class="sseStatusClass">
            {{ sseStatusLabel }}
          </span>
        </div>

        <button class="danger-btn" :disabled="cancelLoading" @click="handleCancel">
          <i v-if="!cancelLoading" class="fas fa-ban"></i> {{ cancelLoading ? '取消中...' : '取消研究' }}
        </button>
      </div>
    </div>

    <!-- ========== 完成态（Phase 3 占位） ========== -->
    <div v-else class="state-placeholder">
      <div class="placeholder-card">
        <!-- 状态图标 -->
        <div v-if="taskStore.current?.status === 'completed'" class="result-icon success">
          <i class="fas fa-circle-check"></i>
        </div>
        <div v-else-if="taskStore.current?.status === 'failed'" class="result-icon danger">
          <i class="fas fa-times-circle"></i>
        </div>
        <div v-else-if="taskStore.current?.status === 'canceled'" class="result-icon muted">
          <i class="fas fa-ban"></i>
        </div>
        <div v-else class="result-icon warning">
          <i class="fas fa-triangle-exclamation"></i>
        </div>

        <h2>{{ statusTitle }}</h2>
        <p class="task-topic">{{ taskStore.current?.topic }}</p>

        <!-- 成功统计 -->
        <div
          v-if="taskStore.current?.status === 'completed' || taskStore.current?.status === 'partially_completed'"
          class="stats-row"
        >
          <div class="stat-item">
            <span class="stat-value">{{ taskStore.current?.total_sources || 0 }}</span>
            <span class="stat-label">来源</span>
          </div>
          <div class="stat-item">
            <span class="stat-value">{{ taskStore.current?.total_evidence || 0 }}</span>
            <span class="stat-label">证据</span>
          </div>
        </div>

        <!-- 失败信息 -->
        <div v-if="taskStore.current?.status === 'failed'" class="error-info">
          <p class="error-message">{{ taskStore.current?.error_message || '未知错误' }}</p>
          <span v-if="taskStore.current?.error_code" class="error-code">
            {{ taskStore.current.error_code }}
          </span>
          <p v-if="taskStore.current?.recoverable" class="recoverable-hint">
            该错误可恢复，已完成阶段不丢失
          </p>
        </div>

        <!-- 操作按钮 -->
        <div class="result-actions">
          <button class="back-btn" @click="handleBackToCreate">
            <i class="fas fa-arrow-left"></i> 返回新建研究
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onBeforeUnmount, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useTaskStore } from '@/stores/task'
import TypeCard from '@/components/task/TypeCard.vue'
import ExampleCard from '@/components/task/ExampleCard.vue'

const taskStore = useTaskStore()

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
  // 重置表单
  form.topic = ''
  form.task_type = null
  form.max_sources = 10
  form.language = 'zh'
  showValidation.value = false
}

// ===== 辅助 =====
function phaseLabel(phase) {
  const map = {
    planning: 'Planning — 拆解研究主题',
    search: 'Search — 搜索信息源',
    fetch: 'Fetch — 抓取网页内容',
    rerank: 'Rerank — 证据粗筛精排',
    synthesis: 'Synthesis — 跨源综合',
    graph: 'Evidence Graph — 构建证据图谱',
    render: 'Render — 报告渲染',
  }
  return map[phase] || phase
}

const sseStatusLabel = computed(() => {
  const map = {
    disconnected: '未连接',
    connecting: '连接中...',
    connected: '已连接 ✓',
    reconnecting: '重连中...',
    error: '连接失败',
  }
  return map[taskStore.sseStatus] || taskStore.sseStatus
})

const sseStatusClass = computed(() => {
  return {
    'status-connected': taskStore.sseStatus === 'connected',
    'status-connecting': taskStore.sseStatus === 'connecting' || taskStore.sseStatus === 'reconnecting',
    'status-error': taskStore.sseStatus === 'error',
  }
})

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
onBeforeUnmount(() => {
  // 离开页面时断开 SSE（不 clearCurrent，保留状态供返回查看）
  taskStore.disconnectSSE()
})
</script>

<style scoped>
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
}

.examples-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--rm-space-3);
}

/* ===== 运行态 / 完成态 占位 ===== */
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

/* ===== 运行态特有 ===== */
.running-spinner {
  width: 48px;
  height: 48px;
  margin: 0 auto var(--rm-space-4);
  background: var(--rm-primary-light);
  border: 1px solid var(--rm-primary-border);
  border-radius: var(--rm-radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--rm-primary);
  font-size: var(--rm-text-xl);
}

.running-info {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--rm-space-1_5);
  margin-bottom: var(--rm-space-2);
  font-size: var(--rm-text-sm);
}

.info-label {
  color: var(--rm-text-tertiary);
}

.info-value {
  color: var(--rm-text-primary);
  font-weight: var(--rm-weight-medium);
}

.status-connected {
  color: var(--rm-success) !important;
}

.status-connecting {
  color: var(--rm-warning) !important;
}

.status-error {
  color: var(--rm-danger) !important;
}

.danger-btn {
  margin-top: var(--rm-space-5);
  height: 32px;
  padding: 0 12px;
  background: var(--rm-danger-light);
  color: var(--rm-danger);
  border: 1px solid var(--rm-danger-border);
  border-radius: var(--rm-radius-md);
  font-size: var(--rm-text-xs);
  font-weight: var(--rm-weight-medium);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: var(--rm-space-1);
  transition: all var(--rm-transition-fast);
  flex-shrink: 0;
  font-family: inherit;
}

.danger-btn:hover {
  background: var(--rm-danger-border);
}

.danger-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* ===== 完成态特有 ===== */
.result-icon {
  width: 64px;
  height: 64px;
  border-radius: var(--rm-radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto var(--rm-space-4);
  font-size: 24px;
}

.result-icon.success {
  background: var(--rm-success-light);
  color: var(--rm-success);
}

.result-icon.danger {
  background: var(--rm-danger-light);
  color: var(--rm-danger);
}

.result-icon.warning {
  background: var(--rm-warning-light);
  color: var(--rm-warning);
}

.result-icon.muted {
  background: var(--rm-bg-elevated);
  color: var(--rm-text-secondary);
}

.stats-row {
  display: flex;
  justify-content: center;
  gap: var(--rm-space-8);
  margin-bottom: var(--rm-space-4);
}

.stat-item {
  text-align: center;
}

.stat-item .stat-value {
  display: block;
  font-size: var(--rm-text-2xl);
  font-weight: var(--rm-weight-bold);
  color: var(--rm-primary);
}

.stat-item .stat-label {
  font-size: var(--rm-text-xs);
  color: var(--rm-text-tertiary);
}

.error-info {
  margin-bottom: var(--rm-space-4);
}

.error-message {
  font-size: var(--rm-text-body);
  color: var(--rm-text-secondary);
  margin: 0 0 var(--rm-space-1_5) 0;
}

.error-code {
  display: inline-block;
  background: var(--rm-danger-light);
  color: var(--rm-danger);
  font-family: var(--rm-font-mono);
  font-size: var(--rm-text-3xs);
  font-weight: var(--rm-weight-semibold);
  padding: 2px 8px;
  border-radius: var(--rm-radius-xs);
}

.recoverable-hint {
  font-size: var(--rm-text-xs);
  color: var(--rm-text-tertiary);
  margin-top: var(--rm-space-2);
}

.result-actions {
  margin-top: var(--rm-space-5);
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
